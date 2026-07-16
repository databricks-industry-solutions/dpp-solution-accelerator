"""
Gold Layer -- Complete Product Passport (Denormalized View)

Creates a single wide materialized view that joins all passport-related
Silver tables into one comprehensive record per product. This is the
primary view for passport lookups and the serving layer.
"""

import dlt
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


@dlt.table(
    name="gold_passport_complete",
    comment=(
        "Fully denormalized product passport combining manufacturer, materials, "
        "environmental impact, compliance, circularity, and disposal data. "
        "One row per passport with nested/aggregated child data."
    ),
)
def gold_passport_complete() -> DataFrame:
    """Build the complete passport view by joining all Silver tables."""
    passport = dlt.read("silver_product_passport")
    manufacturer = dlt.read("silver_manufacturer")
    materials = dlt.read("silver_product_materials")
    impact = dlt.read("silver_environmental_impact")
    compliance = dlt.read("silver_compliance_records")
    circularity = dlt.read("silver_circularity_info")

    # Aggregate materials per passport
    materials_agg = (
        materials
        .groupBy("passport_id")
        .agg(
            F.count("*").alias("material_count"),
            F.collect_list(
                F.struct(
                    "material_name", "material_category",
                    "percentage_by_weight", "recycled_content_pct",
                    "renewable_flag", "hazardous_flag", "cas_number",
                )
            ).alias("materials"),
            F.sum(
                F.when(F.col("renewable_flag") == True, F.col("percentage_by_weight"))  # noqa: E712
                .otherwise(0)
            ).alias("renewable_content_pct"),
            F.max(F.col("hazardous_flag").cast("int")).alias("contains_hazardous"),
            F.max(F.when(F.col("svhc_flag") == True, 1).otherwise(0)).alias("contains_svhc"),  # noqa: E712
        )
    )

    # Aggregate compliance per passport
    compliance_agg = (
        compliance
        .groupBy("passport_id")
        .agg(
            F.count("*").alias("compliance_record_count"),
            F.sum(F.when(F.col("compliance_status") == "compliant", 1).otherwise(0))
                .alias("compliant_count"),
            F.sum(F.when(F.col("compliance_status") == "pending", 1).otherwise(0))
                .alias("pending_count"),
            F.sum(F.when(F.col("compliance_status") == "non_compliant", 1).otherwise(0))
                .alias("non_compliant_count"),
            F.collect_list(
                F.struct("regulation_name", "compliance_status", "expiry_date")
            ).alias("compliance_details"),
        )
    )

    # Join everything together
    result = (
        passport
        .join(manufacturer, "manufacturer_id", "left")
        .join(materials_agg, "passport_id", "left")
        .join(impact, "passport_id", "left")
        .join(compliance_agg, "passport_id", "left")
        .join(circularity, "passport_id", "left")
        .select(
            # Passport core
            passport["passport_id"],
            passport["product_id"],
            passport["gtin"],
            passport["serial_number"],
            passport["batch_lot_number"],
            passport["product_name"],
            passport["product_category"],
            passport["passport_status"],
            passport["production_date"],
            passport["production_facility"],
            passport["country_of_origin"],
            passport["qr_code_url"],
            passport["is_complete"],
            # Manufacturer
            manufacturer["name"].alias("manufacturer_name"),
            manufacturer["country"].alias("manufacturer_country"),
            manufacturer["website"].alias("manufacturer_website"),
            # Materials summary
            F.coalesce(materials_agg["material_count"], F.lit(0)).alias("material_count"),
            materials_agg["materials"],
            materials_agg["renewable_content_pct"],
            F.coalesce(materials_agg["contains_hazardous"], F.lit(0)).cast("boolean")
                .alias("contains_hazardous"),
            F.coalesce(materials_agg["contains_svhc"], F.lit(0)).cast("boolean")
                .alias("contains_svhc"),
            # Environmental impact
            impact["carbon_footprint_kg"],
            impact["carbon_manufacturing"],
            impact["carbon_transport"],
            impact["carbon_use_phase"],
            impact["carbon_end_of_life"],
            impact["energy_consumption_kwh"],
            impact["water_usage_liters"],
            impact["lca_methodology"],
            impact["verified_by"].alias("lca_verified_by"),
            impact["needs_verification"].alias("lca_needs_verification"),
            # Compliance summary
            F.coalesce(compliance_agg["compliance_record_count"], F.lit(0))
                .alias("compliance_record_count"),
            F.coalesce(compliance_agg["compliant_count"], F.lit(0)).alias("compliant_count"),
            F.coalesce(compliance_agg["pending_count"], F.lit(0)).alias("pending_count"),
            F.coalesce(compliance_agg["non_compliant_count"], F.lit(0))
                .alias("non_compliant_count"),
            compliance_agg["compliance_details"],
            # Circularity
            circularity["durability_years"],
            circularity["repairability_score"],
            circularity["spare_parts_available"],
            circularity["spare_parts_years"],
            circularity["refurbishable"],
            circularity["recycled_content_pct"].alias("circularity_recycled_pct"),
            circularity["recyclability_pct"],
            circularity["take_back_program"],
            circularity["second_life_options"],
            # Metadata
            passport["created_at"].alias("passport_created_at"),
            passport["updated_at"].alias("passport_updated_at"),
            F.current_timestamp().alias("_gold_refreshed_at"),
        )
    )

    return result
