# Positioning: why a DPP accelerator on Databricks

## The regulatory driver
The EU Digital Product Passport is mandated by the Ecodesign for Sustainable
Products Regulation (ESPR, 2024/1781) and product-specific acts. It is not
discretionary — it is law, with hard dates:

- **Batteries first** — mandatory **18 February 2027** (EU Batteries Regulation
  2023/1542).
- **Iron & steel** is among the earliest ESPR groups (delegated act **Q4 2026**),
  then **construction products (Q2 2027)**, **textiles, aluminium, tyres (2027)**,
  **furniture (2028)** and **mattresses / recycled-content (2029)**.
- The EU **DPP Registry is operational 20 July 2026**; the Implementing Act for
  the Registry-issued **Unique Identifier (URI)** is scheduled **Q2 2027**.

Product-group dates are set by the individual delegated / sector acts and keep
moving; confirm against the act that applies to you. Every in-scope product sold
in the EU needs a passport.

## How the EU system works — and where the gap is
The Commission's design is **decentralized by intent**. It builds a thin central
layer only:

- **DPP Registry** — stores unique identifiers + pointers (a data-quality gate),
  not the passport content.
- **DPP Web Portal** — lets stakeholders find *links* to passports, by permission.
- **ICSMS interoperability** — market-surveillance authorities resolve a Unique
  Product Identifier to the right passport.
- **Standards** — CEN-CENELEC JTC24 (unique IDs, data carrier, API, data
  exchange, storage, authentication, access rights); EN 18219/18220 for QR + UID.

Crucially, **the passport data itself is not held centrally** — "the full DPP
data is stored with the economic operators or authorised operators." The QR data
carrier resolves to the *operator's own system*. For batteries the Commission is
explicit that DPP service providers are not involved — the responsible economic
operator runs it directly.

**Implication:** every manufacturer/importer must stand up its own DPP backend —
operational store, analytics, serving, AI, governance, and value-chain sharing.

## Where this accelerator fits
This accelerator is the **economic operator's DPP backend** on the Databricks
Data Intelligence Platform:

| Need | Databricks |
|------|-----------|
| Operational passport store (QR lookups, supplier writes, audit) | **Lakebase** |
| Compliance, carbon, multi-tier traceability, circularity | **SDP** Bronze/Silver/Gold |
| Consumer passport viewer + supplier portal | **Databricks Apps** |
| Insights, NL exploration, compliance reporting | **AI Functions, Genie, AI/BI** |
| Tiered access + secure value-chain / cross-border sharing | **Unity Catalog, Delta Sharing** |

It **complements** the EU's Registry/Portal/standards (integration points), it
does not replace them — and it does not compete with DPP-SaaS vendors; it can be
the data backbone behind them. The schema is **domain-agnostic** with selectable
industry profiles (battery, furniture, …), so one foundation serves multiple
product groups.

## Shared responsibility
This accelerator is enablement and reference architecture. The platform provides
the building blocks; the **operator is responsible** for enforcing its own access
controls, network/data-egress policy, and data-residency / cross-border
constraints before exposing DPP data. See [ROADMAP.md](../ROADMAP.md) for the
tiered-access-control extension.
