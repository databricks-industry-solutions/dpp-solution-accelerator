"""
DPP Passport Viewer — Databricks App

Consumer-facing Digital Product Passport viewer. Users scan a QR code
on the product and land here to see the full passport: origin, materials,
environmental impact, compliance, circularity, and disposal info.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import threading
import uuid

import asyncpg
import qrcode
import requests
from databricks.sdk import WorkspaceClient
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger("passport_viewer")
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

# WORKSPACE_HOST is auto-set by Databricks Apps; required for FM API calls.
WORKSPACE_HOST = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
AI_MODEL = os.environ.get("AI_MODEL", "databricks-meta-llama-3-3-70b-instruct")

# Companion Supplier Portal app — surfaced as a nav link in the viewer.
# Prefer an explicit URL (SUPPLIER_PORTAL_URL); otherwise resolve the sibling
# app by name (SUPPLIER_PORTAL_APP, default matches resources/apps.yml). If
# neither resolves, the nav link is simply hidden — never fatal.
SUPPLIER_PORTAL_URL = os.environ.get("SUPPLIER_PORTAL_URL", "").rstrip("/")
SUPPLIER_PORTAL_APP = os.environ.get("SUPPLIER_PORTAL_APP", "dpp-supplier-portal")


def _resolve_lakebase_dns() -> str:
    """Resolve the Lakebase instance DNS (fallback / native-login path).

    Prefers an explicit LAKEBASE_DNS env var (useful for local dev).
    Falls back to looking up LAKEBASE_INSTANCE via the workspace API,
    so the app.yaml only needs the instance name.
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


PAGE_SIZE = 24

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()

