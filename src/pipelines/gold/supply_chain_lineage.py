"""
Gold Layer -- Supply Chain Lineage

Creates a multi-tier supplier graph view showing the full supply chain
for each product passport. Useful for traceability audits, risk analysis,
and regulatory reporting.
"""

import dlt
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


@dlt.table(
    name="gold_supply_chain_lineage",
    comment=(
        "Multi-tier supply chain lineage per product. Joins passport, origin, "
        "and supplier data to produce a complete traceability graph with "
        "certification status and risk scoring."
    ),
)
def gold_supply_chain_lineage() -> DataFrame:
    """Build the supply chain lineage view."""
    passport = dlt.read("silver_product_passport")
    origin = dlt.read("silver_product_origin")
    supplier = dlt.read("silver_supplier")

    lineage = (
        origin
        .join(passport, "passport_id", "inner")
        .join(supplier, "supplier_id", "inner")
        .select(
            # Product identification
            origin["passport_id"],
            passport["product_id"],
            passport["product_name"],
            passport["product_category"],
            # Supply chain node
            origin["origin_id"],
            origin["supply_chain_tier"],
            origin["component_name"],
            origin["source_country"],
            origin["source_region"],
            # Supplier details
            origin["supplier_id"],
            supplier["name"].alias("supplier_name"),
            supplier["country"].alias("supplier_country"),
            supplier["tier"].alias("supplier_tier"),
            supplier["risk_score"].alias("supplier_risk_score"),
            supplier["active"].alias("supplier_active"),
            supplier["certifications"].alias("supplier_certifications"),
            supplier["last_audit_date"].alias("supplier_last_audit"),
            # Certification status
            origin["certification"],
            origin["certification_expiry"],
            origin["certification_expiring_soon"],
            origin["traceability_proof"],
            # Risk flags
            F.when(supplier["risk_score"] >= 7.0, F.lit("HIGH"))
             .when(supplier["risk_score"] >= 4.0, F.lit("MEDIUM"))
             .otherwise(F.lit("LOW"))
             .alias("risk_level"),
            F.when(supplier["active"] == False, F.lit(True))  # noqa: E712
             .otherwise(F.lit(False))
             .alias("inactive_supplier_flag"),
            # Metadata
            F.current_timestamp().alias("_gold_refreshed_at"),
        )
    )

    return lineage


@dlt.table(
    name="gold_supply_chain_summary",
    comment=(
        "Per-product supply chain summary: number of suppliers per tier, "
        "average risk score, certification gaps."
    ),
)
def gold_supply_chain_summary() -> DataFrame:
    """Aggregate supply chain metrics per product."""
    lineage = dlt.read("gold_supply_chain_lineage")

    summary = (
        lineage
        .groupBy("passport_id", "product_id", "product_name", "product_category")
        .agg(
            F.countDistinct("supplier_id").alias("total_suppliers"),
            F.countDistinct(
                F.when(F.col("supply_chain_tier") == 1, F.col("supplier_id"))
            ).alias("tier_1_suppliers"),
            F.countDistinct(
                F.when(F.col("supply_chain_tier") == 2, F.col("supplier_id"))
            ).alias("tier_2_suppliers"),
            F.countDistinct(
                F.when(F.col("supply_chain_tier") == 3, F.col("supplier_id"))
            ).alias("tier_3_suppliers"),
            F.avg("supplier_risk_score").alias("avg_supplier_risk_score"),
            F.max("supplier_risk_score").alias("max_supplier_risk_score"),
            F.sum(F.col("certification_expiring_soon").cast("int"))
                .alias("expiring_certifications"),
            F.sum(F.col("inactive_supplier_flag").cast("int"))
                .alias("inactive_suppliers"),
            F.countDistinct("source_country").alias("unique_source_countries"),
            F.current_timestamp().alias("_gold_refreshed_at"),
        )
    )

    return summary


@dlt.table(
    name="gold_supplier_traceability",
    comment=(
        "Flattened multi-tier supplier ancestry. For every supplier, emits one "
        "row per node on the path from itself up to its tier-1 (direct) "
        "supplier, following parent_supplier_id. depth=0 is the supplier "
        "itself, depth increases toward the manufacturer. Enables tier-1 -> "
        "tier-N traceability queries (e.g. 'which sub-suppliers feed direct "
        "supplier X')."
    ),
)
def gold_supplier_traceability() -> DataFrame:
    """Walk the supplier parent chain iteratively.

    The supply chain is at most 3 tiers deep, so two parent hops from any
    supplier reach the tier-1 root. An iterative join (rather than a recursive
    CTE) keeps this portable across runtimes and trivially bounded.
    """
    supplier = dlt.read("silver_supplier").select(
        F.col("supplier_id"),
        F.col("name"),
        F.col("tier"),
        F.col("country"),
        F.col("risk_score"),
        F.col("parent_supplier_id"),
    )

    # depth 0: every supplier is the start of its own walk.
    level0 = supplier.select(
        F.col("supplier_id"),
        F.col("name").alias("supplier_name"),
        F.col("tier").alias("supplier_tier"),
        F.col("supplier_id").alias("ancestor_id"),
        F.col("name").alias("ancestor_name"),
        F.col("tier").alias("ancestor_tier"),
        F.col("country").alias("ancestor_country"),
        F.col("risk_score").alias("ancestor_risk_score"),
        F.col("parent_supplier_id").alias("_next_parent"),
        F.lit(0).alias("depth"),
    )

    levels = [level0]
    frontier = level0

    # Max tier depth is 3 -> 2 parent hops cover the deepest chain.
    for _ in range(2):
        parents = supplier.select(
            F.col("supplier_id").alias("p_id"),
            F.col("name").alias("p_name"),
            F.col("tier").alias("p_tier"),
            F.col("country").alias("p_country"),
            F.col("risk_score").alias("p_risk"),
            F.col("parent_supplier_id").alias("p_parent"),
        )
        frontier = (
            frontier
            .join(parents, frontier["_next_parent"] == parents["p_id"], "inner")
            .select(
                frontier["supplier_id"],
                frontier["supplier_name"],
                frontier["supplier_tier"],
                parents["p_id"].alias("ancestor_id"),
                parents["p_name"].alias("ancestor_name"),
                parents["p_tier"].alias("ancestor_tier"),
                parents["p_country"].alias("ancestor_country"),
                parents["p_risk"].alias("ancestor_risk_score"),
                parents["p_parent"].alias("_next_parent"),
                (frontier["depth"] + 1).alias("depth"),
            )
        )
        levels.append(frontier)

    traceability = levels[0]
    for lvl in levels[1:]:
        traceability = traceability.unionByName(lvl)

    return traceability.select(
        "supplier_id",
        "supplier_name",
        "supplier_tier",
        "ancestor_id",
        "ancestor_name",
        "ancestor_tier",
        "ancestor_country",
        "ancestor_risk_score",
        "depth",
        F.when(F.col("ancestor_tier") == 1, F.lit(True))
         .otherwise(F.lit(False))
         .alias("ancestor_is_direct_supplier"),
        F.current_timestamp().alias("_gold_refreshed_at"),
    )
