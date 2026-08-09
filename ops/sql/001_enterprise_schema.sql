DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agentic_app') THEN
        CREATE ROLE agentic_app LOGIN PASSWORD 'agentic_app' NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agentic_registry') THEN
        CREATE ROLE agentic_registry LOGIN PASSWORD 'agentic_registry'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS document_registry (
    corpus text NOT NULL,
    relative_path text NOT NULL,
    document_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    classification text NOT NULL CHECK (classification IN ('public','internal','confidential','restricted')),
    is_public boolean NOT NULL DEFAULT false,
    owner_department text,
    allowed_roles text[] NOT NULL DEFAULT '{}',
    allowed_departments text[] NOT NULL DEFAULT '{}',
    allowed_purposes text[] NOT NULL DEFAULT '{}',
    shared_with_tenants text[] NOT NULL DEFAULT '{}',
    source_version integer NOT NULL DEFAULT 1 CHECK (source_version > 0),
    policy_version text NOT NULL,
    valid_from timestamptz,
    expires_at timestamptz,
    content_hash text,
    active boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (corpus, relative_path)
);

CREATE TABLE IF NOT EXISTS operational_order (
    order_id text NOT NULL,
    tenant_id text NOT NULL,
    status text NOT NULL,
    delivered_at timestamptz,
    product_category text,
    customer_reference text,
    record_version integer NOT NULL DEFAULT 1 CHECK (record_version > 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, order_id)
);

CREATE TABLE IF NOT EXISTS security_audit_event (
    event_id text PRIMARY KEY,
    occurred_at timestamptz NOT NULL,
    request_id text NOT NULL,
    user_id text NOT NULL,
    tenant_id text NOT NULL,
    purpose text NOT NULL,
    action text NOT NULL,
    outcome text NOT NULL,
    policy_decision_id text,
    policy_version text NOT NULL,
    query_hash text NOT NULL,
    answer_hash text,
    source_ids text[] NOT NULL DEFAULT '{}',
    classifications text[] NOT NULL DEFAULT '{}',
    details jsonb NOT NULL DEFAULT '{}'
);

ALTER TABLE operational_order ENABLE ROW LEVEL SECURITY;
ALTER TABLE operational_order FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS operational_order_tenant_read ON operational_order;
CREATE POLICY operational_order_tenant_read ON operational_order
FOR SELECT
USING (tenant_id = current_setting('app.tenant_id', true));

ALTER TABLE document_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_registry FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_registry_tenant_read ON document_registry;
CREATE POLICY document_registry_tenant_read ON document_registry
FOR SELECT
USING (
    current_user = 'agentic_registry'
    OR is_public = true
    OR tenant_id = current_setting('app.tenant_id', true)
    OR current_setting('app.tenant_id', true) = ANY(shared_with_tenants)
);

CREATE INDEX IF NOT EXISTS ix_document_registry_lookup
ON document_registry (lower(corpus), lower(relative_path)) WHERE active = true;
CREATE INDEX IF NOT EXISTS ix_operational_order_tenant
ON operational_order (tenant_id, order_id);
CREATE INDEX IF NOT EXISTS ix_security_audit_tenant_time
ON security_audit_event (tenant_id, occurred_at DESC);


GRANT CONNECT ON DATABASE agentic_ai TO agentic_app, agentic_registry;
GRANT USAGE ON SCHEMA public TO agentic_app, agentic_registry;
GRANT SELECT ON operational_order TO agentic_app;
GRANT SELECT ON document_registry TO agentic_registry;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON operational_order FROM agentic_app;
REVOKE ALL ON security_audit_event FROM agentic_app, agentic_registry;
