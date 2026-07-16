"""
Reyden Toggle (OPTIONAL) -- Adaptive Query Layer for DPP

NOTE: Reyden support is OPTIONAL and DISABLED BY DEFAULT. This module is
NOT USED by the Passport Viewer App, which queries Lakebase directly via
asyncpg. It is provided only as a reference pattern for integrating Reyden
(DBSQL Operational endpoints) when preview access is available. No other
module in this accelerator imports reyden_toggle, and nothing here is
required to run the accelerator.

Provides a unified query interface that routes passport lookups through
either Reyden (DBSQL Operational endpoint) or standard DBSQL/Lakebase,
depending on configuration.

This toggle lets the accelerator work with or without Reyden preview access.

Environment variables:
    REYDEN_ENABLED          "true" to route through Reyden, "false" (default) for DBSQL
    DATABRICKS_HOST         Workspace hostname
    DATABRICKS_TOKEN        PAT or OAuth token
    DATABRICKS_WAREHOUSE_ID SQL Warehouse ID (for standard DBSQL path)
    REYDEN_ENDPOINT_ID      Reyden endpoint ID (when REYDEN_ENABLED=true)
    LAKEBASE_HOST           Lakebase hostname (for direct PG fallback)
    LAKEBASE_PORT           Lakebase port (default: 5432)
    LAKEBASE_DATABASE       Lakebase database (default: databricks_postgres)
    LAKEBASE_USER           Lakebase user (for direct PG fallback)
    LAKEBASE_PASSWORD       Lakebase password (for direct PG fallback)
"""

from __future__ import annotations

import json
import os
from enum import Enum
from typing import Any, Optional


class QueryBackend(Enum):
    """Available query backends."""
    REYDEN = "reyden"
    DBSQL = "dbsql"
    LAKEBASE_DIRECT = "lakebase_direct"


def _get_backend() -> QueryBackend:
    """Determine which backend to use based on environment configuration."""
    if os.environ.get("REYDEN_ENABLED", "false").lower() == "true":
        return QueryBackend.REYDEN
    if os.environ.get("DATABRICKS_WAREHOUSE_ID"):
        return QueryBackend.DBSQL
    if os.environ.get("LAKEBASE_HOST"):
        return QueryBackend.LAKEBASE_DIRECT
    return QueryBackend.DBSQL


def _query_reyden(sql: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Execute a query through the Reyden (DBSQL Operational) endpoint.

    Uses the Databricks SQL Statement Execution API with the Reyden
    endpoint for low-latency operational reads.
    """
    try:
        import requests
    except ImportError:
        raise RuntimeError("requests library is required for Reyden queries")

    host = os.environ["DATABRICKS_HOST"].rstrip("/")
    token = os.environ["DATABRICKS_TOKEN"]
    endpoint_id = os.environ["REYDEN_ENDPOINT_ID"]

    url = f"https://{host}/api/2.0/sql/statements"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "warehouse_id": endpoint_id,
        "statement": sql,
        "wait_timeout": "30s",
        "disposition": "INLINE",
        "format": "JSON_ARRAY",
    }
    if params:
        payload["parameters"] = [
            {"name": k, "value": str(v)} for k, v in params.items()
        ]

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    result = response.json()

    if result.get("status", {}).get("state") != "SUCCEEDED":
        error = result.get("status", {}).get("error", {})
        raise RuntimeError(f"Reyden query failed: {error}")

    # Parse result set
    columns = [col["name"] for col in result.get("manifest", {}).get("schema", {}).get("columns", [])]
    rows = result.get("result", {}).get("data_array", [])
    return [dict(zip(columns, row)) for row in rows]


def _query_dbsql(sql: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Execute a query through standard DBSQL warehouse.

    Uses the Databricks SQL Connector for Python.
    """
    try:
        from databricks import sql as dbsql
    except ImportError:
        raise RuntimeError(
            "databricks-sql-connector is required. "
            "Install with: pip install databricks-sql-connector"
        )

    host = os.environ["DATABRICKS_HOST"]
    token = os.environ["DATABRICKS_TOKEN"]
    warehouse_id = os.environ["DATABRICKS_WAREHOUSE_ID"]

    http_path = f"/sql/1.0/warehouses/{warehouse_id}"

    with dbsql.connect(
        server_hostname=host,
        http_path=http_path,
        access_token=token,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, parameters=params)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]


