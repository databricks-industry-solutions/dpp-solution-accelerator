"""
Silver Layer -- Data Cleansing and Conformance

Reads from Bronze streaming tables, applies data quality expectations,
standardizes formats, and produces clean Silver materialized views.

This pipeline is designed to run as a Spark Declarative Pipeline (SDP).
"""

import dlt
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql import types as T


# ---------------------------------------------------------------------------
# Silver Materialized Views
# ---------------------------------------------------------------------------

@dlt.table(
    name="silver_manufacturer",
    comment="Cleaned manufacturer data with validated fields",
)
@dlt.expect_or_drop("valid_manufacturer_id", "manufacturer_id IS NOT NULL")
@dlt.expect_or_drop("valid_country_code", "LENGTH(country) = 3")
@dlt.expect("has_name", "name IS NOT NULL AND LENGTH(TRIM(name)) > 0")
def silver_manufacturer() -> DataFrame:
    return (
        dlt.read("bronze_manufacturer")
        .select(
            F.col("manufacturer_id"),
            F.trim(F.col("name")).alias("name"),
            F.upper(F.col("country")).alias("country"),
            F.trim(F.col("registration_number")).alias("registration_number"),
            F.trim(F.col("website")).alias("website"),
            F.col("created_at"),
            F.col("updated_at"),
            F.col("_ingested_at"),
        )
    )


@dlt.table(
    name="silver_supplier",
    comment="Cleaned supplier data with risk scoring validation",
)
@dlt.expect_or_drop("valid_supplier_id", "supplier_id IS NOT NULL")
@dlt.expect_or_drop("valid_country_code", "LENGTH(country) = 3")
@dlt.expect("valid_tier", "tier BETWEEN 1 AND 3")
@dlt.expect("valid_risk_score", "risk_score BETWEEN 0.0 AND 10.0")
def silver_supplier() -> DataFrame:
    return (
        dlt.read("bronze_supplier")
        .select(
            F.col("supplier_id"),
            F.trim(F.col("name")).alias("name"),
            F.upper(F.col("country")).alias("country"),
            F.col("tier"),
            F.col("parent_supplier_id"),
            F.col("risk_score"),
            F.col("certifications"),
            F.col("last_audit_date"),
            F.col("active"),
            F.col("created_at"),
            F.col("updated_at"),
            F.col("_ingested_at"),
        )
    )


@dlt.table(
    name="silver_product_passport",
    comment="Cleaned product passport data with status validation",
)
@dlt.expect_or_drop("valid_passport_id", "passport_id IS NOT NULL")
@dlt.expect_or_drop("valid_product_id", "product_id IS NOT NULL")
@dlt.expect("valid_gtin_length", "gtin IS NULL OR LENGTH(gtin) = 14")
@dlt.expect(
    "valid_status",
    "passport_status IN ('draft', 'active', 'expired', 'revoked')",
)
@dlt.expect("has_manufacturer", "manufacturer_id IS NOT NULL")
def silver_product_passport() -> DataFrame:
    return (
        dlt.read("bronze_product_passport")
        .select(
            F.col("passport_id"),
            F.trim(F.col("product_id")).alias("product_id"),
            F.col("gtin"),
            F.col("serial_number"),
            F.col("batch_lot_number"),
            F.trim(F.col("product_name")).alias("product_name"),
            F.trim(F.col("product_category")).alias("product_category"),
            F.col("manufacturer_id"),
            F.col("production_date"),
            F.trim(F.col("production_facility")).alias("production_facility"),
            F.upper(F.col("country_of_origin")).alias("country_of_origin"),
            F.lower(F.trim(F.col("passport_status"))).alias("passport_status"),
            F.col("qr_code_url"),
            F.col("created_at"),
            F.col("updated_at"),
            F.col("_ingested_at"),
            # Data completeness flag
            F.when(
                F.col("serial_number").isNotNull()
                & F.col("production_facility").isNotNull()
                & F.col("country_of_origin").isNotNull()
                & F.col("qr_code_url").isNotNull(),
                F.lit(True),
            ).otherwise(F.lit(False)).alias("is_complete"),
        )
    )


@dlt.table(
    name="silver_product_origin",
    comment="Cleaned product origin with supply chain traceability",
)
@dlt.expect_or_drop("valid_origin_id", "origin_id IS NOT NULL")
@dlt.expect_or_drop("valid_passport_ref", "passport_id IS NOT NULL")
@dlt.expect_or_drop("valid_supplier_ref", "supplier_id IS NOT NULL")
@dlt.expect("valid_tier", "supply_chain_tier BETWEEN 1 AND 3")
def silver_product_origin() -> DataFrame:
    return (
        dlt.read("bronze_product_origin")
        .select(
            F.col("origin_id"),
            F.col("passport_id"),
            F.col("supplier_id"),
            F.col("supply_chain_tier"),
            F.trim(F.col("component_name")).alias("component_name"),
            F.upper(F.col("source_country")).alias("source_country"),
            F.trim(F.col("source_region")).alias("source_region"),
            F.trim(F.col("certification")).alias("certification"),
            F.col("certification_expiry"),
            F.col("traceability_proof"),
            F.col("_ingested_at"),
            # Certification expiry alert
            F.when(
                F.col("certification_expiry").isNotNull()
                & (F.col("certification_expiry") < F.date_add(F.current_date(), 30)),
                F.lit(True),
            ).otherwise(F.lit(False)).alias("certification_expiring_soon"),
        )
    )


