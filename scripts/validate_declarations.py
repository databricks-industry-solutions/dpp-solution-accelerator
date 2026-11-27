#!/usr/bin/env python3
"""
Check a supplier declaration file against the contract BEFORE sending it.

    python3 scripts/validate_declarations.py my_declarations.jsonl
    python3 scripts/validate_declarations.py my_declarations.jsonl --contract contracts/inbound/supplier_material_declaration.v1.json

Uses the same rules as the ingestion pipeline (both are derived from the
contract file). Needs Python 3.9+ and nothing else. Exit code 0 = every record
would be accepted, 1 = at least one record would be rejected, 2 = the file
cannot be read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from contracts.dpp_contract import load_contract, validate_records  # noqa: E402

DEFAULT_CONTRACT = ROOT / "contracts" / "inbound" / "supplier_material_declaration.v1.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="JSON-lines file, one declaration per line")
    ap.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    ap.add_argument("--max-problems", type=int, default=20, help="how many problem lines to print")
    args = ap.parse_args()

    contract = load_contract(args.contract)
    records = []
    try:
        with open(args.file, encoding="utf-8") as fh:
            for n, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"line {n}: not valid JSON ({e.msg})")
                    return 2
                if not isinstance(rec, dict):
                    print(f"line {n}: expected a JSON object")
                    return 2
                records.append(rec)
    except OSError as e:
        print(f"cannot read {args.file}: {e}")
        return 2

    s = validate_records(contract, records)
    print(f"Contract : {s['contract']}")
    print(f"Records  : {s['records']}")
    print(f"Accepted : {s['accepted']} ({s['accepted_with_warnings']} with warnings)")
    print(f"Rejected : {s['rejected']}")
    if s["unknown_fields"]:
        print(f"Ignored fields not in the contract: {', '.join(s['unknown_fields'])}")
    if s["violations_by_rule"]:
        print("\nViolations by rule:")
        for rule, count in s["violations_by_rule"].items():
            print(f"  {rule:<40} {count}")
        print(f"\nFirst {min(args.max_problems, len(s['problems']))} problems:")
        for p in s["problems"][: args.max_problems]:
            action = "REJECTED" if p["severity"] == "drop" else "warning"
            print(f"  record {p['line']:>5}  {action:<8}  {p['rule']}")
    return 1 if s["rejected"] else 0


if __name__ == "__main__":
    sys.exit(main())
