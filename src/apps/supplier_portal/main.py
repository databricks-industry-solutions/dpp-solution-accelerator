"""
DPP Supplier Portal — Databricks App

Internal supplier-facing portal for managing certifications, material
declarations, and compliance status. Key differentiator from the read-only
Passport Viewer: this app performs transactional writes (INSERT/UPDATE)
against Lakebase, demonstrating OLTP capability.

Demo scenario — "The Regulator is Coming":
  1. Compliance officer sees expired cert in dashboard
  2. Goes to Supplier Portal
  3. Supplier renews certification (UPDATE)
  4. Audit log captures the change automatically (trigger)
  5. Pipeline refreshes → compliance dashboard updates
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import requests
from databricks.sdk import WorkspaceClient
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger("supplier_portal")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Lakebase connection
# ---------------------------------------------------------------------------
# Two auth modes, resolved at first connection (never at import, so a missing
# var can't crash app startup):
#
#   1. PREFERRED — Lakebase declared as an app resource. Databricks injects
#      PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD bound to the app's service
#      principal role (OAuth-managed password, correct DNS). No secret, no
#      manual PG user. This is the path a clean `bundle deploy` should hit.
#   2. FALLBACK — PG native login: resolve DNS from LAKEBASE_INSTANCE and log
#      in as LAKEBASE_USER with LAKEBASE_PASSWORD (a secret). Used for local
#      dev or when the resource binding is unavailable.
SCHEMA = os.environ.get("DPP_SCHEMA", "dpp")
DATABASE_NAME = os.environ.get("LAKEBASE_DATABASE_NAME", "databricks_postgres")
LAKEBASE_USER = os.environ.get("LAKEBASE_USER", "dpp_app_user")


def _resolve_lakebase_dns() -> str:
    """Resolve Lakebase DNS (fallback / native-login path).

    Prefers an explicit LAKEBASE_DNS env var, otherwise looks up
    LAKEBASE_INSTANCE via the workspace API. Matches the bronze pipeline.
    """
    explicit = os.environ.get("LAKEBASE_DNS")
    if explicit:
        return explicit
    instance = os.environ.get("LAKEBASE_INSTANCE")
    if not instance:
        raise RuntimeError(
            "Set LAKEBASE_DNS or LAKEBASE_INSTANCE in the app environment, "
            "or bind the Lakebase database as an app resource (PGHOST)."
        )
    w = WorkspaceClient()
    headers = w.config.authenticate()
    host = w.config.host.rstrip("/")
    resp = requests.get(
        f"{host}/api/2.0/database/instances/{instance}",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["read_write_dns"]


def _reference_date() -> date:
    """Reference date for cert-expiry urgency.

    Defaults to today() so the demo doesn't drift; override via
    DPP_REFERENCE_DATE=YYYY-MM-DD for reproducible screenshots.
    """
    override = os.environ.get("DPP_REFERENCE_DATE")
    if override:
        try:
            return date.fromisoformat(override)
        except ValueError:
            logger.warning("Invalid DPP_REFERENCE_DATE=%r, falling back to today()", override)
    return date.today()

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()

# Queries in this file use psycopg-style %s placeholders; asyncpg uses $1, $2…
_PLACEHOLDER_RE = re.compile(r"%s")


def _to_pg(query: str) -> str:
    """Convert %s placeholders to asyncpg's positional $1, $2, … form."""
    counter = {"n": 0}

    def repl(_match: re.Match) -> str:
        counter["n"] += 1
        return f"${counter['n']}"

    return _PLACEHOLDER_RE.sub(repl, query)