_workspace_client: WorkspaceClient | None = None
_ws_lock = threading.Lock()

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
    w = _get_workspace_client()
    host = w.config.host.rstrip("/")
    resp = requests.post(
        f"{host}/api/2.0/database/credentials",
        headers=w.config.authenticate(),
        json={"request_id": str(uuid.uuid4()), "instance_names": [instance]},
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
    """Decode/encode uuid + json/jsonb as text so plain str values pass through
    transparently (the queries here use string IDs and json strings)."""
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
app = FastAPI(title="DPP Passport Viewer")
templates = Jinja2Templates(directory="templates")

# Static assets (architecture diagram on /demo). static/architecture.svg is a
# copy of docs/architecture.svg -- keep them in sync when the diagram changes.
app.mount("/static", StaticFiles(directory="static"), name="static")

_supplier_portal_url_cache: str | None = None
_supplier_portal_lock = threading.Lock()


def supplier_portal_url() -> str:
    """Resolve the Supplier Portal app URL for the nav link.

    Prefers the explicit SUPPLIER_PORTAL_URL env var. Otherwise looks the
    sibling app up by name via the workspace API and caches the result.
    Returns "" (link hidden) on any failure, so a missing/unreadable sibling
    app never breaks the viewer.
    """
    global _supplier_portal_url_cache
    if SUPPLIER_PORTAL_URL:
        return SUPPLIER_PORTAL_URL
    if _supplier_portal_url_cache is not None:
        return _supplier_portal_url_cache
    with _supplier_portal_lock:
        if _supplier_portal_url_cache is not None:
            return _supplier_portal_url_cache
        resolved = ""
        try:
            w = _get_workspace_client()
            resolved = (w.apps.get(name=SUPPLIER_PORTAL_APP).url or "").rstrip("/")
        except Exception as exc:  # noqa: BLE001 — nav link is best-effort
            logger.info("Supplier Portal URL not resolved (%s); nav link hidden.", exc)
        _supplier_portal_url_cache = resolved
        return resolved


# Expose to every template (base.html renders the nav link when non-empty).
templates.env.globals["supplier_portal_url"] = supplier_portal_url


# ---------------------------------------------------------------------------
# App access logging (opt-in)
# ---------------------------------------------------------------------------
# When ACCESS_LOG_ENABLED=true, record who opens the app to dpp.app_access_log.
# A deployed Databricks App runs behind SSO and injects the end user in the
# X-Forwarded-* headers, so each request carries the authenticated identity.
# Off by default: user emails are personal data (GDPR); the operator opts in.
# Best-effort and non-blocking, so it never slows a response or breaks a page.
ACCESS_LOG_ENABLED = os.environ.get("ACCESS_LOG_ENABLED", "false").lower() == "true"
_ACCESS_LOG_APP = "passport_viewer"
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


async def _attach_supplier_chains(origins: list[dict]) -> None:
    """Attach the upstream supplier chain to each origin record (in place).

    Walks parent_supplier_id with a recursive CTE: for each origin's supplier,
    returns the ancestors from that supplier up to its tier-1 (direct) supplier.
    Each origin gains a ``supplier_chain`` list of ``{name, tier}`` ordered from
    the supplier itself toward the manufacturer (empty for tier-1 suppliers).
    """
    supplier_ids = list({o["supplier_id"] for o in origins if o.get("supplier_id")})
    if not supplier_ids:
        return

    rows = await _fetch_all(
        f"""
        WITH RECURSIVE chain AS (
            SELECT supplier_id AS root_id, supplier_id, name, tier,
                   parent_supplier_id, 0 AS depth
            FROM {SCHEMA}.supplier
            WHERE supplier_id = ANY(%s)
            UNION ALL
            SELECT c.root_id, s.supplier_id, s.name, s.tier,
                   s.parent_supplier_id, c.depth + 1
            FROM {SCHEMA}.supplier s
            JOIN chain c ON s.supplier_id = c.parent_supplier_id
        )
        SELECT root_id, name, tier, depth
        FROM chain
        WHERE depth > 0
        ORDER BY root_id, depth
        """,
        (supplier_ids,),
    )

    chains: dict[str, list[dict]] = {}
    for r in rows:
        chains.setdefault(str(r["root_id"]), []).append(
            {"name": r["name"], "tier": r["tier"]}
        )

    for o in origins:
        o["supplier_chain"] = chains.get(str(o.get("supplier_id")), [])


async def _get_full_passport(passport_id: str) -> dict | None:
    """Fetch a complete passport with all 6 DPP categories.

    Uses 2 round-trips:
      1. Main passport with manufacturer + environmental_impact + circularity_info (all 1:1).
      2. asyncio.gather for the 1:many child records (origins, materials, compliance, disposal).
    """
    # Query 1: Main passport + 1:1 joins
    passport = await _fetch_one(
        f"""
        SELECT pp.*,
               m.name AS manufacturer_name, m.country AS manufacturer_country,
               m.website AS manufacturer_website, m.registration_number,
               ei.carbon_footprint_kg, ei.carbon_manufacturing, ei.carbon_transport,
               ei.carbon_use_phase, ei.carbon_end_of_life,
               ei.energy_consumption_kwh, ei.water_usage_liters,
               ei.lca_methodology, ei.verified_by,
               ci.repairability_score, ci.durability_years,
               ci.recyclability_pct, ci.recycled_content_pct,
               ci.spare_parts_available, ci.spare_parts_years,
               ci.refurbishable, ci.take_back_program,
               ci.second_life_options,
               ci.state_of_health_pct, ci.cycle_count, ci.dynamic_data_updated_at
        FROM {SCHEMA}.product_passport pp
        LEFT JOIN {SCHEMA}.manufacturer m ON pp.manufacturer_id = m.manufacturer_id
        LEFT JOIN {SCHEMA}.environmental_impact ei ON pp.passport_id = ei.passport_id
        LEFT JOIN {SCHEMA}.circularity_info ci ON pp.passport_id = ci.passport_id
        WHERE pp.passport_id = %s
        """,
        (passport_id,),
    )
    if not passport:
        return None

    # Split the flat row into separate dicts for the template
    impact_keys = {
        "carbon_footprint_kg", "carbon_manufacturing", "carbon_transport",
        "carbon_use_phase", "carbon_end_of_life", "energy_consumption_kwh",
        "water_usage_liters", "lca_methodology", "verified_by",
    }
    circularity_keys = {
        "repairability_score", "durability_years", "recyclability_pct",
        "recycled_content_pct", "spare_parts_available", "spare_parts_years",
        "refurbishable", "take_back_program", "second_life_options",
        "state_of_health_pct", "cycle_count", "dynamic_data_updated_at",
    }

    impact = {k: passport[k] for k in impact_keys if k in passport}
    circularity = {k: passport[k] for k in circularity_keys if k in passport}

    # Check if the joined data actually exists (all None = no row)
    impact = impact if any(v is not None for v in impact.values()) else None
    circularity = circularity if any(v is not None for v in circularity.values()) else None

    # Query 2: 1:many children in parallel
    origins_coro = _fetch_all(
        f"""
        SELECT po.*, s.name AS supplier_name, s.country AS supplier_country,
               s.risk_score, s.certifications AS supplier_certifications
        FROM {SCHEMA}.product_origin po
        JOIN {SCHEMA}.supplier s ON po.supplier_id = s.supplier_id
        WHERE po.passport_id = %s
        ORDER BY po.supply_chain_tier, s.name
        """,
        (passport_id,),
    )

    materials_coro = _fetch_all(
        f"SELECT * FROM {SCHEMA}.product_materials WHERE passport_id = %s "
        "ORDER BY percentage_by_weight DESC",
        (passport_id,),
    )

    compliance_coro = _fetch_all(
        f"SELECT * FROM {SCHEMA}.compliance_records WHERE passport_id = %s "
        "ORDER BY regulation_name",
        (passport_id,),
    )

    disposal_coro = _fetch_all(
        f"SELECT * FROM {SCHEMA}.disposal_guidelines WHERE passport_id = %s "
        "ORDER BY weight_kg DESC",
        (passport_id,),
    )

    origins, materials, compliance, disposal = await asyncio.gather(
        origins_coro, materials_coro, compliance_coro, disposal_coro,
    )

    # Resolve the multi-tier upstream chain for each origin's supplier so the
    # Origin tab can show full tier-1 -> tier-N traceability.
    await _attach_supplier_chains(origins)

    return {
        "passport": passport,
        "origins": origins,
        "materials": materials,
        "impact": impact,
        "compliance": compliance,
        "circularity": circularity,
        "disposal": disposal,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

_brand_name: str | None = None


async def _manufacturer_name() -> str:
    """Manufacturer display name for page branding (depends on the seeded
    profile: furniture or battery), read once from the DB and cached."""
    global _brand_name
    if _brand_name is None:
        row = await _fetch_one(f"SELECT name FROM {SCHEMA}.manufacturer LIMIT 1")
        _brand_name = (row or {}).get("name") or "Demo Manufacturer"
    return _brand_name


@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    page: int = 1,
):
    """Landing page with search, category filter, and pagination."""
    if page < 1:
        page = 1
    offset = (page - 1) * PAGE_SIZE

    # Build query based on filters
    conditions = []
    params: list = []

    if q:
        conditions.append(
            "(product_name ILIKE %s OR product_id ILIKE %s OR gtin ILIKE %s)"
        )
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    if category:
        conditions.append("product_category = %s")
        params.append(category)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([PAGE_SIZE + 1, offset])

    products = await _fetch_all(
        f"""
        SELECT passport_id, product_id, product_name, product_category,
               passport_status, country_of_origin
        FROM {SCHEMA}.product_passport
        {where}
        ORDER BY product_category, product_name, product_id
        LIMIT %s OFFSET %s
        """,
        tuple(params),
    )

    has_next = len(products) > PAGE_SIZE
    products = products[:PAGE_SIZE]

    # Get counts per category for the filter badges
    counts = await _fetch_all(
        f"""
        SELECT product_category, count(*) as cnt
        FROM {SCHEMA}.product_passport
        GROUP BY product_category
        ORDER BY product_category
        """,
    )
    category_counts = {r["product_category"]: r["cnt"] for r in counts}

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "products": products,
            "query": q or "",
            "category": category or "",
            "categories": list(category_counts),
            "category_counts": category_counts,
            "brand": await _manufacturer_name(),
            "page": page,
            "has_next": has_next,
            "has_prev": page > 1,
        },
    )


