"""
Digital Product Passport -- Unity Catalog governance (tiered access)

A passport has three audiences: the public (consumers scanning the QR code),
restricted readers (authorities, recyclers, auditors) and the operator itself.
This job applies that tiering to the tables the pipeline produced:

  1. a column mask on the supplier contact in the file-delivered declarations:
     only members of the account group `dpp_restricted_readers` see it,
  2. an access-tier tag on every table (public / restricted / internal),
  3. a data-class tag on the masked column,
  4. a read-back of what is now in place (printed, so the job log is the proof).

Run it after the ingestion pipeline. It is idempotent.

Params (from the bundle): --catalog --schema
"""

from __future__ import annotations

import argparse

RESTRICTED_GROUP = "dpp_restricted_readers"

PUBLIC = ["gold_passport_complete", "gold_carbon_by_category", "gold_circularity_metrics"]
RESTRICTED = [
    "gold_supply_chain_lineage", "gold_supply_chain_summary", "gold_supplier_traceability",
    "gold_supplier_declaration_coverage", "gold_compliance_gap_analysis",
    "silver_supplier", "silver_supplier_declarations",
]
INTERNAL = ["bronze_supplier_declarations", "bronze_supplier"]


def main() -> None:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    args, _ = ap.parse_known_args()
    ns = f"`{args.catalog}`.`{args.schema}`"

    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()

    def run(sql: str) -> None:
        print(f"SQL> {sql}")
        spark.sql(sql)

    print("== 1. Column mask: supplier contact visible to the restricted tier only")
    run(
        f"CREATE OR REPLACE FUNCTION {ns}.mask_supplier_contact(contact STRING) RETURNS STRING "
        f"COMMENT 'Tiered access: supplier contact is visible only to account group {RESTRICTED_GROUP}' "
        f"RETURN CASE WHEN is_account_group_member('{RESTRICTED_GROUP}') THEN contact "
        "ELSE concat('***@', split_part(contact, '@', 2)) END"
    )
    run(f"ALTER MATERIALIZED VIEW {ns}.silver_supplier_declarations "
        f"ALTER COLUMN submitted_by SET MASK {ns}.mask_supplier_contact")

    print("\n== 2. Access-tier tags")
    for tier, tables in (("public", PUBLIC), ("restricted", RESTRICTED), ("internal", INTERNAL)):
        for t in tables:
            run(f"ALTER TABLE {ns}.{t} SET TAGS ('dpp_access_tier' = '{tier}')")

    # Own tag key on purpose: workspaces with governed tag policies restrict the
    # values of common keys such as `pii`.
    print("\n== 3. Data-class tag on the masked column")
    run(f"ALTER TABLE {ns}.silver_supplier_declarations ALTER COLUMN submitted_by "
        "SET TAGS ('dpp_data_class' = 'supplier_contact')")

    print("\n== 4. Read-back")
    print("-- table tags")
    spark.sql(
        f"SELECT table_name, tag_name, tag_value FROM `{args.catalog}`.information_schema.table_tags "
        f"WHERE schema_name = '{args.schema}' AND tag_name = 'dpp_access_tier' ORDER BY tag_value, table_name"
    ).show(50, truncate=False)
    print("-- column tags")
    spark.sql(
        f"SELECT table_name, column_name, tag_name, tag_value FROM `{args.catalog}`.information_schema.column_tags "
        f"WHERE schema_name = '{args.schema}' AND tag_name = 'dpp_data_class'"
    ).show(truncate=False)
    print("-- column masks")
    spark.sql(
        f"SELECT table_name, column_name, mask_name FROM `{args.catalog}`.information_schema.column_masks "
        f"WHERE table_schema = '{args.schema}'"
    ).show(truncate=False)
    is_member = spark.sql("SELECT is_account_group_member('" + RESTRICTED_GROUP + "')").first()[0]
    print("-- what the job identity sees (member of " + RESTRICTED_GROUP + ": " + str(is_member) + ")")
    spark.sql(
        f"SELECT declaration_id, supplier_name, material_name, submitted_by "
        f"FROM {ns}.silver_supplier_declarations ORDER BY declaration_id LIMIT 5"
    ).show(truncate=False)


if __name__ == "__main__":
    main()
