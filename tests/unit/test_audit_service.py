from __future__ import annotations

import json

from nvidia_agentic_rag.audit import AuditEvent, InMemoryAuditService, JsonlAuditService


def event() -> AuditEvent:
    return AuditEvent(
        event_id="AE-1",
        request_id="R-1",
        user_id="U-1",
        tenant_id="T-1",
        purpose="research",
        action="agent.chat",
        outcome="success",
        policy_version="P-1",
        query_hash="q",
    )


def test_memory_and_jsonl_audit_sinks(tmp_path) -> None:
    memory = InMemoryAuditService()
    memory.record(event())
    assert memory.events[0].event_id == "AE-1"

    path = tmp_path / "audit" / "events.jsonl"
    sink = JsonlAuditService(path)
    sink.record(event())
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["query_hash"] == "q"
    assert "raw_query" not in payload