@app.get("/demo", response_class=HTMLResponse)
async def demo_guide(request: Request):
    """Guided demo / help walkthrough for the accelerator."""
    return templates.TemplateResponse(
        "demo.html",
        {"request": request, "brand": await _manufacturer_name()},
    )


@app.get("/passport/{passport_id}", response_class=HTMLResponse)
async def passport_view(request: Request, passport_id: str):
    """Consumer-facing passport detail page."""
    from datetime import date
    try:
        data = await _get_full_passport(passport_id)
        if not data:
            raise HTTPException(status_code=404, detail="Passport not found")
        return templates.TemplateResponse(
            "passport.html",
            {
                "request": request,
                "now": date.today().isoformat(),
                "brand": await _manufacturer_name(),
                **data,
            },
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error rendering passport %s", passport_id)
        return HTMLResponse(
            content="<p>An internal error occurred while loading this passport. Please try again later.</p>",
            status_code=500,
        )


@app.get("/api/passport/{passport_id}")
async def passport_api(passport_id: str):
    """JSON API for external system integration."""
    import json
    from datetime import date, datetime
    from decimal import Decimal
    import uuid as _uuid

    def _default(obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, _uuid.UUID):
            return str(obj)
        return str(obj)

    try:
        data = await _get_full_passport(passport_id)
        if not data:
            raise HTTPException(status_code=404, detail="Passport not found")
        return JSONResponse(
            content=json.loads(json.dumps(data, default=_default)),
            media_type="application/json",
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error fetching passport API for %s", passport_id)
        return JSONResponse(
            content={"error": "An internal error occurred. Please try again later."},
            status_code=500,
        )


@app.get("/api/qr/{passport_id}")
async def passport_qr(request: Request, passport_id: str):
    """Generate a QR code image for a passport."""
    passport = await _fetch_one(
        f"SELECT passport_id FROM {SCHEMA}.product_passport WHERE passport_id = %s",
        (passport_id,),
    )
    if not passport:
        raise HTTPException(status_code=404, detail="Passport not found")

    # Use X-Forwarded-Host/Proto headers (set by Databricks Apps proxy)
    # to build the public URL instead of request.base_url (which is localhost)
    fwd_host = request.headers.get("x-forwarded-host", "")
    fwd_proto = request.headers.get("x-forwarded-proto", "https")
    if fwd_host:
        base_url = f"{fwd_proto}://{fwd_host}"
    else:
        base_url = str(request.base_url).rstrip("/")
    url = f"{base_url}/passport/{passport_id}"

    img = qrcode.make(url, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return StreamingResponse(buf, media_type="image/png")


# ---------------------------------------------------------------------------
# AI Insights
# ---------------------------------------------------------------------------

def _get_workspace_client() -> WorkspaceClient:
    """Lazily initialize the WorkspaceClient (thread-safe)."""
    global _workspace_client
    if _workspace_client is not None:
        return _workspace_client
    with _ws_lock:
        if _workspace_client is not None:
            return _workspace_client
        _workspace_client = WorkspaceClient(host=WORKSPACE_HOST)
        return _workspace_client


def _build_insights_prompt(data: dict) -> str:
    """Build a data-rich prompt from the passport data for AI analysis."""
    p = data["passport"]
    impact = data.get("impact") or {}
    circularity = data.get("circularity") or {}
    materials = data.get("materials") or []
    compliance = data.get("compliance") or []
    origins = data.get("origins") or []

    # Materials summary
    mat_lines = []
    for m in materials:
        recycled = f", {m.get('recycled_content_pct', 0) or 0:.0f}% recycled" if m.get("recycled_content_pct") else ""
        flags = []
        if m.get("hazardous_flag"):
            flags.append("HAZARDOUS")
        if m.get("svhc_flag"):
            flags.append("SVHC")
        if m.get("renewable_flag"):
            flags.append("renewable")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        mat_lines.append(
            f"  - {m.get('material_name', 'Unknown')}: {m.get('percentage_by_weight', 0):.1f}% by weight{recycled}{flag_str}"
        )
    materials_text = "\n".join(mat_lines) if mat_lines else "  No materials data."

    # Compliance summary
    comp_lines = []
    for c in compliance:
        expiry = f", expires {c['expiry_date']}" if c.get("expiry_date") else ""
        comp_lines.append(
            f"  - {c.get('regulation_name', 'Unknown')}: {c.get('compliance_status', 'unknown')}{expiry}"
        )
    compliance_text = "\n".join(comp_lines) if comp_lines else "  No compliance records."

    # Origins / suppliers summary
    origin_lines = []
    for o in origins:
        risk = f", risk score {o['risk_score']:.1f}" if o.get("risk_score") else ""
        origin_lines.append(
            f"  - {o.get('component_name', 'Unknown')} from {o.get('supplier_name', '?')} ({o.get('supplier_country', '?')}), Tier {o.get('supply_chain_tier', '?')}{risk}"
        )
    origins_text = "\n".join(origin_lines) if origin_lines else "  No origin data."

    prompt = f"""Analyze this Digital Product Passport and provide structured insights.

PRODUCT DATA:
- Name: {p.get('product_name', 'N/A')}
- Category: {p.get('product_category', 'N/A')}
- Product ID: {p.get('product_id', 'N/A')}
- GTIN: {p.get('gtin', 'N/A')}
- Serial Number: {p.get('serial_number', 'N/A') or 'MISSING'}
- Passport Status: {p.get('passport_status', 'N/A')}
- Is Complete: {p.get('is_complete', 'N/A')}
- Country of Origin: {p.get('country_of_origin', 'N/A')}
- Production Facility: {p.get('production_facility', 'N/A') or 'MISSING'}
- Production Date: {p.get('production_date', 'N/A')}
- Manufacturer: {p.get('manufacturer_name', 'N/A')} ({p.get('manufacturer_country', 'N/A')})

CARBON / ENVIRONMENTAL IMPACT:
- Total Carbon Footprint: {impact.get('carbon_footprint_kg', 'N/A')} kg CO2e
- Manufacturing: {impact.get('carbon_manufacturing', 'N/A')} kg
- Transport: {impact.get('carbon_transport', 'N/A')} kg
- Use Phase: {impact.get('carbon_use_phase', 'N/A')} kg
- End of Life: {impact.get('carbon_end_of_life', 'N/A')} kg
- Energy Consumption: {impact.get('energy_consumption_kwh', 'N/A')} kWh
- Water Usage: {impact.get('water_usage_liters', 'N/A')} liters
- LCA Methodology: {impact.get('lca_methodology', 'N/A')}
- Verified By: {impact.get('verified_by', 'N/A') or 'NOT VERIFIED'}

MATERIALS:
{materials_text}

COMPLIANCE:
{compliance_text}

CIRCULARITY:
- Repairability Score: {circularity.get('repairability_score', 'N/A')}/10
- Durability: {circularity.get('durability_years', 'N/A')} years
- Recyclability: {circularity.get('recyclability_pct', 'N/A')}%
- Recycled Content: {circularity.get('recycled_content_pct', 'N/A')}%
- Spare Parts Available: {circularity.get('spare_parts_available', 'N/A')} (for {circularity.get('spare_parts_years', 'N/A')} years)
- Refurbishable: {circularity.get('refurbishable', 'N/A')}
- Take-Back Program: {circularity.get('take_back_program', 'N/A')}
- Second Life Options: {circularity.get('second_life_options', 'N/A')}

SUPPLY CHAIN:
{origins_text}

Respond ONLY with a JSON object (no markdown, no code fences) with these exact keys:
- "gaps": a list of strings describing missing or incomplete passport data (be specific about what is missing and why it matters)
- "carbon_analysis": a single string analyzing the carbon footprint — which lifecycle phase dominates, how this compares to typical {p.get('product_category', '')} products, and any concerns
- "compliance_alerts": a list of strings about expired/expiring certifications, non-compliant regulations, or risk areas
- "circularity_recommendations": a list of strings with specific, actionable recommendations to improve circularity (repairability, recycled content, take-back programs, etc.)

Be specific and reference actual numbers from the data. Do not give generic advice."""

    return prompt


def _get_ai_insights(passport_data: dict) -> dict:
    """Call the Databricks Foundation Model API and return structured insights."""
    prompt = _build_insights_prompt(passport_data)

    w = _get_workspace_client()
    headers = w.config.authenticate()
    token = headers.get("Authorization", "").replace("Bearer ", "")

    url = f"{WORKSPACE_HOST}/serving-endpoints/{AI_MODEL}/invocations"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1000,
            "temperature": 0.1,
        },
        timeout=30,
    )
    resp.raise_for_status()

    result = resp.json()
    raw_text = result["choices"][0]["message"]["content"]

    # Try to parse JSON from the response
    try:
        insights = json.loads(raw_text)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code fences
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_text)
        if match:
            try:
                insights = json.loads(match.group(1))
            except json.JSONDecodeError:
                insights = {
                    "gaps": [],
                    "carbon_analysis": raw_text,
                    "compliance_alerts": [],
                    "circularity_recommendations": [],
                    "raw_response": True,
                }
        else:
            insights = {
                "gaps": [],
                "carbon_analysis": raw_text,
                "compliance_alerts": [],
                "circularity_recommendations": [],
                "raw_response": True,
            }

    return insights