@dlt.table(
    name="silver_product_materials",
    comment="Cleaned product materials with REACH/SVHC flags",
)
@dlt.expect_or_drop("valid_material_id", "material_id IS NOT NULL")
@dlt.expect_or_drop("valid_passport_ref", "passport_id IS NOT NULL")
@dlt.expect("valid_percentage", "percentage_by_weight BETWEEN 0 AND 100")
@dlt.expect(
    "valid_recycled_pct",
    "recycled_content_pct IS NULL OR recycled_content_pct BETWEEN 0 AND 100",
)
def silver_product_materials() -> DataFrame:
    return (
        dlt.read("bronze_product_materials")
        .select(
            F.col("material_id"),
            F.col("passport_id"),
            F.trim(F.col("material_name")).alias("material_name"),
            F.trim(F.col("material_category")).alias("material_category"),
            F.col("percentage_by_weight"),
            F.col("recycled_content_pct"),
            F.col("renewable_flag"),
            F.col("hazardous_flag"),
            F.trim(F.col("cas_number")).alias("cas_number"),
            F.col("reach_compliant"),
            F.col("svhc_flag"),
            F.col("_ingested_at"),
        )
    )


@dlt.table(
    name="silver_environmental_impact",
    comment="Cleaned environmental impact / LCA data",
)
@dlt.expect_or_drop("valid_impact_id", "impact_id IS NOT NULL")
@dlt.expect_or_drop("valid_passport_ref", "passport_id IS NOT NULL")
@dlt.expect("positive_carbon", "carbon_footprint_kg IS NULL OR carbon_footprint_kg >= 0")
@dlt.expect("positive_energy", "energy_consumption_kwh IS NULL OR energy_consumption_kwh >= 0")
def silver_environmental_impact() -> DataFrame:
    return (
        dlt.read("bronze_environmental_impact")
        .select(
            F.col("impact_id"),
            F.col("passport_id"),
            F.col("carbon_footprint_kg"),
            F.col("carbon_manufacturing"),
            F.col("carbon_transport"),
            F.col("carbon_use_phase"),
            F.col("carbon_end_of_life"),
            F.col("energy_consumption_kwh"),
            F.col("water_usage_liters"),
            F.trim(F.col("lca_methodology")).alias("lca_methodology"),
            F.trim(F.col("lca_data_source")).alias("lca_data_source"),
            F.col("assessment_date"),
            F.trim(F.col("verified_by")).alias("verified_by"),
            F.col("_ingested_at"),
            # Flag unverified assessments
            F.when(
                F.col("verified_by").isNull() | F.col("lca_methodology").isNull(),
                F.lit(True),
            ).otherwise(F.lit(False)).alias("needs_verification"),
        )
    )


@dlt.table(
    name="silver_compliance_records",
    comment="Cleaned compliance records with status normalization",
)
@dlt.expect_or_drop("valid_compliance_id", "compliance_id IS NOT NULL")
@dlt.expect_or_drop("valid_passport_ref", "passport_id IS NOT NULL")
@dlt.expect(
    "valid_status",
    "compliance_status IN ('compliant', 'pending', 'non_compliant', 'expired')",
)
def silver_compliance_records() -> DataFrame:
    return (
        dlt.read("bronze_compliance_records")
        .select(
            F.col("compliance_id"),
            F.col("passport_id"),
            F.trim(F.col("regulation_name")).alias("regulation_name"),
            F.trim(F.col("regulation_version")).alias("regulation_version"),
            F.lower(F.trim(F.col("compliance_status"))).alias("compliance_status"),
            F.trim(F.col("certificate_ref")).alias("certificate_ref"),
            F.trim(F.col("issuing_body")).alias("issuing_body"),
            F.col("issue_date"),
            F.col("expiry_date"),
            F.col("document_url"),
            F.col("notes"),
            F.col("_ingested_at"),
            # Expired certificate detection
            F.when(
                F.col("expiry_date").isNotNull()
                & (F.col("expiry_date") < F.current_date()),
                F.lit(True),
            ).otherwise(F.lit(False)).alias("is_expired"),
        )
    )


@dlt.table(
    name="silver_circularity_info",
    comment="Cleaned circularity information",
)
@dlt.expect_or_drop("valid_circularity_id", "circularity_id IS NOT NULL")
@dlt.expect_or_drop("valid_passport_ref", "passport_id IS NOT NULL")
@dlt.expect("valid_repairability", "repairability_score IS NULL OR repairability_score BETWEEN 0 AND 10")
def silver_circularity_info() -> DataFrame:
    return (
        dlt.read("bronze_circularity_info")
        .select(
            F.col("circularity_id"),
            F.col("passport_id"),
            F.col("durability_years"),
            F.col("repairability_score"),
            F.col("spare_parts_available"),
            F.col("spare_parts_years"),
            F.col("refurbishable"),
            F.col("recycled_content_pct"),
            F.col("recyclability_pct"),
            F.col("take_back_program"),
            F.col("second_life_options"),
            F.col("_ingested_at"),
        )
    )


@dlt.table(
    name="silver_disposal_guidelines",
    comment="Cleaned disposal guidelines",
)
@dlt.expect_or_drop("valid_disposal_id", "disposal_id IS NOT NULL")
@dlt.expect_or_drop("valid_passport_ref", "passport_id IS NOT NULL")
@dlt.expect("positive_weight", "weight_kg IS NULL OR weight_kg >= 0")
def silver_disposal_guidelines() -> DataFrame:
    return (
        dlt.read("bronze_disposal_guidelines")
        .select(
            F.col("disposal_id"),
            F.col("passport_id"),
            F.trim(F.col("component_name")).alias("component_name"),
            F.trim(F.col("disposal_method")).alias("disposal_method"),
            F.col("disassembly_steps"),
            F.trim(F.col("recycling_code")).alias("recycling_code"),
            F.col("local_collection_info"),
            F.col("special_handling"),
            F.col("weight_kg"),
            F.col("_ingested_at"),
        )
    )
