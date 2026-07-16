# Security Policy

## Reporting a Vulnerability

Please email bugbounty@databricks.com to report any security vulnerabilities. We will acknowledge receipt of your vulnerability and strive to send you regular updates about our progress. If you're curious about the status of your disclosure please feel free to email us again. If you want to encrypt your disclosure email, you can use [this PGP key](https://keybase.io/arikfr/key.asc).

Do not open a public GitHub issue for security vulnerabilities. If you find a
leaked credential (API key, token, password) in this repository or a pull
request, treat it as an incident: invalidate the credential immediately and
report it.

## Credentials and secrets

This accelerator is designed to run with **no static credentials**:

- Pipeline and setup jobs authenticate to Lakebase with short-lived OAuth tokens
  derived from the job's identity (no secrets).
- The apps authenticate to Lakebase by binding the database instance as an app
  resource and minting a short-lived OAuth token with the app's service
  principal — no password is stored. A PG native-login fallback (secret-scope
  password) is provided only for local development.
- No API keys, tokens, or passwords are committed to this repository.

## Shared responsibility

This is a solution accelerator and reference architecture — **not** a compliance
product, a certification, or legal advice, and it does not by itself make any
organization compliant with the EU Digital Product Passport or any regulation.

In particular, the bundled apps are **demo-grade**: the Supplier Portal and
Passport Viewer have no application-level authentication or authorization
(any user who can reach the portal can renew any supplier's certificate), and
the schema DDL grants read/write to `PUBLIC`. Both are deliberate so a demo
deploys with zero manual steps — neither is acceptable for production.

Before exposing any DPP application or data, the deploying organization is
responsible for enforcing, per its own policies and with its own legal and
regulatory teams:

- Access controls and authentication on the apps and data.
- Network and data-egress controls.
- Data residency and any cross-border transfer constraints.
- Which passport data is public vs. restricted (data tiering).

## Supported usage

The accelerator targets the latest Databricks Runtime and Serverless compute on
Unity Catalog. Run it in a non-production workspace for evaluation; harden per
the README "Production hardening" section before any production use.

