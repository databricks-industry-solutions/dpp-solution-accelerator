-- ===========================================================================
-- Digital Product Passport (DPP) -- Lakebase Schema DDL
-- Target: Lakebase (PostgreSQL-compatible)
-- ===========================================================================
-- Run this script against the Lakebase PostgreSQL endpoint to create all
-- tables required for the DPP operational store.
--
-- Idempotent: uses CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS.
-- ===========================================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Schema
CREATE SCHEMA IF NOT EXISTS dpp;

-- -------------------------------------------------------------------
-- 1. Manufacturer
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dpp.manufacturer (
    manufacturer_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              VARCHAR(255) NOT NULL,
    country           VARCHAR(3)   NOT NULL,
    registration_number VARCHAR(100),
    website           VARCHAR(500),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- -------------------------------------------------------------------
-- 2. Supplier
-- -------------------------------------------------------------------
-- Self-referential FK (parent_supplier_id) models multi-tier supply chains:
-- a tier-N supplier's parent is the tier-(N-1) supplier it delivers to, so the
-- chain walks "up" toward the manufacturer. Tier-1 (direct) suppliers have a
-- NULL parent. This enables full tier-1 -> tier-N traceability (recursive walk).
CREATE TABLE IF NOT EXISTS dpp.supplier (
    supplier_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name               VARCHAR(255) NOT NULL,
    country            VARCHAR(3)   NOT NULL,
    tier               INT          NOT NULL CHECK (tier BETWEEN 1 AND 3),
    parent_supplier_id UUID         REFERENCES dpp.supplier(supplier_id),
    risk_score         DECIMAL(3,1) CHECK (risk_score BETWEEN 0.0 AND 10.0),
    certifications     TEXT[],
    last_audit_date    DATE,
    active             BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_supplier_country ON dpp.supplier (country);
CREATE INDEX IF NOT EXISTS idx_supplier_tier    ON dpp.supplier (tier);
CREATE INDEX IF NOT EXISTS idx_supplier_parent  ON dpp.supplier (parent_supplier_id);

-- -------------------------------------------------------------------
-- 3. Product Passport (core entity)
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dpp.product_passport (
    passport_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id        VARCHAR(50)  NOT NULL,
    gtin              VARCHAR(14),
    serial_number     VARCHAR(100),
    batch_lot_number  VARCHAR(100),
    product_name      VARCHAR(255) NOT NULL,
    product_category  VARCHAR(100) NOT NULL,
    manufacturer_id   UUID         NOT NULL REFERENCES dpp.manufacturer(manufacturer_id),
    production_date   DATE,
    production_facility VARCHAR(255),
    country_of_origin VARCHAR(3),
    passport_status   VARCHAR(20)  NOT NULL DEFAULT 'draft',
    qr_code_url       TEXT,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_passport_status CHECK (
        passport_status IN ('draft', 'active', 'expired', 'revoked')
    ),
    CONSTRAINT uq_product_id UNIQUE (product_id)
);

CREATE INDEX IF NOT EXISTS idx_passport_product_id ON dpp.product_passport (product_id);
CREATE INDEX IF NOT EXISTS idx_passport_gtin       ON dpp.product_passport (gtin);
CREATE INDEX IF NOT EXISTS idx_passport_category   ON dpp.product_passport (product_category);
CREATE INDEX IF NOT EXISTS idx_passport_status     ON dpp.product_passport (passport_status);

-- -------------------------------------------------------------------
-- 4. Product Origin (supply chain traceability)
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dpp.product_origin (
    origin_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    passport_id         UUID NOT NULL REFERENCES dpp.product_passport(passport_id),
    supplier_id         UUID NOT NULL REFERENCES dpp.supplier(supplier_id),
    supply_chain_tier   INT  NOT NULL,
    component_name      VARCHAR(255) NOT NULL,
    source_country      VARCHAR(3),
    source_region       VARCHAR(255),
    certification       VARCHAR(255),
    certification_expiry DATE,
    traceability_proof  TEXT
);

CREATE INDEX IF NOT EXISTS idx_origin_passport ON dpp.product_origin (passport_id);
CREATE INDEX IF NOT EXISTS idx_origin_supplier ON dpp.product_origin (supplier_id);

-- -------------------------------------------------------------------
-- 5. Product Materials (bill of materials / composition)
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dpp.product_materials (
    material_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    passport_id          UUID NOT NULL REFERENCES dpp.product_passport(passport_id),
    material_name        VARCHAR(255) NOT NULL,
    material_category    VARCHAR(100),
    percentage_by_weight DECIMAL(5,2) NOT NULL CHECK (percentage_by_weight BETWEEN 0 AND 100),
    recycled_content_pct DECIMAL(5,2) CHECK (recycled_content_pct BETWEEN 0 AND 100),
    renewable_flag       BOOLEAN DEFAULT FALSE,
    hazardous_flag       BOOLEAN DEFAULT FALSE,
    cas_number           VARCHAR(20),
    reach_compliant      BOOLEAN DEFAULT TRUE,
    svhc_flag            BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_materials_passport ON dpp.product_materials (passport_id);

-- -------------------------------------------------------------------
-- 6. Environmental Impact (LCA data)
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dpp.environmental_impact (
    impact_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    passport_id            UUID NOT NULL REFERENCES dpp.product_passport(passport_id),
    carbon_footprint_kg    DECIMAL(10,3),
    carbon_manufacturing   DECIMAL(10,3),
    carbon_transport       DECIMAL(10,3),
    carbon_use_phase       DECIMAL(10,3),
    carbon_end_of_life     DECIMAL(10,3),
    energy_consumption_kwh DECIMAL(10,3),
    water_usage_liters     DECIMAL(10,3),
    lca_methodology        VARCHAR(100),
    lca_data_source        VARCHAR(255),
    assessment_date        DATE,
    verified_by            VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_impact_passport ON dpp.environmental_impact (passport_id);

-- -------------------------------------------------------------------
-- 7. Compliance Records
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dpp.compliance_records (
    compliance_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    passport_id        UUID NOT NULL REFERENCES dpp.product_passport(passport_id),
    regulation_name    VARCHAR(255) NOT NULL,
    regulation_version VARCHAR(50),
    compliance_status  VARCHAR(20) NOT NULL,
    certificate_ref    VARCHAR(255),
    issuing_body       VARCHAR(255),
    issue_date         DATE,
    expiry_date        DATE,
    document_url       TEXT,
    notes              TEXT,
    CONSTRAINT chk_compliance_status CHECK (
        compliance_status IN ('compliant', 'pending', 'non_compliant', 'expired')
    )
);

CREATE INDEX IF NOT EXISTS idx_compliance_passport ON dpp.compliance_records (passport_id);
CREATE INDEX IF NOT EXISTS idx_compliance_status   ON dpp.compliance_records (compliance_status);

-- -------------------------------------------------------------------
-- 8. Circularity Information
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dpp.circularity_info (
    circularity_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    passport_id           UUID NOT NULL REFERENCES dpp.product_passport(passport_id),
    durability_years      INT,
    repairability_score   DECIMAL(3,1) CHECK (repairability_score BETWEEN 0 AND 10),
    spare_parts_available BOOLEAN DEFAULT FALSE,
    spare_parts_years     INT,
    refurbishable         BOOLEAN DEFAULT FALSE,
    recycled_content_pct  DECIMAL(5,2) CHECK (recycled_content_pct BETWEEN 0 AND 100),
    recyclability_pct     DECIMAL(5,2) CHECK (recyclability_pct BETWEEN 0 AND 100),
    take_back_program     BOOLEAN DEFAULT FALSE,
    second_life_options   TEXT[],
    -- Dynamic data (EU Batteries Reg. Art.10/14): state of health + cycle count.
    -- Populated only for rechargeable batteries with a BMS; NULL otherwise.
    state_of_health_pct     DECIMAL(5,2) CHECK (state_of_health_pct BETWEEN 0 AND 100),
    cycle_count             INT,
    dynamic_data_updated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_circularity_passport ON dpp.circularity_info (passport_id);

-- Additive migration: CREATE TABLE IF NOT EXISTS does not add new columns to a
-- table that already exists from an earlier deploy, so add the dynamic-data
-- columns explicitly. Idempotent via ADD COLUMN IF NOT EXISTS.
ALTER TABLE dpp.circularity_info ADD COLUMN IF NOT EXISTS state_of_health_pct     DECIMAL(5,2);
ALTER TABLE dpp.circularity_info ADD COLUMN IF NOT EXISTS cycle_count             INT;
ALTER TABLE dpp.circularity_info ADD COLUMN IF NOT EXISTS dynamic_data_updated_at TIMESTAMPTZ;

-- -------------------------------------------------------------------
-- 9. Disposal Guidelines
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dpp.disposal_guidelines (
    disposal_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    passport_id        UUID NOT NULL REFERENCES dpp.product_passport(passport_id),
    component_name     VARCHAR(255) NOT NULL,
    disposal_method    VARCHAR(100),
    disassembly_steps  TEXT,
    recycling_code     VARCHAR(20),
    local_collection_info TEXT,
    special_handling   TEXT,
    weight_kg          DECIMAL(8,3)
);

CREATE INDEX IF NOT EXISTS idx_disposal_passport ON dpp.disposal_guidelines (passport_id);

-- -------------------------------------------------------------------
-- 10. Passport Audit Log (change tracking)
-- -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dpp.passport_audit_log (
    log_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    passport_id  UUID,
    table_name   VARCHAR(100) NOT NULL,
    action       VARCHAR(10)  NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
    changed_by   VARCHAR(255),
    changed_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    old_values   JSONB,
    new_values   JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_passport  ON dpp.passport_audit_log (passport_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON dpp.passport_audit_log (changed_at);

-- -------------------------------------------------------------------
-- 11. Passport AI Insights (pre-computed cache)
-- -------------------------------------------------------------------
-- Populated by the nightly precompute_insights job (ai_query over the Gold
-- layer). The Passport Viewer serves these cached insights instead of calling
-- the Foundation Model API on every page view. insights_json holds the same
-- shape the app expects: {gaps, carbon_analysis, compliance_alerts,
-- circularity_recommendations}.
CREATE TABLE IF NOT EXISTS dpp.passport_insights (
    passport_id   UUID PRIMARY KEY REFERENCES dpp.product_passport(passport_id),
    insights_json TEXT NOT NULL,
    model         VARCHAR(255),
    generated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -------------------------------------------------------------------
-- 12. App Access Log (opt-in usage tracking)
-- -------------------------------------------------------------------
-- Populated by the apps only when ACCESS_LOG_ENABLED=true. Records who opens
-- the Passport Viewer / Supplier Portal. A deployed Databricks App runs behind
-- SSO and injects the end user in X-Forwarded-* headers, so each request
-- carries the authenticated identity. This is personal data (GDPR); keep it
-- disabled unless you need internal usage tracking. Not covered by the audit
-- trigger below (no passport_id).
CREATE TABLE IF NOT EXISTS dpp.app_access_log (
    access_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email   VARCHAR(320),
    user_name    VARCHAR(255),
    app_name     VARCHAR(100),
    path         TEXT,
    method       VARCHAR(10),
    client_ip    VARCHAR(64),
    user_agent   TEXT,
    accessed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_access_email ON dpp.app_access_log (user_email);
CREATE INDEX IF NOT EXISTS idx_access_time  ON dpp.app_access_log (accessed_at);

-- -------------------------------------------------------------------
-- Audit trigger function (auto-populate audit log on changes)
-- -------------------------------------------------------------------
CREATE OR REPLACE FUNCTION dpp.audit_trigger_func()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO dpp.passport_audit_log (passport_id, table_name, action, changed_by, new_values)
        VALUES (NEW.passport_id, TG_TABLE_NAME, 'INSERT', current_user, to_jsonb(NEW));
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO dpp.passport_audit_log (passport_id, table_name, action, changed_by, old_values, new_values)
        VALUES (NEW.passport_id, TG_TABLE_NAME, 'UPDATE', current_user, to_jsonb(OLD), to_jsonb(NEW));
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO dpp.passport_audit_log (passport_id, table_name, action, changed_by, old_values)
        VALUES (OLD.passport_id, TG_TABLE_NAME, 'DELETE', current_user, to_jsonb(OLD));
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Apply audit triggers to key tables
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN SELECT unnest(ARRAY[
        'product_passport', 'product_origin', 'product_materials',
        'environmental_impact', 'compliance_records', 'circularity_info',
        'disposal_guidelines'
    ]) LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS audit_trigger ON dpp.%I; '
            'CREATE TRIGGER audit_trigger '
            'AFTER INSERT OR UPDATE OR DELETE ON dpp.%I '
            'FOR EACH ROW EXECUTE FUNCTION dpp.audit_trigger_func();',
            tbl, tbl
        );
    END LOOP;
END $$;

-- -------------------------------------------------------------------
-- Grants for the Databricks Apps' service-principal roles
-- -------------------------------------------------------------------
-- DEMO-GRADE: grant to PUBLIC so each app's bound Postgres role (its injected
-- PGUSER) can read/write without a separate per-role step. Every Postgres role
-- is implicitly a member of PUBLIC. The Supplier Portal needs writes, the
-- Viewer only reads -- PUBLIC covers both.
--
-- PRODUCTION: drop these and grant least privilege to each app's PGUSER, e.g.
--   GRANT USAGE ON SCHEMA dpp TO "<viewer-pguser>";
--   GRANT SELECT ON ALL TABLES IN SCHEMA dpp TO "<viewer-pguser>";
--   GRANT SELECT, INSERT, UPDATE ON <writable tables> TO "<portal-pguser>";
GRANT USAGE ON SCHEMA dpp TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA dpp TO PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA dpp
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO PUBLIC;
