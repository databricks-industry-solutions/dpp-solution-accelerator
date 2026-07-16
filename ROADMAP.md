# Roadmap

v1.0 delivers a complete, deployable DPP accelerator with an industry-agnostic
schema and two profiles (`battery` (default), `furniture`). The items below are **deliberately
out of scope for v1.0** — they are credible extensions, each mapped to the EU
requirements that motivate them and the Databricks capability that would showcase
them. They are documented here so adopters can prioritise without re-discovering
the analysis.

Sources: the European Commission
[DPP overview](https://single-market-economy.ec.europa.eu/single-market/digital-product-passport_en);
the EC webinar *"The Digital Product Passport — Implications and Practical
Guidance for the Battery Industry"* (DG GROW, 27 May 2026); and EU Batteries
Regulation 2023/1542, Annex XIII.

## Suggested v2 priority order

Based on the current EU framework and the dated obligations landing in 2026-2027,
a v2 would lead with these (the first four are the biggest correctness gaps, the
rest deepen coverage):

1. **Tiered access control (ABAC)** — the largest gap; v1.0 serves everything openly.
2. **DPP Registry integration + Unique Identifier (URI)** — dated obligation (Registry live 20 Jul 2026; URI implementing act Q2 2027).
3. **Daily State-of-Health time-series** — the strongest operational battery differentiator.
4. **DPP data backup / persistence obligation** — a distinct economic-operator duty.
5. **Iron & steel profile** — early-mandate group (delegated act Q4 2026), directly on the manufacturing customer base.
6. **Value-chain aggregation + cross-border exchange** — nested sub-passports, Clean Rooms.
7. **Standards-conformant identifier, data carrier, and DPP API** — CEN-CENELEC / EN 18219-18220.

## Candidate extensions

### 1. Tiered access control (public / restricted / notified-body)
- **Why:** Annex XIII defines distinct access tiers — public (battery model),
  restricted to persons with a legitimate interest, and notified-bodies/market-
  surveillance only. v1.0 serves all passport data publicly.
- **Shape (generic):** an `access_tier` classification on data fields/tables; the
  viewer renders a public section and a gated restricted section.
- **Databricks showcase:** Unity Catalog ABAC, row/column masking, and Delta
  Sharing for sharing restricted data with specific counterparties.
- Applies to **every** product group, not just batteries.

### 2. Dynamic data time series / daily SoH ingestion
- **Why:** Art 14 requires per-battery SoH (updated *daily*), charge/discharge
  cycle count, status, negative events, and operating conditions (temperature,
  state of charge). v1.0 models the **latest** SoH snapshot per battery
  (`circularity_info.state_of_health_pct`, `cycle_count`,
  `dynamic_data_updated_at`) but not the update pipeline or history.
- **Shape (generic):** a time-series table keyed by passport + timestamp; battery
  populates SoH/cycles, other industries can use it for any dynamic attribute.
- **Databricks showcase:** Lakebase OLTP for the latest value + Spark Structured
  Streaming / Zerobus for ingestion + Delta history for the trend. The single
  strongest operational differentiator for the battery use case.

### 3. Battery technical/performance parameters + status lifecycle
- **Why:** Annex XIII 1(f–s) — rated capacity (Ah), min/nominal/max voltage,
  power (W), expected lifetime in cycles, capacity threshold for exhaustion (EV),
  internal resistance, C-rate, commercial warranty. Plus the status lifecycle
  *original → repurposed → reused → remanufactured → waste* ("the passport ceases
  to exist after recycling"; a new passport + new responsible operator on
  remanufacture), a **critical-raw-material (CRM) flag** on materials, and the
  **responsible-sourcing / due-diligence report** (Art 52(3), required by Aug 2028).
- **Shape (generic):** a key-value `product_performance` table (attribute, value,
  unit) so any product group can carry its own technical parameters; extend the
  status enum per profile; add `crm_flag`; add a due-diligence document reference.
- **Databricks showcase:** AI Functions to extract due-diligence/ESG report fields;
  metric views over performance parameters.

### 4. Value-chain aggregation + cross-border exchange
- **Why:** the EC webinar's Catena-X case shows passports **aggregated** across tiers
  (mining → material → cell → module → pack), and the EU/China cross-border case
  (Lingang–BMW–CATL) shows compliant cross-jurisdiction exchange.
- **Shape:** model nested/aggregated sub-passports that roll a component's
  upstream passports into the finished-product passport.
- **Databricks showcase:** Delta Sharing and Clean Rooms for sovereign cross-company
  / cross-border exchange — directly addresses the "EU requires disclosure vs China
  restricts outflow" challenge.

### 5. DPP Registry integration + Unique Identifier (URI)
- **Why:** the EU
  [DPP overview](https://single-market-economy.ec.europa.eu/single-market/digital-product-passport_en)
  is explicit that the operator must **register the DPP in the central Registry
  before market placement** (EU-manufactured) or **at customs** (imports), and the
  Registry **issues a Unique Registration Identifier (URI)** that the data carrier
  resolves against. The Registry is operational **20 July 2026**; the **Implementing
  Act for Unique Identifiers is scheduled Q2 2027**. v1.0 has no registration concept
  or URI, only a self-minted demo QR.
- **Shape (generic):** a `registration` concept on the passport (`registry_id`/URI,
  `registration_status`, `registered_at`) and a small registration-state machine
  (draft → registered → placed-on-market); the data carrier resolves via the URI.
- **Databricks showcase:** Lakebase state machine + a standards-shaped DPP API served
  from Databricks Apps; audit trail in Unity Catalog. Highest-value v2 headline
  because it is dated and unambiguous.

### 6. DPP data backup / persistence obligation
- **Why:** the EU overview lists a distinct economic-operator duty to **maintain a
  backup of the product information** so the passport survives even if the operator
  ceases trading (data must remain resolvable for the product's regulated lifetime).
  v1.0 models none of this.
- **Shape (generic):** retention policy + an escrow/hand-off concept for a passport
  when an operator exits; point-in-time recoverability of passport state.
- **Databricks showcase:** Delta time-travel / retention for point-in-time state, and
  Delta Sharing to a third-party escrow / successor operator — a clean, differentiated
  continuity story that few DPP-SaaS front-ends address.

### 7. Standards-conformant identifier, data carrier, and DPP API
- **Why:** the DPP relies on **8 CEN-CENELEC harmonised standards** (unique identifiers,
  data carrier, API, data exchange, storage, authentication, access rights); the EU
  page notes six land by July 2026 and two more by summer 2026, with **EN 18219 /
  EN 18220** for the QR + unique identifier. v1.0 uses a demo QR and an ad-hoc schema,
  not a standards-conformant identifier scheme or API.
- **Shape (generic):** a conformant identifier/data-carrier module and a DPP API surface
  shaped to the emerging standard, so a passport is interoperable with the Registry,
  Web Portal, and ICSMS market-surveillance resolution.
- **Databricks showcase:** Databricks Apps as the standards-conformant API host over the
  governed Lakebase + lakehouse data.

### 8. Iron & steel industry profile
- **Why:** iron & steel is one of the **earliest ESPR groups (delegated act Q4 2026)**,
  ahead of most, and lands squarely on the manufacturing customer base this accelerator
  targets. A third profile proves the "domain-agnostic schema, swap the data" claim on a
  near-term-mandated, non-battery group.
- **Shape:** a new `steel` entry in `PROFILES` (product catalog, materials, EPD/carbon
  ranges, mill/route metadata, scrap-content and recycled-content fields, relevant
  standards) — no schema or app changes, matching the existing profile mechanism.
- **Databricks showcase:** the same stack, re-profiled; a concrete GTM hook for steel /
  heavy-industry accounts.

## Engineering hardening (deferred from the v1.0 review)

Smaller code-quality items identified in the pre-publication review, deferred
to keep v1.0 lean:

- Extract the duplicated database helpers in the two apps (`_to_pg`, OAuth
  token mint, pool management, fetch helpers — ~200 lines) into a shared
  module copied into each app's `source_code_path`.
- Validate UUID path parameters up front so unknown IDs return 404 instead of
  a Postgres `22P02` error surfacing as a 500.
- Add `ruff` and unit tests for `_to_pg` and the seeder's SQL-splitting /
  value-preparation helpers to CI; make `bundle validate` a required CI step.
- Move the SDP pipeline from the `PREVIEW` channel to `CURRENT` once the
  features it relies on land there.
- Replace `asyncio.get_event_loop()` in the viewer's AI path with
  `asyncio.to_thread`.

## Standards tracking (informational)
- QR + unique identifier: EN 18219 / EN 18220 (referenced via delegated act).
- CEN-CENELEC JTC24: 8 harmonised DPP standards (identifiers, interoperability,
  data carrier, API, data exchange, storage, authentication, access rights).
- DPP Registry operational 20 July 2026; battery passports mandatory 18 February 2027.
- Implementing Act for Unique Identifiers scheduled Q2 2027 (Registry-issued URI).
