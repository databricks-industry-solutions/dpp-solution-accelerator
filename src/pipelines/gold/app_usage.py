"""
Gold Layer -- App Usage

Cleaned app access events for internal usage tracking. Populated only when the
apps run with ACCESS_LOG_ENABLED=true (otherwise the source table is empty).
Powers the "App usage" page on the compliance dashboard: who opened the apps,
how often, and which pages. User emails are personal data -- treat accordingly.
"""

import dlt
from pyspark.sql import DataFrame
from pyspark.sql import functions as F


@dlt.table(
    name="gold_app_usage",
    comment="Cleaned app access events (user, app, path, timestamp) for usage tracking.",
)
def gold_app_usage() -> DataFrame:
    return (
        dlt.read("bronze_app_access_log")
        .withColumn("access_date", F.to_date("accessed_at"))
        .select(
            "access_id", "user_email", "user_name", "app_name",
            "path", "method", "client_ip", "accessed_at", "access_date",
        )
    )
