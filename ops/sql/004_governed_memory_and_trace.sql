-- v6: governed durable memory, replayable run traces, and transactional outbox.
CREATE TABLE IF NOT EXISTS agent_memory (
    memory_id text PRIMARY KEY,
    memory_type text NOT NULL CHECK (memory_type IN ('policy','preference','fact','episodic','trace')),
    status text NOT NULL CHECK (status IN ('provisional','active','superseded','rejected','deleted')),
    scope text NOT NULL CHECK (scope IN ('user','tenant','global')),
    tenant_id text,
    user_id text,
    subject text NOT NULL,
    predicate text,
    value text,
    content text NOT NULL,
    content_hash text NOT NULL,
    confidence double precision NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    provenance text NOT NULL CHECK (
        provenance IN ('user_stated','tool_observed','document_derived','model_inferred','admin_configured')
    ),
    source_run_id text,
    source_ids text[] NOT NULL DEFAULT '{}',
    effective_from timestamptz NOT NULL DEFAULT now(),
    effective_until timestamptz,
    superseded_by text REFERENCES agent_memory(memory_id) ON DELETE SET NULL,
    metadata jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    search_vector tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(subject,'') || ' ' || coalesce(predicate,'') || ' ' ||
            coalesce(value,'') || ' ' || coalesce(content,''))
    ) STORED,
    CHECK (
        (scope = 'global' AND tenant_id IS NULL AND user_id IS NULL)
        OR (scope = 'tenant' AND tenant_id IS NOT NULL AND user_id IS NULL)
        OR (scope = 'user' AND tenant_id IS NOT NULL AND user_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_memory_active_hash_scope
ON agent_memory(memory_type, scope, coalesce(tenant_id,''), coalesce(user_id,''), content_hash)
WHERE status = 'active';

CREATE INDEX IF NOT EXISTS ix_agent_memory_exact
ON agent_memory(scope, tenant_id, user_id, memory_type, status, effective_from, effective_until);
CREATE INDEX IF NOT EXISTS ix_agent_memory_subject_predicate
ON agent_memory(lower(subject), lower(coalesce(predicate,'')), status);
CREATE INDEX IF NOT EXISTS ix_agent_memory_search
ON agent_memory USING gin(search_vector);
CREATE INDEX IF NOT EXISTS ix_agent_memory_source_run
ON agent_memory(source_run_id) WHERE source_run_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS agent_run_trace (
    run_id text PRIMARY KEY,
    request_id text NOT NULL,
    session_id text NOT NULL,
    tenant_id text NOT NULL,
    user_id text NOT NULL,
    purpose text NOT NULL,
    query_hash text NOT NULL,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    outcome text NOT NULL CHECK (outcome IN ('running','success','blocked','failed')),
    answer_hash text,
    index_version text NOT NULL,
    memory_version text NOT NULL,
    prompt_version text NOT NULL,
    provider text NOT NULL,
    latency_ms integer NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
    source_ids jsonb NOT NULL DEFAULT '[]',
    tool_names jsonb NOT NULL DEFAULT '[]',
    retrieval_traces jsonb NOT NULL DEFAULT '[]',
    memory_reads jsonb NOT NULL DEFAULT '{}',
    memory_writes jsonb NOT NULL DEFAULT '{}',
    events jsonb NOT NULL DEFAULT '[]',
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_agent_run_trace_tenant_time
ON agent_run_trace(tenant_id, started_at DESC);
CREATE INDEX IF NOT EXISTS ix_agent_run_trace_request ON agent_run_trace(request_id);

CREATE TABLE IF NOT EXISTS agent_outbox (
    event_id text PRIMARY KEY,
    aggregate_type text NOT NULL,
    aggregate_id text NOT NULL,
    event_type text NOT NULL,
    tenant_id text,
    user_id text,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    publish_attempts integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_agent_outbox_unpublished
ON agent_outbox(created_at) WHERE published_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_agent_outbox_tenant_unpublished
ON agent_outbox(tenant_id, created_at) WHERE published_at IS NULL;

ALTER TABLE agent_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_memory FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS agent_memory_scope_read ON agent_memory;
CREATE POLICY agent_memory_scope_read ON agent_memory FOR SELECT USING (
    scope = 'global'
    OR (
        tenant_id = current_setting('app.tenant_id', true)
        AND (
            scope = 'tenant'
            OR (
                scope = 'user'
                AND (
                    user_id = current_setting('app.user_id', true)
                    OR current_setting('app.is_memory_admin', true) = 'true'
                )
            )
        )
    )
);
DROP POLICY IF EXISTS agent_memory_scope_write ON agent_memory;
CREATE POLICY agent_memory_scope_write ON agent_memory FOR ALL USING (
    scope <> 'global'
    AND tenant_id = current_setting('app.tenant_id', true)
    AND (
        scope = 'tenant'
        OR (
            scope = 'user'
            AND (
                user_id = current_setting('app.user_id', true)
                OR current_setting('app.is_memory_admin', true) = 'true'
            )
        )
    )
) WITH CHECK (
    scope <> 'global'
    AND tenant_id = current_setting('app.tenant_id', true)
    AND (
        scope = 'tenant'
        OR (
            scope = 'user'
            AND (
                user_id = current_setting('app.user_id', true)
                OR current_setting('app.is_memory_admin', true) = 'true'
            )
        )
    )
);

ALTER TABLE agent_run_trace ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_run_trace FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS agent_run_trace_tenant ON agent_run_trace;
CREATE POLICY agent_run_trace_tenant ON agent_run_trace FOR ALL
USING (tenant_id = current_setting('app.tenant_id', true))
WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

ALTER TABLE agent_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_outbox FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS agent_outbox_tenant_insert ON agent_outbox;
CREATE POLICY agent_outbox_tenant_insert ON agent_outbox FOR INSERT
WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

ALTER TABLE security_audit_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE security_audit_event FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS security_audit_tenant_insert ON security_audit_event;
CREATE POLICY security_audit_tenant_insert ON security_audit_event FOR INSERT
WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

GRANT SELECT, INSERT, UPDATE, DELETE ON agent_memory TO agentic_app;
GRANT SELECT, INSERT, UPDATE ON agent_run_trace TO agentic_app;
REVOKE ALL ON agent_outbox FROM agentic_app;
GRANT INSERT ON agent_outbox TO agentic_app;
GRANT INSERT ON security_audit_event TO agentic_app;
