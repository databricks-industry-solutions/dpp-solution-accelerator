"""
Gold Layer -- Material Composition Trends + Circularity Metrics

Two category-level aggregates promised in the PLAN:
  - gold_material_composition_trends: material makeup per product category
    (recycled / renewable / hazardous shares, REACH/SVHC counts).
  - gold_circularity_metrics: circularity KPIs per product category plus a
    composite circularity index.

Both power the sustainability dashboard and the Genie space.
"""

import dlt
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


@dlt.table(
    name="gold_material_composition_trends",
    comment=(
        "Material composition per product category x material category: "
        "weight share, recycled content, renewable/hazardous shares, and "
        "REACH/SVHC counts. Weighted by percentage_by_weight."
    ),
)
def gold_material_composition_trends() -> DataFrame:
    """Aggregate material composition by product + material category."""
    passport = dlt.read("silver_product_passport").select(
        "passport_id", "product_category"
    )
    materials = dlt.read("silver_product_materials")

    joined = materials.join(passport, "passport_id", "inner")

    return (
        joined
        .groupBy("product_category", "material_category")
        .agg(
            F.countDistinct("passport_id").alias("product_count"),
            F.count("*").alias("material_line_count"),
            F.round(F.avg("percentage_by_weight"), 2).alias("avg_pct_by_weight"),
            # Weighted recycled content across this material category.
            F.round(F.avg("recycled_content_pct"), 2).alias("avg_recycled_content_pct"),
            # Weight-weighted renewable share (% of weight flagged renewable).
            F.round(
                100.0
                * F.sum(F.when(F.col("renewable_flag"), F.col("percentage_by_weight")).otherwise(0))
                / F.sum("percentage_by_weight"),
                1,
            ).alias("renewable_weight_share_pct"),
            F.sum(F.col("hazardous_flag").cast("int")).alias("hazardous_material_count"),
            F.sum(F.col("svhc_flag").cast("int")).alias("svhc_material_count"),
            F.sum((~F.col("reach_compliant")).cast("int")).alias("reach_noncompliant_count"),
            F.current_timestamp().alias("_gold_refreshed_at"),
        )
    )


@dlt.table(
    name="gold_circularity_metrics",
    comment=(
        "Circularity KPIs per product category: repairability, durability, "
        "recyclability, recycled content, and take-back / refurbish / spare-part "
        "availability rates, plus a 0-100 composite circularity index."
    ),
)
def gold_circularity_metrics() -> DataFrame:
    """Aggregate circularity KPIs by product category."""
    passport = dlt.read("silver_product_passport").select(
        "passport_id", "product_category"
    )
    circ = dlt.read("silver_circularity_info")

    joined = circ.join(passport, "passport_id", "inner")

    agg = (
        joined
        .groupBy("product_category")
        .agg(
            F.count("*").alias("product_count"),
            F.round(F.avg("repairability_score"), 2).alias("avg_repairability_score"),
            F.round(F.avg("durability_years"), 1).alias("avg_durability_years"),
            F.round(F.avg("recyclability_pct"), 1).alias("avg_recyclability_pct"),
            F.round(F.avg("recycled_content_pct"), 1).alias("avg_recycled_content_pct"),
            F.round(100.0 * F.avg(F.col("refurbishable").cast("int")), 1)
                .alias("refurbishable_rate_pct"),
            F.round(100.0 * F.avg(F.col("take_back_program").cast("int")), 1)
                .alias("take_back_rate_pct"),
            F.round(100.0 * F.avg(F.col("spare_parts_available").cast("int")), 1)
                .alias("spare_parts_rate_pct"),
        )
    )

    # Composite 0-100 circularity index: equal-weight blend of repairability
    # (/10), recyclability (%), recycled content (%), and the take-back rate.
    return agg.select(
        "*",
        F.round(
            (
                F.coalesce(F.col("avg_repairability_score"), F.lit(0)) * 10.0
                + F.coalesce(F.col("avg_recyclability_pct"), F.lit(0))
                + F.coalesce(F.col("avg_recycled_content_pct"), F.lit(0))
                + F.coalesce(F.col("take_back_rate_pct"), F.lit(0))
            )
            / 4.0,
            1,
        ).alias("circularity_index"),
        F.current_timestamp().alias("_gold_refreshed_at"),
    )
