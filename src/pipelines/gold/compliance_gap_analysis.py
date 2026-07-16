"""
Gold Layer -- Compliance Gap Analysis

Identifies products at risk of non-compliance, with expiring certifications,
incomplete passports, or missing regulatory records. This view powers the
compliance dashboard and alerting.
"""

import dlt
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


@dlt.table(
    name="gold_compliance_gap_analysis",
    comment=(
        "Products at risk: non-compliant regulations, expiring certificates, "
        "incomplete passport data, and missing compliance records."
    ),
)
def gold_compliance_gap_analysis() -> DataFrame:
    """Build the compliance gap analysis view."""
    passport = dlt.read("silver_product_passport")
    compliance = dlt.read("silver_compliance_records")
    origin = dlt.read("silver_product_origin")
    impact = dlt.read("silver_environmental_impact")

    # Compliance issues per passport
    compliance_issues = (
        compliance
        .groupBy("passport_id")
        .agg(
            F.count("*").alias("total_compliance_records"),
            F.sum(F.when(F.col("compliance_status") == "non_compliant", 1).otherwise(0))
                .alias("non_compliant_count"),
            F.sum(F.when(F.col("compliance_status") == "pending", 1).otherwise(0))
                .alias("pending_count"),
            F.sum(F.col("is_expired").cast("int")).alias("expired_certificate_count"),
            F.collect_list(
                F.when(
                    F.col("compliance_status") == "non_compliant",
                    F.col("regulation_name"),
                )
            ).alias("non_compliant_regulations"),
            F.collect_list(
                F.when(
                    F.col("compliance_status") == "pending",
                    F.col("regulation_name"),
                )
            ).alias("pending_regulations"),
        )
    )

    # Certification expiry issues from origin
    cert_issues = (
        origin
        .groupBy("passport_id")
        .agg(
            F.sum(F.col("certification_expiring_soon").cast("int"))
                .alias("expiring_supplier_certs"),
        )
    )

    # LCA verification gaps
    lca_gaps = (
        impact
        .select(
            "passport_id",
            "needs_verification",
        )
    )

    # Build the gap analysis
    result = (
        passport
        .join(compliance_issues, "passport_id", "left")
        .join(cert_issues, "passport_id", "left")
        .join(lca_gaps, "passport_id", "left")
        .select(
            passport["passport_id"],
            passport["product_id"],
            passport["product_name"],
            passport["product_category"],
            passport["passport_status"],
            passport["is_complete"],
            # Compliance gaps
            F.coalesce(compliance_issues["total_compliance_records"], F.lit(0))
                .alias("total_compliance_records"),
            F.coalesce(compliance_issues["non_compliant_count"], F.lit(0))
                .alias("non_compliant_count"),
            F.coalesce(compliance_issues["pending_count"], F.lit(0))
                .alias("pending_count"),
            F.coalesce(compliance_issues["expired_certificate_count"], F.lit(0))
                .alias("expired_certificate_count"),
            compliance_issues["non_compliant_regulations"],
            compliance_issues["pending_regulations"],
            # Supply chain cert gaps
            F.coalesce(cert_issues["expiring_supplier_certs"], F.lit(0))
                .alias("expiring_supplier_certifications"),
            # LCA gaps
            F.coalesce(lca_gaps["needs_verification"], F.lit(False))
                .alias("lca_needs_verification"),
            # Overall risk score (0-100, higher = more risk)
            (
                F.coalesce(compliance_issues["non_compliant_count"], F.lit(0)) * 30
                + F.coalesce(compliance_issues["pending_count"], F.lit(0)) * 15
                + F.coalesce(compliance_issues["expired_certificate_count"], F.lit(0)) * 20
                + F.coalesce(cert_issues["expiring_supplier_certs"], F.lit(0)) * 10
                + F.when(passport["is_complete"] == False, F.lit(15)).otherwise(F.lit(0))  # noqa: E712
                + F.when(
                    F.coalesce(lca_gaps["needs_verification"], F.lit(False)) == True,  # noqa: E712
                    F.lit(10),
                ).otherwise(F.lit(0))
            ).alias("risk_score"),
            # Risk category
            F.when(
                (F.coalesce(compliance_issues["non_compliant_count"], F.lit(0)) > 0),
                F.lit("CRITICAL"),
            ).when(
                (F.coalesce(compliance_issues["pending_count"], F.lit(0)) > 0)
                | (F.coalesce(compliance_issues["expired_certificate_count"], F.lit(0)) > 0),
                F.lit("HIGH"),
            ).when(
                (passport["is_complete"] == False)  # noqa: E712
                | (F.coalesce(cert_issues["expiring_supplier_certs"], F.lit(0)) > 0),
                F.lit("MEDIUM"),
            ).otherwise(F.lit("LOW")).alias("risk_category"),
            # Metadata
            F.current_timestamp().alias("_gold_refreshed_at"),
        )
    )

    return result