def _lakebase_oauth_token() -> str:
    """Mint a short-lived Lakebase credential using the app's service principal.

    Databricks Apps with a bound Lakebase resource inject PGHOST/PGUSER/
    PGDATABASE but NOT a password — the app authenticates with an OAuth token
    minted from its own SP identity (auto-injected DATABRICKS_CLIENT_ID/SECRET).
    """
    instance = os.environ.get("LAKEBASE_INSTANCE")
    if not instance:
        raise RuntimeError("LAKEBASE_INSTANCE is required to mint a Lakebase token.")
    w = WorkspaceClient()
    host = w.config.host.rstrip("/")
    resp = requests.post(
        f"{host}/api/2.0/database/credentials",
        headers=w.config.authenticate(),
        json={"request_id": str(uuid4()), "instance_names": [instance]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["token"]


async def _oauth_password() -> str:
    """Mint a fresh Lakebase OAuth token off the event loop (per new connection).

    Passed to asyncpg as the password provider so a long-lived pool never holds
    a stale token: asyncpg calls it whenever it opens a connection.
    """
    return await asyncio.to_thread(_lakebase_oauth_token)


def _conn_kwargs() -> dict:
    """asyncpg connection kwargs.

    Mode 1 (preferred): Lakebase bound as an app resource — PGHOST/PGUSER/
    PGDATABASE injected, password minted per connection via _oauth_password.
    Mode 2 (fallback): PG native login with a secret password.
    """
    if os.environ.get("PGHOST"):
        return {
            "host": os.environ["PGHOST"],
            "port": int(os.environ.get("PGPORT", "5432")),
            "database": os.environ.get("PGDATABASE", DATABASE_NAME),
            "user": os.environ["PGUSER"],
            "password": _oauth_password,  # callable -> fresh token per connection
            "ssl": True,
        }
    password = os.environ.get("LAKEBASE_PASSWORD")
    if not password:
        raise RuntimeError(
            "No Lakebase credentials found. Either bind the Lakebase database "
            "as an app resource (injects PGHOST/PGUSER) or set LAKEBASE_PASSWORD "
            "(PG native login)."
        )
    return {
        "host": _resolve_lakebase_dns(),
        "port": 5432,
        "database": DATABASE_NAME,
        "user": LAKEBASE_USER,
        "password": password,
        "ssl": True,
    }


async def _init_conn(conn: asyncpg.Connection) -> None:
    """Decode/encode uuid + json/jsonb as text so plain str values pass through."""
    for type_name in ("uuid", "json", "jsonb"):
        await conn.set_type_codec(
            type_name, schema="pg_catalog",
            encoder=lambda v: v, decoder=lambda v: v, format="text",
        )


async def _get_pool() -> asyncpg.Pool:
    """Lazily initialize the async connection pool on first use."""
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is not None:
            return _pool
        _pool = await asyncpg.create_pool(
            min_size=1,
            max_size=10,
            max_inactive_connection_lifetime=1800,  # recycle before ~1h token TTL
            init=_init_conn,
            **_conn_kwargs(),
        )
        return _pool


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(title="DPP Supplier Portal")
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# App access logging (opt-in)
# ---------------------------------------------------------------------------
# When ACCESS_LOG_ENABLED=true, record who opens the app to dpp.app_access_log.
# A deployed Databricks App runs behind SSO and injects the end user in the
# X-Forwarded-* headers, so each request carries the authenticated identity.
# Off by default: user emails are personal data (GDPR); the operator opts in.
# Best-effort and non-blocking, so it never slows a response or breaks a page.
ACCESS_LOG_ENABLED = os.environ.get("ACCESS_LOG_ENABLED", "false").lower() == "true"
_ACCESS_LOG_APP = "supplier_portal"
_ACCESS_LOG_SKIP = ("/health", "/api/qr", "/static", "/favicon")
_access_bg_tasks: set = set()


async def _write_access_log(email, user, ip, ua, path, method) -> None:
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO {SCHEMA}.app_access_log "
                "(user_email, user_name, app_name, path, method, client_ip, user_agent) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                email, user, _ACCESS_LOG_APP, path, method, ip, ua,
            )
    except Exception as exc:  # noqa: BLE001 -- logging is best-effort
        logger.info("access-log write skipped: %s", exc)


@app.middleware("http")
async def _access_log_middleware(request: Request, call_next):
    response = await call_next(request)
    if ACCESS_LOG_ENABLED and not request.url.path.startswith(_ACCESS_LOG_SKIP):
        h = request.headers
        task = asyncio.create_task(_write_access_log(
            h.get("x-forwarded-email"),
            h.get("x-forwarded-preferred-username") or h.get("x-forwarded-user"),
            h.get("x-real-ip") or (request.client.host if request.client else None),
            h.get("user-agent"),
            request.url.path,
            request.method,
        ))
        _access_bg_tasks.add(task)
        task.add_done_callback(_access_bg_tasks.discard)
    return response


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
async def _fetch_one(query: str, params: tuple = ()) -> dict | None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(_to_pg(query), *params)
        return dict(row) if row is not None else None


async def _fetch_all(query: str, params: tuple = ()) -> list[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_to_pg(query), *params)
        return [dict(r) for r in rows]


_brand_name: str | None = None


async def _manufacturer_name() -> str:
    """Manufacturer display name for page branding (depends on the seeded
    profile: furniture or battery), read once from the DB and cached."""
    global _brand_name
    if _brand_name is None:
        row = await _fetch_one(f"SELECT name FROM {SCHEMA}.manufacturer LIMIT 1")
        _brand_name = (row or {}).get("name") or "Demo Manufacturer"
    return _brand_name


async def _execute_write(statements: list[tuple[str, tuple]]) -> None:
    """Execute one or more write statements in a single transaction —
    either all statements succeed or none do."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for query, params in statements:
                await conn.execute(_to_pg(query), *params)


def _json_default(obj: Any) -> Any:
    """JSON serializer for types not handled by default."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, UUID):
        return str(obj)
    return str(obj)


def _format_jsonb(val: Any) -> str:
    """Pretty-format a JSONB value for display in audit log."""
    if val is None:
        return "-"
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    return json.dumps(val, indent=2, default=_json_default)


# Register template filters
templates.env.filters["format_jsonb"] = _format_jsonb


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def suppliers_list(request: Request):
    """Supplier selection page — list all suppliers with product counts."""
    try:
        suppliers = await _fetch_all(
            f"""
            SELECT s.supplier_id, s.name, s.country, s.tier, s.risk_score,
                   s.certifications, s.last_audit_date, s.active,
                   s.created_at, s.updated_at,
                   COUNT(DISTINCT po.origin_id) AS product_count
            FROM {SCHEMA}.supplier s
            LEFT JOIN {SCHEMA}.product_origin po ON s.supplier_id = po.supplier_id
            GROUP BY s.supplier_id, s.name, s.country, s.tier, s.risk_score,
                     s.certifications, s.last_audit_date, s.active,
                     s.created_at, s.updated_at
            ORDER BY s.name
            """,
        )

        return templates.TemplateResponse(
            "suppliers.html",
            {
                "request": request,
                "suppliers": suppliers,
                "reference_date": _reference_date(),
                "brand": await _manufacturer_name(),
            },
        )
    except Exception:
        logger.exception("Error rendering supplier list")
        return HTMLResponse(
            content="<p>An internal error occurred loading the supplier list.</p>",
            status_code=500,
        )


@app.get("/supplier/{supplier_id}", response_class=HTMLResponse)
async def supplier_dashboard(request: Request, supplier_id: str, renewed: int = 0):
    """Supplier dashboard — details, product origins, recent audit entries."""
    supplier = await _fetch_one(
        f"SELECT * FROM {SCHEMA}.supplier WHERE supplier_id = %s",
        (supplier_id,),
    )
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    # Fetch product origins and recent audit entries in parallel
    origins_coro = _fetch_all(
        f"""
        SELECT po.*, pp.product_name
        FROM {SCHEMA}.product_origin po
        JOIN {SCHEMA}.product_passport pp ON po.passport_id = pp.passport_id
        WHERE po.supplier_id = %s
        ORDER BY po.certification_expiry ASC NULLS LAST
        """,
        (supplier_id,),
    )

    audit_coro = _fetch_all(
        f"""
        SELECT pal.*
        FROM {SCHEMA}.passport_audit_log pal
        WHERE pal.passport_id IN (
            SELECT DISTINCT po.passport_id
            FROM {SCHEMA}.product_origin po
            WHERE po.supplier_id = %s
        )
        ORDER BY pal.changed_at DESC
        LIMIT 10
        """,
        (supplier_id,),
    )

    origins, audit_entries = await asyncio.gather(origins_coro, audit_coro)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "supplier": supplier,
            "origins": origins,
            "audit_entries": audit_entries,
            "reference_date": _reference_date(),
            "renewed": renewed,
            "brand": await _manufacturer_name(),
        },
    )


