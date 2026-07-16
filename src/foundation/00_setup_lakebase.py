"""
Digital Product Passport -- Lakebase Setup (schema + generate + seed)

Single-process setup so it works as ONE Databricks serverless spark_python_task:
  1. apply 01_setup_lakebase_schema.sql (idempotent DDL),
  2. generate synthetic data IN MEMORY for the chosen --profile,
  3. seed it straight into Lakebase.

Why one process: serverless job tasks each run on their own compute and do NOT
share a local filesystem, so the older generate-to-JSON-then-seed-from-JSON
hand-off cannot work across tasks. Generating in memory and seeding directly
removes that dependency (and the JSON round-trip entirely).

Connection + auth resolution is reused from 03_seed_lakebase.get_connection
(runtime OAuth on Databricks; LAKEBASE_HOST/PASSWORD or DSN for local dev).

Params (from the bundle): --instance --database --profile
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys
from pathlib import Path


def _script_dir() -> Path:
    """Directory of this script. serverless spark_python_task has no __file__."""
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path(sys.argv[0]).resolve().parent


HERE = _script_dir()


def _load(mod_name: str, filename: str):
    """Load a sibling script by absolute path (numeric prefixes aren't importable)."""
    spec = importlib.util.spec_from_file_location(mod_name, HERE / filename)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def split_sql(sql: str) -> list[str]:
    """Split a SQL script into statements, respecting $$-quoted bodies and
    -- line comments so semicolons inside function/DO blocks don't split."""
    stmts: list[str] = []
    buf: list[str] = []
    in_dollar = False
    in_line_comment = False
    i, n = 0, len(sql)
    while i < n:
        if in_line_comment:
            buf.append(sql[i])
            if sql[i] == "\n":
                in_line_comment = False
            i += 1
            continue
        two = sql[i:i + 2]
        if not in_dollar and two == "--":
            in_line_comment = True
            buf.append(two)
            i += 2
            continue
        if two == "$$":
            in_dollar = not in_dollar
            buf.append(two)
            i += 2
            continue
        ch = sql[i]
        if ch == ";" and not in_dollar:
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def main() -> None:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--profile", default=os.environ.get("DPP_PROFILE", "furniture"))
    args, _ = ap.parse_known_args()

    print("=" * 60)
    print("DPP Lakebase Setup (schema + generate + seed)")
    print(f"Profile: {args.profile}")
    print("=" * 60)

    seeder = _load("seed_lakebase", "03_seed_lakebase.py")
    generator = _load("dpp_generator", "02_synthetic_data_generator.py")
    seeder.apply_cli_overrides()  # --instance / --database -> env

    ddl_path = HERE / "01_setup_lakebase_schema.sql"
    statements = split_sql(ddl_path.read_text(encoding="utf-8"))

    # 2. Generate synthetic data in memory (sync; before touching the DB).
    print(f"\nGenerating synthetic data (profile={args.profile})...")
    gen = generator.DPPDataGenerator(seed=generator.SEED, profile=args.profile)
    gen.generate_all()
    tables = {
        "manufacturer": [gen.manufacturer],
        "supplier": gen.suppliers,
        "product_passport": gen.passports,
        "product_origin": gen.origins,
        "product_materials": gen.materials,
        "environmental_impact": gen.impacts,
        "compliance_records": gen.compliance,
        "circularity_info": gen.circularity,
        "disposal_guidelines": gen.disposal,
        "passport_audit_log": gen.audit_log,
    }
    print(f"  {len(gen.passports)} passports, {len(gen.suppliers)} suppliers.")

    async def _run() -> None:
        conn = await seeder._connect()
        try:
            # 1. Schema (idempotent) -- each statement auto-commits.
            print(f"\nApplying schema ({len(statements)} statements)...")
            for stmt in statements:
                await conn.execute(stmt)
            print("Schema ready.")

            # 3. Seed straight from memory (no JSON files).
            print("\nSeeding Lakebase...")
            async with conn.transaction():
                await seeder.truncate_tables(conn)
                total = 0
                for table_name in seeder.TABLE_LOAD_ORDER:
                    records = tables.get(table_name) or []
                    if records:
                        count = await seeder.insert_table(conn, table_name, records)
                        print(f"  Inserted {count:>5} rows into dpp.{table_name}")
                        total += count
            print(f"\nTotal rows inserted: {total}. Done.")
        finally:
            await conn.close()

    seeder.run_async(_run())


if __name__ == "__main__":
    main()
