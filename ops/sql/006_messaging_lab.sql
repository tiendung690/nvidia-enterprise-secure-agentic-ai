-- Messaging lab: idempotent inbox + broker-independent failure ledger.
CREATE TABLE IF NOT EXISTS agent_message_inbox (
    consumer_name text NOT NULL,
    event_id text NOT NULL,
    event_type text NOT NULL,
    payload_hash text NOT NULL,
    correlation_id text,
    tenant_id text,
    status text NOT NULL CHECK (status IN ('processing','processed','failed')),
    received_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    last_error text,
    PRIMARY KEY (consumer_name, event_id)
);
CREATE INDEX IF NOT EXISTS ix_agent_message_inbox_status_time
ON agent_message_inbox(consumer_name, status, received_at DESC);

CREATE TABLE IF NOT EXISTS agent_dlq_record (
    dlq_id bigserial PRIMARY KEY,
    consumer_name text NOT NULL,
    event_id text,
    event_type text,
    error_class text NOT NULL,
    error_message text NOT NULL,
    retry_count integer NOT NULL DEFAULT 0,
    correlation_id text,
    payload jsonb,
    failed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_agent_dlq_record_consumer_time
ON agent_dlq_record(consumer_name, failed_at DESC);

-- Lab consumer uses the local postgres admin URL by default. In production create a
-- dedicated consumer DB role with only the grants it needs.
