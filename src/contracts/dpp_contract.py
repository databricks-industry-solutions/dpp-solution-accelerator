"""
Digital Product Passport -- data contracts

One contract file describes a data exchange; everything else is derived from
it, so the rules live in exactly one place:

  inbound  (contracts/inbound/*.json)   what a supplier delivers
      -> the Auto Loader schema, the Silver casts and the pipeline expectations
      -> the validator a supplier runs before sending (scripts/validate_declarations.py)
  outbound (contracts/outbound/*.json)  what the manufacturer shares, per audience
      -> the views and Delta Sharing shares (src/sharing/publish_outbound_shares.py)

Standard library only, on purpose: the same module runs in the pipeline, in a
job and on a supplier's laptop.

Rule semantics (identical in SQL and in Python):
  a value is first typed (string / double / date); a value that cannot be typed
  is null. `required` means the typed value is not null. `min` / `max` apply to
  non-null values only. `on_violation` is `drop` (the record is rejected) or
  `warn` (the record is kept and counted).
"""

from __future__ import annotations

import json
import re
from datetime import date

TYPES = {"string": "STRING", "double": "DOUBLE", "date": "DATE"}
NORMALIZERS = {"trim", "upper"}
SEVERITIES = {"drop", "warn"}
TIERS = ("public", "restricted", "internal")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHARED_AS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ContractError(ValueError):
    """The contract file itself is malformed."""


def _name(value, what: str) -> str:
    if not isinstance(value, str) or not _NAME.match(value):
        raise ContractError(f"{what}: {value!r} is not a valid identifier")
    return value


def load_contract(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        contract = json.load(fh)
    for key in ("id", "version", "direction"):
        if not contract.get(key):
            raise ContractError(f"{path}: missing '{key}'")
    if contract["direction"] == "inbound":
        _check_inbound(contract)
    elif contract["direction"] == "outbound":
        _check_outbound(contract)
    else:
        raise ContractError(f"{path}: direction must be inbound or outbound")
    return contract


# --------------------------------------------------------------------------
# Inbound
# --------------------------------------------------------------------------

def _check_inbound(contract: dict) -> None:
    fields = contract.get("fields") or []
    if not fields:
        raise ContractError("inbound contract has no fields")
    seen = set()
    for f in fields:
        name = _name(f.get("name"), "field name")
        if name in seen:
            raise ContractError(f"duplicate field {name}")
        seen.add(name)
        if f.get("type") not in TYPES:
            raise ContractError(f"{name}: type must be one of {sorted(TYPES)}")
        if f.get("normalize") and (f["normalize"] not in NORMALIZERS or f["type"] != "string"):
            raise ContractError(f"{name}: normalize must be one of {sorted(NORMALIZERS)} on a string field")
        if f.get("on_violation", "drop") not in SEVERITIES:
            raise ContractError(f"{name}: on_violation must be drop or warn")
        if f.get("access_tier", "internal") not in TIERS:
            raise ContractError(f"{name}: access_tier must be one of {TIERS}")
        for bound in ("min", "max"):
            if bound in f and (f["type"] != "double" or isinstance(f[bound], bool)
                               or not isinstance(f[bound], (int, float))):
                raise ContractError(f"{name}: {bound} needs a number on a double field")


def raw_schema_ddl(contract: dict) -> str:
    """Schema of the files as delivered. Dates arrive as text and are typed in Silver."""
    return ", ".join(
        f"{f['name']} {'STRING' if f['type'] == 'date' else TYPES[f['type']]}" for f in contract["fields"]
    )


def silver_select_exprs(contract: dict) -> list[str]:
    """SQL expressions that type and normalize the raw columns."""
    exprs = []
    for f in contract["fields"]:
        n = f["name"]
        if f["type"] == "date":
            exprs.append(f"try_cast({n} AS DATE) AS {n}")
        elif f.get("normalize"):
            exprs.append(f"{f['normalize']}({n}) AS {n}")
        else:
            exprs.append(n)
    return exprs


def rules(contract: dict) -> list[dict]:
    """Every quality rule in the contract: name, field, severity, SQL expression."""
    out = []
    for f in contract["fields"]:
        n, severity = f["name"], f.get("on_violation", "drop")
        if f.get("required"):
            out.append({"name": f"has_valid_{n}", "field": n, "kind": "required",
                        "severity": severity, "sql": f"{n} IS NOT NULL"})
        lo, hi = f.get("min"), f.get("max")
        if lo is not None or hi is not None:
            parts = ([f"{n} >= {lo}"] if lo is not None else []) + ([f"{n} <= {hi}"] if hi is not None else [])
            label = "_".join(
                ([f"min_{lo}"] if lo is not None else []) + ([f"max_{hi}"] if hi is not None else [])
            ).replace(".", "p").replace("-", "neg")
            out.append({"name": f"{n}_{label}", "field": n, "kind": "range", "severity": severity,
                        "min": lo, "max": hi, "sql": f"{n} IS NULL OR ({' AND '.join(parts)})"})
    return out


def expectations(contract: dict) -> dict[str, dict[str, str]]:
    """Pipeline expectations, split by what happens on violation."""
    result: dict[str, dict[str, str]] = {"drop": {}, "warn": {}}
    for r in rules(contract):
        result[r["severity"]][r["name"]] = r["sql"]
    return result


def _typed(field: dict, value):
    """Type a raw value the way the pipeline does; anything untypable is None."""
    if value is None:
        return None
    if field["type"] == "string":
        if not isinstance(value, str):
            return None
        if field.get("normalize") == "trim":
            return value.strip()
        if field.get("normalize") == "upper":
            return value.upper()
        return value
    if field["type"] == "double":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)
    if not isinstance(value, str) or not _ISO_DATE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def validate_record(contract: dict, record: dict) -> list[dict]:
    """The rules this record breaks: [{'rule', 'field', 'severity'}]. Empty means clean."""
    by_name = {f["name"]: f for f in contract["fields"]}
    broken = []
    for r in rules(contract):
        value = _typed(by_name[r["field"]], record.get(r["field"]))
        if r["kind"] == "required":
            ok = value is not None
        else:
            ok = value is None or (
                (r["min"] is None or value >= r["min"]) and (r["max"] is None or value <= r["max"])
            )
        if not ok:
            broken.append({"rule": r["name"], "field": r["field"], "severity": r["severity"]})
    return broken


