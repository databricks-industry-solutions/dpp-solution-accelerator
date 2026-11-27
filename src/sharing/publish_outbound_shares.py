"""
Digital Product Passport -- outbound Delta Sharing

Publishes the outbound contract (contracts/outbound/passport_shares.v1.json):

  1. checks the contract against what exists: every source table is there, has
     the columns asked for, and carries a `dpp_access_tier` tag that the share
     is allowed to draw on. Any problem stops the job before anything is shared.
  2. creates one view per shared object, with the explicit column list from the
     contract (a new Gold column is never shared by accident),
  3. creates one share per audience and adds the views under their public names,
  4. prints what is now shared and to whom (the job log is the proof).

Recipients are not created here: who gets access is a decision per deployment.
See the README ("Sharing passports") for CREATE RECIPIENT and GRANT.

Needs CREATE SHARE on the metastore. Run after the governance job. Idempotent.

Params (from the bundle): --catalog --schema --bundle-files --contract [--share-prefix]
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--bundle-files", required=True)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--share-prefix", default="")
    args, _ = ap.parse_known_args()

    sys.path.insert(0, f"{args.bundle_files}/src")
    from contracts.dpp_contract import load_contract, plan_share_objects

    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()
    contract = load_contract(f"{args.bundle_files}/{args.contract}")
    ns = f"`{args.catalog}`.`{args.schema}`"
    label = f"{contract['id']} v{contract['version']}"
    print(f"Outbound contract: {label}")

    def run(sql: str) -> None:
        print(f"SQL> {sql}")
        spark.sql(sql)

    def q(text: str) -> str:
        return text.replace("'", "''")

    print("\n== 1. Check the contract against the catalog")
    sources = sorted({o["source"] for s in contract["shares"] for o in s["objects"]})
    in_list = ", ".join(f"'{t}'" for t in sources)
    columns: dict[str, list[str]] = {}
    for r in spark.sql(
        f"SELECT table_name, column_name FROM `{args.catalog}`.information_schema.columns "
        f"WHERE table_schema = '{args.schema}' AND table_name IN ({in_list})"
    ).collect():
        columns.setdefault(r["table_name"], []).append(r["column_name"])
    tiers = {
        r["table_name"]: r["tag_value"]
        for r in spark.sql(
            f"SELECT table_name, tag_value FROM `{args.catalog}`.information_schema.table_tags "
            f"WHERE schema_name = '{args.schema}' AND tag_name = 'dpp_access_tier' AND table_name IN ({in_list})"
        ).collect()
    }
    available = {t: {"columns": cols, "access_tier": tiers.get(t)} for t, cols in columns.items()}
    for t in sources:
        print(f"  {t:<40} tier={tiers.get(t)}  columns={len(columns.get(t, []))}")
    problems = plan_share_objects(contract, available)
    if problems:
        print("\nNothing was shared. Problems:")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(1)
    print("  OK: every source exists, has the columns and an allowed access tier")

    print("\n== 2. Views with the contract's column lists")
    # A view that is already in a share cannot be replaced, only altered.
    existing_views = {
        r["table_name"]
        for r in spark.sql(
            f"SELECT table_name FROM `{args.catalog}`.information_schema.views "
            f"WHERE table_schema = '{args.schema}'"
        ).collect()
    }
    for s in contract["shares"]:
        for o in s["objects"]:
            select = f"SELECT {', '.join(o['columns'])} FROM {ns}.{o['source']}"
            if o["view"] in existing_views:
                run(f"ALTER VIEW {ns}.{o['view']} AS {select}")
            else:
                run(
                    f"CREATE VIEW {ns}.{o['view']} "
                    f"COMMENT '{q(o.get('description', ''))} [{contract['id']}, share {s['name']}]' "
                    f"AS {select}"
                )
            run(f"ALTER VIEW {ns}.{o['view']} SET TAGS ('dpp_access_tier' = '{s['access_tier']}')")

    print("\n== 3. Shares")
    share_names = []
    existing_shares = {r["share"] for r in spark.sql("SHOW SHARES").collect()}
    for s in contract["shares"]:
        share = f"{args.share_prefix}{s['name']}"
        share_names.append(share)
        if share in existing_shares:
            print(f"  {share}: share exists, reusing it")
        else:
            try:
                run(f"CREATE SHARE `{share}` COMMENT '{q(s.get('audience', ''))} [{label}]'")
            except Exception as e:
                if "CREATE SHARE" not in str(e):
                    raise
                print(
                    f"\nThe views are in place, but this identity may not create shares.\n"
                    f"Either grant it CREATE SHARE on the metastore, or have a metastore admin run\n"
                    f"  CREATE SHARE `{share}`; ALTER SHARE `{share}` OWNER TO `<this identity>`;\n"
                    f"for each share in the contract, then re-run this job."
                )
                raise SystemExit(1)
        already = {r["name"] for r in spark.sql(f"SHOW ALL IN SHARE `{share}`").collect()}
        wanted = set()
        for o in s["objects"]:
            wanted.add(o["shared_as"])
            if o["shared_as"] in already:
                print(f"  {share}: {o['shared_as']} already shared")
                continue
            run(f"ALTER SHARE `{share}` ADD VIEW {ns}.{o['view']} AS {o['shared_as']}")
        extra = sorted(already - wanted)
        if extra:
            print(f"  NOTE {share} also contains objects that are not in the contract: {extra}")

    print("\n== 4. Read-back")
    for share in share_names:
        print(f"-- {share}: shared objects")
        spark.sql(f"SHOW ALL IN SHARE `{share}`").select("name", "type", "shared_object").show(50, truncate=False)
        print(f"-- {share}: recipients")
        spark.sql(f"SHOW GRANTS ON SHARE `{share}`").show(50, truncate=False)


if __name__ == "__main__":
    main()