def _query_lakebase_direct(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """Execute a query directly against Lakebase PostgreSQL (asyncpg).

    Fallback path when neither Reyden nor DBSQL is available. Uses asyncpg
    (Apache-2.0), the same driver as the apps. The SQL must use positional
    $1, $2, ... placeholders and `params` is the matching tuple of values.
    """
    import asyncio

    try:
        import asyncpg
    except ImportError:
        raise RuntimeError(
            "asyncpg is required for direct Lakebase queries. "
            "Install with: pip install asyncpg"
        )

    async def _run() -> list[dict[str, Any]]:
        conn = await asyncpg.connect(
            host=os.environ["LAKEBASE_HOST"],
            port=int(os.environ.get("LAKEBASE_PORT", "5432")),
            database=os.environ.get("LAKEBASE_DATABASE", "databricks_postgres"),
            user=os.environ["LAKEBASE_USER"],
            password=os.environ["LAKEBASE_PASSWORD"],
            ssl=True,
        )
        try:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_query(
    sql: str,
    params: Optional[dict[str, Any]] = None,
    backend: Optional[QueryBackend] = None,
) -> list[dict[str, Any]]:
    """Execute a SQL query using the configured backend.

    Args:
        sql: SQL statement to execute.
        params: Optional query parameters.
        backend: Override automatic backend detection.

    Returns:
        List of row dicts.
    """
    target = backend or _get_backend()

    if target == QueryBackend.LAKEBASE_DIRECT:
        # asyncpg takes positional $1..$n placeholders; the values are bound
        # in the dict's insertion order.
        return _query_lakebase_direct(sql, tuple((params or {}).values()))

    dispatch = {
        QueryBackend.REYDEN: _query_reyden,
        QueryBackend.DBSQL: _query_dbsql,
    }

    handler = dispatch[target]
    return handler(sql, params)


def query_passport(passport_id: str) -> dict[str, Any]:
    """Retrieve a complete product passport by ID.

    This is the primary query function used by the passport viewer app
    and API endpoints. It returns a fully denormalized passport record.

    Args:
        passport_id: UUID of the passport to retrieve.

    Returns:
        Dict with passport data, or empty dict if not found.
    """
    backend = _get_backend()

    if backend == QueryBackend.LAKEBASE_DIRECT:
        # Query Lakebase directly with joins
        sql = """
            SELECT
                pp.passport_id, pp.product_id, pp.gtin, pp.serial_number,
                pp.batch_lot_number, pp.product_name, pp.product_category,
                pp.passport_status, pp.production_date, pp.production_facility,
                pp.country_of_origin, pp.qr_code_url,
                m.name AS manufacturer_name, m.country AS manufacturer_country,
                m.website AS manufacturer_website,
                ei.carbon_footprint_kg, ei.energy_consumption_kwh,
                ei.water_usage_liters, ei.lca_methodology,
                ci.durability_years, ci.repairability_score,
                ci.recyclability_pct, ci.take_back_program
            FROM dpp.product_passport pp
            LEFT JOIN dpp.manufacturer m ON pp.manufacturer_id = m.manufacturer_id
            LEFT JOIN dpp.environmental_impact ei ON pp.passport_id = ei.passport_id
            LEFT JOIN dpp.circularity_info ci ON pp.passport_id = ci.passport_id
            WHERE pp.passport_id = $1
        """
        rows = _query_lakebase_direct(sql, (passport_id,))
    else:
        # Query the Gold layer via DBSQL/Reyden
        sql = """
            SELECT *
            FROM gold_passport_complete
            WHERE passport_id = :passport_id
        """
        rows = execute_query(sql, {"passport_id": passport_id}, backend=backend)

    if not rows:
        return {}

    result = rows[0]

    # Enrich with materials and compliance if using Lakebase direct
    if backend == QueryBackend.LAKEBASE_DIRECT:
        materials = _query_lakebase_direct(
            "SELECT * FROM dpp.product_materials WHERE passport_id = $1",
            (passport_id,),
        )
        compliance = _query_lakebase_direct(
            "SELECT * FROM dpp.compliance_records WHERE passport_id = $1",
            (passport_id,),
        )
        disposal = _query_lakebase_direct(
            "SELECT * FROM dpp.disposal_guidelines WHERE passport_id = $1",
            (passport_id,),
        )
        result["materials"] = materials
        result["compliance_records"] = compliance
        result["disposal_guidelines"] = disposal

    return result


def get_backend_info() -> dict[str, str]:
    """Return information about the currently configured backend.

    Useful for diagnostics and the admin UI.
    """
    backend = _get_backend()
    info = {"backend": backend.value}

    if backend == QueryBackend.REYDEN:
        info["endpoint_id"] = os.environ.get("REYDEN_ENDPOINT_ID", "not set")
        info["host"] = os.environ.get("DATABRICKS_HOST", "not set")
    elif backend == QueryBackend.DBSQL:
        info["warehouse_id"] = os.environ.get("DATABRICKS_WAREHOUSE_ID", "not set")
        info["host"] = os.environ.get("DATABRICKS_HOST", "not set")
    elif backend == QueryBackend.LAKEBASE_DIRECT:
        info["lakebase_host"] = os.environ.get("LAKEBASE_HOST", "not set")
        info["lakebase_database"] = os.environ.get(
            "LAKEBASE_DATABASE", "databricks_postgres"
        )

    return info
