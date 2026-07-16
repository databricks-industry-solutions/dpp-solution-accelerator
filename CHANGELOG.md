# Changelog

All notable changes to the DPP Solution Accelerator are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [1.0.0] - 2026-07-10

First public release — a reproducible, bundle-deployed Digital Product Passport
accelerator on the Databricks Data Intelligence Platform. The default profile is
`battery`: the battery passport is the first mandatory EU DPP (18 Feb 2027),
making it the highest-impact lead. `furniture` remains selectable via
`--var profile=furniture`.

### Added
- **Foundation**: Lakebase schema (12 tables, audit triggers), deterministic
  synthetic data generator (500 products, 50 suppliers), and a single
  self-contained setup task (apply schema + generate + seed in one process via
  runtime OAuth — no secrets, no cross-task filesystem dependency).
- **Multi-tier supply chain**: `supplier.parent_supplier_id` self-reference,
  tier-by-tier synthetic graph, `gold_supplier_traceability`, and an upstream
  supply-chain view in the Passport Viewer's Origin tab. In the battery profile,
  origins read `mine → cell → module → pack` via tier-correlated component names.
- **Battery realism**, grounded in Reg. 2023/1542 (Annex XIII) and the DG GROW
  battery-DPP webinar (27 May 2026):
  - **State of health** dynamic data (`circularity_info.state_of_health_pct`,
    `cycle_count`, `dynamic_data_updated_at`) for rechargeable categories only,
    surfaced as a "Battery Health" panel in the Passport Viewer.
  - **Phased compliance**: carbon footprint (Art.7), recycled content (Art.8),
    and supply-chain due diligence (Art.48) are always present but marked
    `pending` with a note — they are not required at the Feb-2027 launch.
- **SDP pipeline**: Bronze (Lakebase snapshot) → Silver (conformance + DQ
  expectations) → Gold. Gold includes passport-complete, supply-chain lineage,
  carbon aggregates, compliance gap analysis, circularity metrics, material
  composition trends, and app usage.
- **Passport Viewer** app: 7-tab consumer passport, QR codes, category filters
  (with distinct colors per battery category), search, pagination, a nav link to
  the Supplier Portal, and a **"How it's built"** page (`/demo`) explaining the
  data sources, pipeline, governance, and platform capabilities.
- **Supplier Portal** app: supplier self-service with Lakebase writes and audit log.
- **Opt-in app access logging** (`ACCESS_LOG_ENABLED`, off by default). When
  enabled, both apps record who opens them to `dpp.app_access_log` (user
  identity from the Databricks Apps SSO `X-Forwarded-*` headers). Best-effort
  and non-blocking; user emails are personal data, so it stays disabled unless
  the operator turns it on. Surfaced on the dashboard's **App Usage** page.
- **AI/BI dashboard** (portfolio, compliance & risk, environmental impact,
  supply chain risk, app usage) + **Genie space** for natural-language exploration.
- **Pre-computed AI insights**: nightly `ai_query` job writes
  `gold.dpp_passport_insights` and a Lakebase serving table; the viewer serves
  cached insights with a live Foundation Model fallback, and shows a friendly
  "generated on a schedule" note for passports not yet cached.
- **One-command deploy**: apps, pipelines, and jobs all ship via
  `databricks bundle deploy`. Apps bind the Lakebase instance as a resource
  (service-principal role, OAuth password, injected DNS).

### Notes
- The regulatory timeline in the README and `docs/positioning.md` is aligned to
  the European Commission
  [DPP overview](https://single-market-economy.ec.europa.eu/single-market/digital-product-passport_en)
  (Registry operational 20 Jul 2026, batteries 18 Feb 2027, iron & steel delegated
  act Q4 2026, Unique-Identifier implementing act Q2 2027). The README states
  plainly that v1.0 is a reference architecture and demo, not a turnkey compliance
  product — in particular it serves data openly and does not implement the
  regulation's tiered access rights or Registry registration.
- `ROADMAP.md` documents deliberate v1.0 exclusions (tiered access control,
  Registry integration + Unique Identifier, time-series State-of-Health ingestion,
  full Annex XIII battery parameters, DPP data-backup obligation, value-chain
  aggregation, standards-conformant identifier/API, and an iron & steel profile),
  each mapped to an EU requirement and a Databricks capability.

[1.0.0]: https://github.com/databricks-industry-solutions/dpp-solution-accelerator/releases/tag/v1.0.0
