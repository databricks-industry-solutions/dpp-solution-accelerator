"""
Tests for the data contracts and the rules derived from them.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from contracts.dpp_contract import (  # noqa: E402
    ContractError,
    expectations,
    load_contract,
    plan_share_objects,
    raw_schema_ddl,
    silver_select_exprs,
    validate_record,
    validate_records,
)

INBOUND = ROOT / "contracts" / "inbound" / "supplier_material_declaration.v1.json"
OUTBOUND = ROOT / "contracts" / "outbound" / "passport_shares.v1.json"

GOOD = {
    "declaration_id": "DECL-1", "supplier_id": "S-1", "supplier_name": "  Acme  ",
    "material_name": "Lithium", "recycled_content_pct": 12.5, "carbon_kg_co2e_per_kg": 3.1,
    "country_of_origin": "se", "certificate_number": "CERT-1",
    "certificate_valid_until": "2027-01-31", "declared_at": "2026-05-01",
    "submitted_by": "compliance@acme.example",
}


@pytest.fixture(scope="module")
def inbound() -> dict:
    return load_contract(str(INBOUND))


@pytest.fixture(scope="module")
def outbound() -> dict:
    return load_contract(str(OUTBOUND))


def _write(tmp_path, contract: dict) -> str:
    p = tmp_path / "c.json"
    p.write_text(json.dumps(contract))
    return str(p)


# ---- inbound ---------------------------------------------------------------

def test_raw_schema_keeps_dates_as_text(inbound):
    ddl = raw_schema_ddl(inbound)
    assert "declared_at STRING" in ddl
    assert "recycled_content_pct DOUBLE" in ddl
    assert "DATE" not in ddl


def test_silver_exprs_type_and_normalize(inbound):
    exprs = silver_select_exprs(inbound)
    assert "try_cast(declared_at AS DATE) AS declared_at" in exprs
    assert "trim(supplier_name) AS supplier_name" in exprs
    assert "upper(country_of_origin) AS country_of_origin" in exprs
    assert len(exprs) == len(inbound["fields"])


def test_expectations_split_by_severity(inbound):
    rules = expectations(inbound)
    assert rules["drop"]["has_valid_supplier_id"] == "supplier_id IS NOT NULL"
    assert rules["drop"]["has_valid_declared_at"] == "declared_at IS NOT NULL"
    assert rules["drop"]["recycled_content_pct_min_0_max_100"] == (
        "recycled_content_pct IS NULL OR (recycled_content_pct >= 0 AND recycled_content_pct <= 100)"
    )
    assert "has_valid_certificate_number" in rules["warn"]
    assert not set(rules["drop"]) & set(rules["warn"])


def test_good_record_is_clean(inbound):
    assert validate_record(inbound, GOOD) == []


@pytest.mark.parametrize(
    "change, rule, severity",
    [
        ({"supplier_id": None}, "has_valid_supplier_id", "drop"),
        ({"recycled_content_pct": 140.0}, "recycled_content_pct_min_0_max_100", "drop"),
        ({"recycled_content_pct": None}, "has_valid_recycled_content_pct", "drop"),
        ({"recycled_content_pct": "12"}, "has_valid_recycled_content_pct", "drop"),
        ({"declared_at": "not-a-date"}, "has_valid_declared_at", "drop"),
        ({"declared_at": "2026-02-30"}, "has_valid_declared_at", "drop"),
        ({"certificate_number": None}, "has_valid_certificate_number", "warn"),
        ({"carbon_kg_co2e_per_kg": -1}, "carbon_kg_co2e_per_kg_min_0", "warn"),
    ],
)
def test_each_rule_fires(inbound, change, rule, severity):
    broken = validate_record(inbound, {**GOOD, **change})
    assert (rule, severity) in {(b["rule"], b["severity"]) for b in broken}


def test_optional_fields_may_be_missing(inbound):
    rec = {k: v for k, v in GOOD.items() if k not in ("certificate_valid_until", "carbon_kg_co2e_per_kg")}
    assert validate_record(inbound, rec) == []


def test_summary_counts(inbound):
    records = [
        GOOD,
        {**GOOD, "supplier_id": None},
        {**GOOD, "certificate_number": None},
        {**GOOD, "extra_field": 1},
    ]
    s = validate_records(inbound, records)
    assert (s["records"], s["accepted"], s["rejected"], s["accepted_with_warnings"]) == (4, 3, 1, 1)
    assert s["unknown_fields"] == ["extra_field"]
    assert s["problems"][0]["line"] == 2


def test_validator_agrees_with_the_synthetic_landing_files(inbound):
    """The generator plants three kinds of dirty line; the contract must reject exactly those."""
    spec = importlib.util.spec_from_file_location(
        "land_raw", ROOT / "src" / "foundation" / "04_land_raw_declarations.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    suppliers = [{"supplier_id": f"S-{i}", "name": f"Supplier {i}", "country": "DE"} for i in range(120)]
    materials = [{"material_name": m} for m in ("Lithium", "Cobalt", "Nickel", "Graphite", "Copper", "Aluminium")]
    decls = mod.build_declarations(suppliers, materials, date(2026, 6, 1), seed=42)
    dirty = sum(
        1 for d in decls
        if d["supplier_id"] is None or d["recycled_content_pct"] > 100 or d["declared_at"] == "not-a-date"
    )
    s = validate_records(inbound, decls)
    assert dirty > 0
    assert s["rejected"] == dirty
    assert s["unknown_fields"] == []


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda c: c["fields"].append(dict(c["fields"][0])), "duplicate field"),
        (lambda c: c["fields"][0].update(type="int"), "type must be"),
        (lambda c: c["fields"][0].update(name="bad name; DROP"), "not a valid identifier"),
        (lambda c: c["fields"][0].update(min=0), "needs a number on a double field"),
        (lambda c: c["fields"][0].update(on_violation="ignore"), "on_violation"),
    ],
)
def test_malformed_inbound_contract_is_refused(inbound, tmp_path, mutate, message):
    c = copy.deepcopy(inbound)
    mutate(c)
    with pytest.raises(ContractError, match=message):
        load_contract(_write(tmp_path, c))


# ---- outbound --------------------------------------------------------------

def _available(outbound, tier_of):
    avail: dict[str, dict] = {}
    for s in outbound["shares"]:
        for o in s["objects"]:
            entry = avail.setdefault(o["source"], {"columns": [], "access_tier": tier_of(o["source"])})
            entry["columns"] = sorted(set(entry["columns"]) | set(o["columns"]))
    return avail


TIER = {
    "gold_passport_complete": "public", "gold_carbon_by_category": "public",
    "gold_circularity_metrics": "public", "gold_supply_chain_lineage": "restricted",
    "gold_supplier_declaration_coverage": "restricted",
}


def test_outbound_plan_is_clean_with_the_governance_tags(outbound):
    assert plan_share_objects(outbound, _available(outbound, TIER.get)) == []


def test_restricted_table_cannot_enter_the_public_share(outbound):
    c = copy.deepcopy(outbound)
    c["shares"][0]["objects"][0]["source"] = "gold_supply_chain_lineage"
    avail = _available(c, TIER.get)
    problems = plan_share_objects(c, avail)
    assert any("tagged 'restricted', not allowed" in p for p in problems)


def test_untagged_missing_table_and_missing_column_are_reported(outbound):
    avail = _available(outbound, TIER.get)
    avail["gold_carbon_by_category"]["access_tier"] = None
    del avail["gold_circularity_metrics"]
    avail["gold_passport_complete"]["columns"].remove("gtin")
    problems = "\n".join(plan_share_objects(outbound, avail))
    assert "has no dpp_access_tier tag" in problems
    assert "gold_circularity_metrics does not exist" in problems
    assert "['gtin']" in problems


def test_public_share_exposes_no_supplier_or_internal_columns(outbound):
    public = outbound["shares"][0]
    cols = {c for o in public["objects"] for c in o["columns"]}
    assert not {c for c in cols if "supplier" in c or "risk" in c or c in ("materials", "compliance_details")}


def test_no_share_exposes_risk_scores_or_contacts(outbound):
    cols = {c for s in outbound["shares"] for o in s["objects"] for c in o["columns"]}
    assert not {c for c in cols if "risk" in c or c == "submitted_by"}


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda c: c["shares"][0].update(allowed_source_tiers=["public", "internal"]), "internal data cannot be shared"),
        (lambda c: c["shares"][0]["objects"][0].update(shared_as="passport"), "shared_as must be"),
        (lambda c: c["shares"][0]["objects"][0].update(columns=["a", "a"]), "without duplicates"),
        (lambda c: c["shares"][1]["objects"][0].update(view="out_public_passport"), "defined twice"),
        (lambda c: c["shares"][0]["objects"][0].update(columns=["a; DROP TABLE x"]), "not a valid identifier"),
    ],
)
def test_malformed_outbound_contract_is_refused(outbound, tmp_path, mutate, message):
    c = copy.deepcopy(outbound)
    mutate(c)
    with pytest.raises(ContractError, match=message):
        load_contract(_write(tmp_path, c))
