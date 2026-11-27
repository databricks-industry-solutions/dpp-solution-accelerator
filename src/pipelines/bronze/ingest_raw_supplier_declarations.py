"""
RAW files -> Bronze -> Silver -> Gold: supplier material declarations

Starts the data journey from raw files. Suppliers deliver material
declarations as JSON-lines files into a Unity Catalog volume. This file:

  bronze_supplier_declarations   Auto Loader streaming table, files as delivered
  silver_supplier_declarations   typed and validated against the supplier data
                                 contract (contracts/inbound/); bad lines are
                                 dropped and counted
  gold_supplier_declaration_coverage
                                 per supplier: is the passport evidence there,
                                 is it still valid, how much recycled content

The Gold table joins the file-delivered evidence with the supplier master that
comes from Lakebase, so the two ingestion paths meet in one governed model.
"""

import sys

import dlt
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

RAW_PATH = spark.conf.get("dpp.raw.declarations_path")  # noqa: F821

# The supplier data contract is the single source of the file schema, the
# Silver casts and the quality rules. Change the contract, not this file.
_BUNDLE_FILES = spark.conf.get("dpp.bundle.files_path")  # noqa: F821
if f"{_BUNDLE_FILES}/src" not in sys.path:
    sys.path.insert(0, f"{_BUNDLE_FILES}/src")

from contracts.dpp_contract import (  # noqa: E402
    expectations,
    load_contract,
    raw_schema_ddl,
    silver_select_exprs,
)

CONTRACT = load_contract(f"{_BUNDLE_FILES}/{spark.conf.get('dpp.contract.supplier_declaration')}")  # noqa: F821
CONTRACT_LABEL = f"{CONTRACT['id']} v{CONTRACT['version']}"
RULES = expectations(CONTRACT)


@dlt.table(
    name="bronze_supplier_declarations",
    comment="RAW supplier material declarations as delivered (JSON lines in a UC volume), ingested with Auto Loader",
)
def bronze_supplier_declarations() -> DataFrame:
    return (
        spark.readStream.format("cloudFiles")  # noqa: F821
        .option("cloudFiles.format", "json")
        .schema(raw_schema_ddl(CONTRACT))
        .load(RAW_PATH)
        .withColumn("_source_file", F.col("_metadata.file_path"))
        .withColumn("_ingested_at", F.current_timestamp())
    )


@dlt.table(
    name="silver_supplier_declarations",
    comment=(
        f"Supplier material declarations validated against the contract {CONTRACT_LABEL}. "
        "Records that break a 'drop' rule are rejected and counted; 'warn' rules are counted only."
    ),
)
@dlt.expect_all_or_drop(RULES["drop"])
@dlt.expect_all(RULES["warn"])
def silver_supplier_declarations() -> DataFrame:
    return (
        dlt.read("bronze_supplier_declarations")
        .selectExpr(*silver_select_exprs(CONTRACT), "_source_file", "_ingested_at")
        .withColumn("_contract", F.lit(CONTRACT_LABEL))
    )


@dlt.table(
    name="gold_supplier_declaration_coverage",
    comment=(
        "Per supplier: how much passport evidence has been delivered as material "
        "declarations, whether the certificates are still valid, and the average "
        "declared recycled content. Suppliers with no valid declaration are the "
        "data gaps to chase before a passport can be issued."
    ),
)
def gold_supplier_declaration_coverage() -> DataFrame:
    supplier = dlt.read("silver_supplier")
    decl = dlt.read("silver_supplier_declarations")
    per_supplier = decl.groupBy("supplier_id").agg(
        F.count("*").alias("declarations_received"),
        F.countDistinct("material_name").alias("materials_declared"),
        F.sum(F.when(F.col("certificate_valid_until") >= F.current_date(), 1).otherwise(0)).alias(
            "declarations_with_valid_certificate"
        ),
        F.round(F.avg("recycled_content_pct"), 1).alias("avg_declared_recycled_content_pct"),
        F.round(F.avg("carbon_kg_co2e_per_kg"), 2).alias("avg_declared_carbon_kg_co2e_per_kg"),
        F.max("declared_at").alias("latest_declaration_date"),
    )
    return (
        supplier.join(per_supplier, "supplier_id", "left")
        .select(
            supplier["supplier_id"],
            supplier["name"].alias("supplier_name"),
            supplier["country"].alias("supplier_country"),
            supplier["tier"].alias("supplier_tier"),
            supplier["risk_score"].alias("supplier_risk_score"),
            F.coalesce("declarations_received", F.lit(0)).alias("declarations_received"),
            F.coalesce("materials_declared", F.lit(0)).alias("materials_declared"),
            F.coalesce("declarations_with_valid_certificate", F.lit(0)).alias(
                "declarations_with_valid_certificate"
            ),
            "avg_declared_recycled_content_pct",
            "avg_declared_carbon_kg_co2e_per_kg",
            "latest_declaration_date",
            F.when(F.coalesce("declarations_with_valid_certificate", F.lit(0)) == 0, F.lit("NO_VALID_EVIDENCE"))
            .when(F.col("declarations_with_valid_certificate") < F.col("declarations_received"), F.lit("PARTLY_EXPIRED"))
            .otherwise(F.lit("COVERED"))
            .alias("evidence_status"),
        )
    )
