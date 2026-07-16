"""
Bronze Layer -- Lakebase Snapshot Ingestion via Spark Declarative Pipelines

Reads from the Lakebase PostgreSQL tables via JDBC and creates Bronze-layer
streaming tables in Unity Catalog. Each table is ingested as-is with minimal
transformation (add ingestion metadata only).

Each run performs a full table read (snapshot), not CDC.

Authentication uses the Databricks SDK to generate a short-lived OAuth token
for the Lakebase instance at pipeline start (no static secrets needed).

This pipeline is designed to run as a Spark Declarative Pipeline (SDP).
"""

import uuid

import dlt
import requests
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LAKEBASE_INSTANCE = spark.conf.get("dpp.lakebase.instance_name")  # noqa: F821
LAKEBASE_DATABASE = spark.conf.get("dpp.lakebase.database", "databricks_postgres")  # noqa: F821

# Generate OAuth token for Lakebase via REST API (compatible with all DBR versions)
_ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()  # noqa: F821
_host = _ctx.apiUrl().get()
_token = _ctx.apiToken().get()
_headers = {"Authorization": f"Bearer {_token}", "Content-Type": "application/json"}

# Get instance DNS
_inst_resp = requests.get(
    f"{_host}/api/2.0/database/instances/{LAKEBASE_INSTANCE}",
    headers=_headers, timeout=30,
)
_inst_resp.raise_for_status()
_inst = _inst_resp.json()
_lb_dns = _inst["read_write_dns"]

# Generate credential
_cred_resp = requests.post(
    f"{_host}/api/2.0/database/credentials",
    headers=_headers, timeout=30,
    json={"request_id": str(uuid.uuid4()), "instance_names": [LAKEBASE_INSTANCE]},
)
_cred_resp.raise_for_status()
_lb_token = _cred_resp.json()["token"]

# Get current user
_user_resp = requests.get(f"{_host}/api/2.0/preview/scim/v2/Me", headers=_headers, timeout=30)
_user_resp.raise_for_status()
_lb_user = _user_resp.json()["userName"]

LAKEBASE_JDBC_URL = f"jdbc:postgresql://{_lb_dns}:5432/{LAKEBASE_DATABASE}"
LAKEBASE_USER = _lb_user
LAKEBASE_PASSWORD = _lb_token

LAKEBASE_SCHEMA = "dpp"


def _read_lakebase_table(table_name: str) -> DataFrame:
    """Read a table from Lakebase via JDBC."""
    return (
        spark.read  # noqa: F821
        .format("jdbc")
        .option("url", LAKEBASE_JDBC_URL)
        .option("dbtable", f"{LAKEBASE_SCHEMA}.{table_name}")
        .option("user", LAKEBASE_USER)
        .option("password", LAKEBASE_PASSWORD)
        .option("driver", "org.postgresql.Driver")
        .option("fetchsize", "10000")
        .load()
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_table", F.lit(f"{LAKEBASE_SCHEMA}.{table_name}"))
    )


# ---------------------------------------------------------------------------
# Bronze Streaming Tables
# ---------------------------------------------------------------------------

@dlt.table(
    name="bronze_manufacturer",
    comment="Raw manufacturer data from Lakebase",
)
def bronze_manufacturer() -> DataFrame:
    return _read_lakebase_table("manufacturer")


@dlt.table(
    name="bronze_supplier",
    comment="Raw supplier data from Lakebase",
)
def bronze_supplier() -> DataFrame:
    return _read_lakebase_table("supplier")


@dlt.table(
    name="bronze_product_passport",
    comment="Raw product passport data from Lakebase",
)
def bronze_product_passport() -> DataFrame:
    return _read_lakebase_table("product_passport")


@dlt.table(
    name="bronze_product_origin",
    comment="Raw product origin / supply chain data from Lakebase",
)
def bronze_product_origin() -> DataFrame:
    return _read_lakebase_table("product_origin")


@dlt.table(
    name="bronze_product_materials",
    comment="Raw product materials composition from Lakebase",
)
def bronze_product_materials() -> DataFrame:
    return _read_lakebase_table("product_materials")


@dlt.table(
    name="bronze_environmental_impact",
    comment="Raw environmental impact / LCA data from Lakebase",
)
def bronze_environmental_impact() -> DataFrame:
    return _read_lakebase_table("environmental_impact")


@dlt.table(
    name="bronze_compliance_records",
    comment="Raw compliance records from Lakebase",
)
def bronze_compliance_records() -> DataFrame:
    return _read_lakebase_table("compliance_records")


@dlt.table(
    name="bronze_circularity_info",
    comment="Raw circularity information from Lakebase",
)
def bronze_circularity_info() -> DataFrame:
    return _read_lakebase_table("circularity_info")


@dlt.table(
    name="bronze_disposal_guidelines",
    comment="Raw disposal guidelines from Lakebase",
)
def bronze_disposal_guidelines() -> DataFrame:
    return _read_lakebase_table("disposal_guidelines")


@dlt.table(
    name="bronze_passport_audit_log",
    comment="Raw audit log entries from Lakebase",
)
def bronze_passport_audit_log() -> DataFrame:
    return _read_lakebase_table("passport_audit_log")


@dlt.table(
    name="bronze_app_access_log",
    comment="Raw app access events from Lakebase (empty unless ACCESS_LOG_ENABLED=true)",
)
def bronze_app_access_log() -> DataFrame:
    return _read_lakebase_table("app_access_log")