async def _fetch_cached_insights(passport_id: str) -> dict | None:
    """Return pre-computed insights from dpp.passport_insights, or None.

    Populated by the nightly precompute_insights job. Missing table (insights
    never run) is treated as a cache miss, not an error.
    """
    try:
        row = await _fetch_one(
            f"SELECT insights_json, generated_at FROM {SCHEMA}.passport_insights "
            "WHERE passport_id = %s",
            (passport_id,),
        )
    except Exception:
        logger.info("passport_insights cache unavailable; falling back to live FM")
        return None
    if not row or not row.get("insights_json"):
        return None
    try:
        insights = json.loads(row["insights_json"])
    except (json.JSONDecodeError, TypeError):
        return None
    insights["cached"] = True
    if row.get("generated_at"):
        insights["generated_at"] = row["generated_at"].isoformat()
    return insights


@app.get("/api/insights/{passport_id}")
async def passport_insights(passport_id: str):
    """AI-powered analysis of a product passport.

    Serves pre-computed insights from the Lakebase cache when available
    (populated nightly by the precompute_insights job); otherwise computes
    them live via the Foundation Model API.
    """
    try:
        cached = await _fetch_cached_insights(passport_id)
        if cached is not None:
            return JSONResponse(content=cached)

        data = await _get_full_passport(passport_id)
        if not data:
            raise HTTPException(status_code=404, detail="Passport not found")

        # Run the blocking AI call in a thread pool
        loop = asyncio.get_event_loop()
        insights = await loop.run_in_executor(None, _get_ai_insights, data)
        insights["cached"] = False
        return JSONResponse(content=insights)
    except HTTPException:
        raise
    except Exception:
        # No cached insights and the live Foundation Model call didn't succeed
        # (e.g. the app's service principal can't query the endpoint on this
        # workspace). Return a friendly "pending" state, not an error: the
        # nightly precompute job populates the cache for every passport.
        logger.info(
            "Live insights unavailable for %s; returning pending state", passport_id
        )
        return JSONResponse(
            content={
                "pending": True,
                "message": (
                    "AI insights for this passport are generated by a scheduled "
                    "job and haven't been computed yet. They'll appear here after "
                    "the next refresh."
                ),
            }
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