@app.get("/supplier/{supplier_id}/renew/{origin_id}", response_class=HTMLResponse)
async def renew_form(request: Request, supplier_id: str, origin_id: str):
    """Certification renewal form — pre-filled with current values."""
    supplier = await _fetch_one(
        f"SELECT * FROM {SCHEMA}.supplier WHERE supplier_id = %s",
        (supplier_id,),
    )
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    origin = await _fetch_one(
        f"""
        SELECT po.*, pp.product_name
        FROM {SCHEMA}.product_origin po
        JOIN {SCHEMA}.product_passport pp ON po.passport_id = pp.passport_id
        WHERE po.origin_id = %s AND po.supplier_id = %s
        """,
        (origin_id, supplier_id),
    )
    if not origin:
        raise HTTPException(status_code=404, detail="Product origin not found")

    return templates.TemplateResponse(
        "renew.html",
        {
            "request": request,
            "supplier": supplier,
            "origin": origin,
            "reference_date": _reference_date(),
            "brand": await _manufacturer_name(),
        },
    )


@app.post("/supplier/{supplier_id}/renew/{origin_id}")
async def renew_certification(
    request: Request,
    supplier_id: str,
    origin_id: str,
    new_certification: str = Form(...),
    new_expiry_date: str = Form(...),
    new_certificate_ref: str = Form(""),
):
    """Process certification renewal — UPDATE product_origin and supplier.

    This is the key write operation that demonstrates Lakebase handling
    transactional writes. The audit trigger on dpp.product_origin will
    automatically capture the change in dpp.passport_audit_log.
    """
    # Validate that the origin belongs to this supplier
    origin = await _fetch_one(
        f"SELECT origin_id FROM {SCHEMA}.product_origin WHERE origin_id = %s AND supplier_id = %s",
        (origin_id, supplier_id),
    )
    if not origin:
        raise HTTPException(status_code=404, detail="Product origin not found")

    try:
        expiry = date.fromisoformat(new_expiry_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    try:
        statements: list[tuple[str, tuple]] = [
            # Update the certification on the product origin record
            (
                f"""
                UPDATE {SCHEMA}.product_origin
                SET certification = %s,
                    certification_expiry = %s,
                    traceability_proof = COALESCE(%s, traceability_proof)
                WHERE origin_id = %s
                """,
                (new_certification, expiry, new_certificate_ref or None, origin_id),
            ),
            # Touch supplier's updated_at timestamp
            (
                f"""
                UPDATE {SCHEMA}.supplier
                SET updated_at = NOW()
                WHERE supplier_id = %s
                """,
                (supplier_id,),
            ),
        ]
        await _execute_write(statements)
        logger.info(
            "Certification renewed: origin_id=%s, supplier_id=%s, new_expiry=%s",
            origin_id, supplier_id, expiry,
        )
    except Exception:
        logger.exception(
            "Failed to renew certification: origin_id=%s, supplier_id=%s",
            origin_id, supplier_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to update certification. Please try again.",
        )

    # Redirect with 303 to prevent form re-submission
    return RedirectResponse(
        url=f"/supplier/{supplier_id}?renewed=1",
        status_code=303,
    )


@app.get("/supplier/{supplier_id}/audit", response_class=HTMLResponse)
async def supplier_audit_log(
    request: Request,
    supplier_id: str,
    table_filter: str | None = None,
):
    """Full audit log for all products linked to this supplier."""
    supplier = await _fetch_one(
        f"SELECT * FROM {SCHEMA}.supplier WHERE supplier_id = %s",
        (supplier_id,),
    )
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    # Build optional table_name filter
    filter_clause = ""
    params: list = [supplier_id]
    if table_filter:
        filter_clause = "AND pal.table_name = %s"
        params.append(table_filter)

    audit_entries = await _fetch_all(
        f"""
        SELECT pal.*
        FROM {SCHEMA}.passport_audit_log pal
        WHERE pal.passport_id IN (
            SELECT DISTINCT po.passport_id
            FROM {SCHEMA}.product_origin po
            WHERE po.supplier_id = %s
        )
        {filter_clause}
        ORDER BY pal.changed_at DESC
        LIMIT 100
        """,
        tuple(params),
    )

    # Get distinct table names for filter dropdown
    table_names = await _fetch_all(
        f"""
        SELECT DISTINCT pal.table_name
        FROM {SCHEMA}.passport_audit_log pal
        WHERE pal.passport_id IN (
            SELECT DISTINCT po.passport_id
            FROM {SCHEMA}.product_origin po
            WHERE po.supplier_id = %s
        )
        ORDER BY pal.table_name
        """,
        (supplier_id,),
    )

    return templates.TemplateResponse(
        "audit.html",
        {
            "request": request,
            "supplier": supplier,
            "audit_entries": audit_entries,
            "table_names": [r["table_name"] for r in table_names],
            "table_filter": table_filter or "",
            "brand": await _manufacturer_name(),
        },
    )


@app.get("/health")
async def health():
    """Health check endpoint. Returns 503 if the DB is unreachable so that
    Databricks Apps health probes do not route traffic to a broken instance.
    """
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        logger.exception("Health check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "error", "db": f"unreachable: {e}"},
        )
