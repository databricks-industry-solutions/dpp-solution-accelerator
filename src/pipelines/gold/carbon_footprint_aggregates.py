"""
Gold Layer -- Carbon Footprint Aggregates

Aggregated environmental metrics by product category, lifecycle phase,
and time period. Powers the sustainability dashboard and ESG reporting.
"""

import dlt
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


@dlt.table(
    name="gold_carbon_by_category",
    comment=(
        "Carbon footprint aggregates per product category, including "
        "lifecycle phase breakdown and energy/water metrics."
    ),
)
def gold_carbon_by_category() -> DataFrame:
    """Aggregate carbon metrics by product category."""
    passport = dlt.read("silver_product_passport")
    impact = dlt.read("silver_environmental_impact")

    result = (
        impact
        .join(passport, "passport_id", "inner")
        .groupBy("product_category")
        .agg(
            F.count("*").alias("product_count"),
            # Carbon totals
            F.sum("carbon_footprint_kg").alias("total_carbon_kg"),
            F.avg("carbon_footprint_kg").alias("avg_carbon_kg"),
            F.min("carbon_footprint_kg").alias("min_carbon_kg"),
            F.max("carbon_footprint_kg").alias("max_carbon_kg"),
            F.stddev("carbon_footprint_kg").alias("stddev_carbon_kg"),
            # Lifecycle phase breakdown
            F.sum("carbon_manufacturing").alias("total_carbon_manufacturing"),
            F.sum("carbon_transport").alias("total_carbon_transport"),
            F.sum("carbon_use_phase").alias("total_carbon_use_phase"),
            F.sum("carbon_end_of_life").alias("total_carbon_end_of_life"),
            # Energy and water
            F.sum("energy_consumption_kwh").alias("total_energy_kwh"),
            F.avg("energy_consumption_kwh").alias("avg_energy_kwh"),
            F.sum("water_usage_liters").alias("total_water_liters"),
            F.avg("water_usage_liters").alias("avg_water_liters"),
            # Verification status
            F.sum(F.col("needs_verification").cast("int")).alias("unverified_count"),
            F.current_timestamp().alias("_gold_refreshed_at"),
        )
    )

    return result


@dlt.table(
    name="gold_carbon_by_product",
    comment=(
        "Per-product carbon footprint with lifecycle breakdown "
        "and category percentile ranking."
    ),
)
def gold_carbon_by_product() -> DataFrame:
    """Per-product carbon with category context."""
    passport = dlt.read("silver_product_passport")
    impact = dlt.read("silver_environmental_impact")
    materials = dlt.read("silver_product_materials")

    # Renewable content per passport
    renewable_agg = (
        materials
        .groupBy("passport_id")
        .agg(
            F.sum(
                F.when(F.col("renewable_flag") == True, F.col("percentage_by_weight"))  # noqa: E712
                .otherwise(0)
            ).alias("renewable_content_pct"),
            F.sum(
                F.when(F.col("recycled_content_pct") > 0, F.col("percentage_by_weight"))
                .otherwise(0)
            ).alias("recycled_material_pct"),
        )
    )

    result = (
        impact
        .join(passport, "passport_id", "inner")
        .join(renewable_agg, "passport_id", "left")
        .select(
            passport["passport_id"],
            passport["product_id"],
            passport["product_name"],
            passport["product_category"],
            passport["production_date"],
            # Carbon breakdown
            impact["carbon_footprint_kg"],
            impact["carbon_manufacturing"],
            impact["carbon_transport"],
            impact["carbon_use_phase"],
            impact["carbon_end_of_life"],
            # Manufacturing share
            F.when(
                impact["carbon_footprint_kg"] > 0,
                F.round(
                    impact["carbon_manufacturing"] / impact["carbon_footprint_kg"] * 100,
                    1,
                ),
            ).alias("manufacturing_pct"),
            # Energy and water
            impact["energy_consumption_kwh"],
            impact["water_usage_liters"],
            # Material sustainability
            F.coalesce(renewable_agg["renewable_content_pct"], F.lit(0.0))
                .alias("renewable_content_pct"),
            F.coalesce(renewable_agg["recycled_material_pct"], F.lit(0.0))
                .alias("recycled_material_pct"),
            # LCA info
            impact["lca_methodology"],
            impact["verified_by"],
            impact["needs_verification"],
            # Metadata
            F.current_timestamp().alias("_gold_refreshed_at"),
        )
    )

    return result
