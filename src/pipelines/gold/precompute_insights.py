"""
Gold Layer -- Pre-computed AI Passport Insights

Runs ai_query over gold_passport_complete to generate structured AI insights
per product, writes them to a Gold Delta table (analyst-facing) AND upserts a
JSON copy into the Lakebase dpp.passport_insights serving table so the Passport
Viewer can serve cached insights instead of calling the Foundation Model API on
every page view.

Designed as a nightly spark_python_task. Self-authenticates to Lakebase via a
short-lived OAuth token (job identity) — no secrets.

Params (from the bundle): --catalog --schema --instance --database --model
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import uuid

import asyncpg


def _run_async(coro):
    """Run a coroutine to completion even inside an already-running event loop
    (Databricks serverless), via a fresh loop on a dedicated thread."""
    box: dict = {}

    def _runner() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            box["result"] = loop.run_until_complete(coro)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=_runner)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box.get("result")

# ai_query structured output. The DDL-string form (STRUCT<...>) allows only ONE
# top-level field, so use a JSON Schema response format for the flat object the
# Passport Viewer expects. With json_schema, ai_query returns a JSON STRING.
RESPONSE_FORMAT = json.dumps({
    "type": "json_schema",
    "json_schema": {
        "name": "dpp_insights",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "gaps": {"type": "array", "items": {"type": "string"}},
                "carbon_analysis": {"type": "string"},
                "compliance_alerts": {"type": "array", "items": {"type": "string"}},
                "circularity_recommendations": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "gaps", "carbon_analysis",
                "compliance_alerts", "circularity_recommendations",
            ],
        },
    },
})


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--catalog", default=os.environ.get("DPP_CATALOG", "dpp_dev"))
    ap.add_argument("--schema", default=os.environ.get("DPP_SCHEMA", "dpp"))
    ap.add_argument("--instance", default=os.environ.get("LAKEBASE_INSTANCE", "dpp-passport"))
    ap.add_argument("--database", default=os.environ.get("LAKEBASE_DATABASE", "databricks_postgres"))
    ap.add_argument(
        "--model",
        default=os.environ.get("AI_MODEL", "databricks-meta-llama-3-3-70b-instruct"),
    )
    args, _ = ap.parse_known_args()
    return args


def _insights_sql(catalog: str, schema: str, model: str) -> str:
    """Build the ai_query SQL. Arrays/structs are stringified with to_json so
    they can be concatenated into the prompt."""
    src = f"{catalog}.{schema}.gold_passport_complete"
    prompt = (
        "CONCAT("
        "'Analyze this EU Digital Product Passport. Reference actual numbers; no generic advice.\\n',"
        "'Product: ', product_name, ' (', product_category, ', id ', product_id, ')\\n',"
        "'Status: ', passport_status, ', complete: ', CAST(is_complete AS STRING), '\\n',"
        "'Serial: ', COALESCE(serial_number,'MISSING'), ', facility: ', COALESCE(production_facility,'MISSING'),"
        "', origin: ', COALESCE(country_of_origin,'MISSING'), '\\n',"
        "'Carbon kgCO2e total/mfg/transport/use/eol: ', COALESCE(CAST(carbon_footprint_kg AS STRING),'NA'), '/',"
        "COALESCE(CAST(carbon_manufacturing AS STRING),'NA'), '/', COALESCE(CAST(carbon_transport AS STRING),'NA'), '/',"
        "COALESCE(CAST(carbon_use_phase AS STRING),'NA'), '/', COALESCE(CAST(carbon_end_of_life AS STRING),'NA'), '\\n',"
        "'Energy kWh: ', COALESCE(CAST(energy_consumption_kwh AS STRING),'NA'),"
        "', water L: ', COALESCE(CAST(water_usage_liters AS STRING),'NA'),"
        "', LCA verified by: ', COALESCE(lca_verified_by,'NOT VERIFIED'), '\\n',"
        "'Materials (count ', CAST(material_count AS STRING), '): ', COALESCE(to_json(materials),'none'),"
        "'; renewable% ', COALESCE(CAST(renewable_content_pct AS STRING),'0'),"
        "'; hazardous ', CAST(contains_hazardous AS STRING), '; svhc ', CAST(contains_svhc AS STRING), '\\n',"
        "'Compliance compliant/pending/non-compliant: ', CAST(compliant_count AS STRING), '/',"
        "CAST(pending_count AS STRING), '/', CAST(non_compliant_count AS STRING),"
        "'; details: ', COALESCE(to_json(compliance_details),'none'), '\\n',"
        "'Circularity: repairability ', COALESCE(CAST(repairability_score AS STRING),'NA'), '/10, durability ',"
        "COALESCE(CAST(durability_years AS STRING),'NA'), 'y, recyclability ', COALESCE(CAST(recyclability_pct AS STRING),'NA'),"
        "'%, recycled ', COALESCE(CAST(circularity_recycled_pct AS STRING),'NA'), '%, take-back ',"
        "CAST(take_back_program AS STRING), ', refurbishable ', CAST(refurbishable AS STRING), '\\n',"
        "'Return: gaps (missing/incomplete data and why it matters), carbon_analysis (dominant lifecycle phase + concerns), "
        "compliance_alerts (expiring/non-compliant), circularity_recommendations (specific actions).'"
        ")"
    )
    return f"""
        SELECT
            passport_id,
            product_name,
            product_category,
            ai_query(
                '{model}',
                {prompt},
                modelParameters => named_struct('temperature', 0.1, 'max_tokens', 1000),
                responseFormat => '{RESPONSE_FORMAT}'
            ) AS insights
        FROM {src}
    """


def _resolve_runtime_lakebase(instance: str, database: str) -> tuple[str, str, str]:
    """(dns, user, oauth_token) via the Databricks runtime identity (REST API)."""
    import requests
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    host = w.config.host.rstrip("/")
    headers = w.config.authenticate()

    inst = requests.get(
        f"{host}/api/2.0/database/instances/{instance}", headers=headers, timeout=30
    )
    inst.raise_for_status()
    dns = inst.json()["read_write_dns"]

    cred = requests.post(
        f"{host}/api/2.0/database/credentials", headers=headers, timeout=30,
        json={"request_id": str(uuid.uuid4()), "instance_names": [instance]},
    )
    cred.raise_for_status()
    token = cred.json()["token"]

    me = requests.get(f"{host}/api/2.0/preview/scim/v2/Me", headers=headers, timeout=30)
    me.raise_for_status()
    return dns, me.json()["userName"], token


def main() -> None:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    args = _args()
    print(f"Pre-computing insights from {args.catalog}.{args.schema}.gold_passport_complete")

    spark = SparkSession.builder.getOrCreate()

    scored = spark.sql(_insights_sql(args.catalog, args.schema, args.model))

    # ai_query (json_schema) returns the structured JSON already as a STRING.
    out = scored.select(
        F.col("passport_id"),
        F.col("product_name"),
        F.col("product_category"),
        F.col("insights").alias("insights_json"),
        F.lit(args.model).alias("model"),
        F.current_timestamp().alias("generated_at"),
    )

    # 1) Analyst-facing Gold Delta table.
    uc_table = f"{args.catalog}.{args.schema}.dpp_passport_insights"
    out.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(uc_table)
    print(f"Wrote {uc_table}")

    # 2) Lakebase serving table (small driver-side upsert via asyncpg).
    rows = out.select("passport_id", "insights_json", "model").collect()
    dns, user, token = _resolve_runtime_lakebase(args.instance, args.database)
    records = [(str(r["passport_id"]), r["insights_json"], r["model"]) for r in rows]

    async def _upsert() -> None:
        conn = await asyncpg.connect(
            host=dns, port=5432, database=args.database, user=user,
            password=token, ssl=True,
        )
        # Treat uuid as text so the str passport_id passes through.
        await conn.set_type_codec(
            "uuid", schema="pg_catalog",
            encoder=lambda v: v, decoder=lambda v: v, format="text",
        )
        try:
            async with conn.transaction():
                await conn.executemany(
                    """
                    INSERT INTO dpp.passport_insights (passport_id, insights_json, model, generated_at)
                    VALUES ($1, $2, $3, now())
                    ON CONFLICT (passport_id) DO UPDATE
                      SET insights_json = EXCLUDED.insights_json,
                          model = EXCLUDED.model,
                          generated_at = now()
                    """,
                    records,
                )
        finally:
            await conn.close()

    _run_async(_upsert())
    print(f"Upserted {len(records)} rows into dpp.passport_insights")


if __name__ == "__main__":
    main()
