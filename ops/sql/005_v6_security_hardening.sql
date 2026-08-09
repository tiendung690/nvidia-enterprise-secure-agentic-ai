-- Hardening migration for early v6 previews: tenant-safe memory administration,
-- tenant-tagged outbox events, and PostgreSQL audit persistence.
ALTER TABLE agent_outbox ADD COLUMN IF NOT EXISTS tenant_id text;
ALTER TABLE agent_outbox ADD COLUMN IF NOT EXISTS user_id text;
ALTER TABLE agent_run_trace
    ADD COLUMN IF NOT EXISTS memory_writes jsonb NOT NULL DEFAULT '{}';

ALTER TABLE agent_memory
    DROP CONSTRAINT IF EXISTS agent_memory_superseded_by_fkey;
ALTER TABLE agent_memory
    ADD CONSTRAINT agent_memory_superseded_by_fkey
    FOREIGN KEY (superseded_by) REFERENCES agent_memory(memory_id) ON DELETE SET NULL;

UPDATE agent_outbox AS outbox
SET tenant_id = memory.tenant_id,
    user_id = memory.user_id
FROM agent_memory AS memory
WHERE outbox.aggregate_type = 'memory'
  AND outbox.aggregate_id = memory.memory_id
  AND outbox.tenant_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_agent_outbox_tenant_unpublished
ON agent_outbox(tenant_id, created_at) WHERE published_at IS NULL;

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

REVOKE ALL ON agent_outbox FROM agentic_app;
GRANT INSERT ON agent_outbox TO agentic_app;
GRANT INSERT ON security_audit_event TO agentic_app;