def validate_records(contract: dict, records: list[dict]) -> dict:
    """Summary a supplier can act on before sending a file."""
    known = {f["name"] for f in contract["fields"]}
    by_rule: dict[str, int] = {}
    rejected, warned, unknown = 0, 0, set()
    problems = []
    for i, rec in enumerate(records, start=1):
        unknown |= set(rec) - known
        broken = validate_record(contract, rec)
        for b in broken:
            by_rule[b["rule"]] = by_rule.get(b["rule"], 0) + 1
            problems.append({"line": i, **b})
        if any(b["severity"] == "drop" for b in broken):
            rejected += 1
        elif broken:
            warned += 1
    return {
        "contract": f"{contract['id']} v{contract['version']}",
        "records": len(records),
        "accepted": len(records) - rejected,
        "rejected": rejected,
        "accepted_with_warnings": warned,
        "violations_by_rule": dict(sorted(by_rule.items())),
        "unknown_fields": sorted(unknown),
        "problems": problems,
    }


# --------------------------------------------------------------------------
# Outbound
# --------------------------------------------------------------------------

def _check_outbound(contract: dict) -> None:
    shares = contract.get("shares") or []
    if not shares:
        raise ContractError("outbound contract has no shares")
    share_names, view_names = set(), set()
    for s in shares:
        name = _name(s.get("name"), "share name")
        if name in share_names:
            raise ContractError(f"duplicate share {name}")
        share_names.add(name)
        tiers = s.get("allowed_source_tiers") or []
        if not tiers or any(t not in TIERS for t in tiers):
            raise ContractError(f"{name}: allowed_source_tiers must list tiers out of {TIERS}")
        if "internal" in tiers:
            raise ContractError(f"{name}: internal data cannot be shared")
        aliases = set()
        for o in s.get("objects") or []:
            view = _name(o.get("view"), f"{name}: view")
            if view in view_names:
                raise ContractError(f"view {view} is defined twice")
            view_names.add(view)
            _name(o.get("source"), f"{view}: source")
            if not isinstance(o.get("shared_as"), str) or not _SHARED_AS.match(o["shared_as"]):
                raise ContractError(f"{view}: shared_as must be <schema>.<name>")
            if o["shared_as"] in aliases:
                raise ContractError(f"{name}: {o['shared_as']} is shared twice")
            aliases.add(o["shared_as"])
            cols = o.get("columns") or []
            if not cols or len(set(cols)) != len(cols):
                raise ContractError(f"{view}: columns must be a non-empty list without duplicates")
            for c in cols:
                _name(c, f"{view}: column")
        if not s.get("objects"):
            raise ContractError(f"{name}: no objects")


def plan_share_objects(contract: dict, available: dict[str, dict]) -> list[str]:
    """Check an outbound contract against what exists. Returns the problems found.

    available: {table_name: {"columns": [..], "access_tier": "public" | "restricted" | ... | None}}
    """
    problems = []
    for s in contract["shares"]:
        for o in s["objects"]:
            src = available.get(o["source"])
            if src is None:
                problems.append(f"{s['name']}: source table {o['source']} does not exist")
                continue
            tier = src.get("access_tier")
            if tier is None:
                problems.append(f"{s['name']}: {o['source']} has no dpp_access_tier tag (run the governance job first)")
            elif tier not in s["allowed_source_tiers"]:
                problems.append(f"{s['name']}: {o['source']} is tagged '{tier}', not allowed in this share")
            missing = [c for c in o["columns"] if c not in src["columns"]]
            if missing:
                problems.append(f"{s['name']}: {o['view']} asks for columns {o['source']} does not have: {missing}")
    return problems
