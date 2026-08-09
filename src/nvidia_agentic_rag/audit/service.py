from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Protocol

from nvidia_agentic_rag.audit.models import AuditEvent


class AuditService(Protocol):
    def ping(self) -> bool: ...
    def record(self, event: AuditEvent) -> None: ...


class InMemoryAuditService:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def ping(self) -> bool:
        return True

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


class JsonlAuditService:
    """Append-only local audit sink. It records hashes/IDs, not raw prompts or answers."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def ping(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return self.path.parent.is_dir()
        except OSError:
            return False

    def record(self, event: AuditEvent) -> None:
        line = json.dumps(event.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


class PostgresAuditService:
    """Tenant-scoped append-only audit sink for multi-replica production."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def ping(self) -> bool:
        import psycopg

        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                row = connection.execute(
                    "SELECT to_regclass('public.security_audit_event') IS NOT NULL"
                ).fetchone()
                return bool(row and row[0])
        except Exception:
            return False

    def record(self, event: AuditEvent) -> None:
        import psycopg

        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (event.tenant_id,))
            cursor.execute("SELECT set_config('app.user_id', %s, true)", (event.user_id,))
            cursor.execute(
                """
                INSERT INTO security_audit_event (
                    event_id, occurred_at, request_id, user_id, tenant_id, purpose, action,
                    outcome, policy_decision_id, policy_version, query_hash, answer_hash,
                    source_ids, classifications, details
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
                )
                """,
                (
                    event.event_id,
                    event.occurred_at,
                    event.request_id,
                    event.user_id,
                    event.tenant_id,
                    event.purpose,
                    event.action,
                    event.outcome,
                    event.policy_decision_id,
                    event.policy_version,
                    event.query_hash,
                    event.answer_hash,
                    list(event.source_ids),
                    list(event.classifications),
                    json.dumps(event.details),
                ),
            )
            connection.commit()


def new_audit_event_id() -> str:
    return "AE-" + uuid.uuid4().hex.upper()
