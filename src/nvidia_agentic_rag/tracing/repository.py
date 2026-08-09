from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Protocol

from nvidia_agentic_rag.tracing.models import RunTrace


class TraceRepository(Protocol):
    def ping(self) -> bool: ...
    def save(self, trace: RunTrace) -> None: ...
    def get(
        self, run_id: str, *, tenant_id: str | None = None, user_id: str | None = None
    ) -> RunTrace | None: ...


class InMemoryTraceRepository:
    def __init__(self) -> None:
        self._records: dict[str, RunTrace] = {}
        self._lock = threading.RLock()

    def ping(self) -> bool:
        return True

    def save(self, trace: RunTrace) -> None:
        with self._lock:
            self._records[trace.run_id] = trace.model_copy(deep=True)

    def get(
        self, run_id: str, *, tenant_id: str | None = None, user_id: str | None = None
    ) -> RunTrace | None:
        with self._lock:
            value = self._records.get(run_id)
            if value is None or (tenant_id is not None and value.tenant_id != tenant_id):
                return None
            if user_id is not None and value.user_id != user_id:
                return None
            return value.model_copy(deep=True)


class JsonlTraceRepository:
    """Append-only local trace adapter. Use PostgreSQL/object storage in production."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._latest: dict[str, RunTrace] = {}
        self._lock = threading.RLock()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    trace = RunTrace.model_validate_json(line)
                except Exception:
                    continue
                self._latest[trace.run_id] = trace

    def ping(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return self.path.parent.is_dir()
        except OSError:
            return False

    def save(self, trace: RunTrace) -> None:
        payload = trace.model_dump_json()
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")
            self._latest[trace.run_id] = trace.model_copy(deep=True)

    def get(
        self, run_id: str, *, tenant_id: str | None = None, user_id: str | None = None
    ) -> RunTrace | None:
        with self._lock:
            value = self._latest.get(run_id)
            if value is None or (tenant_id is not None and value.tenant_id != tenant_id):
                return None
            if user_id is not None and value.user_id != user_id:
                return None
            return value.model_copy(deep=True)


class PostgresTraceRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def ping(self) -> bool:
        import psycopg

        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                row = connection.execute(
                    "SELECT to_regclass('public.agent_run_trace') IS NOT NULL"
                ).fetchone()
                return bool(row and row[0])
        except Exception:
            return False

    def save(self, trace: RunTrace) -> None:
        import psycopg

        with psycopg.connect(self.database_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (trace.tenant_id,))
            cursor.execute("SELECT set_config('app.user_id', %s, true)", (trace.user_id,))
            cursor.execute(
                """
                INSERT INTO agent_run_trace(run_id, request_id, session_id, tenant_id, user_id,
                    purpose, query_hash, started_at, completed_at, outcome, answer_hash,
                    index_version, memory_version, prompt_version, provider, latency_ms,
                    source_ids, tool_names, retrieval_traces, memory_reads, memory_writes,
                    events, error_code)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,
                    %s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s)
                ON CONFLICT (run_id) DO UPDATE SET completed_at=EXCLUDED.completed_at,
                    outcome=EXCLUDED.outcome, answer_hash=EXCLUDED.answer_hash,
                    latency_ms=EXCLUDED.latency_ms, source_ids=EXCLUDED.source_ids,
                    tool_names=EXCLUDED.tool_names, retrieval_traces=EXCLUDED.retrieval_traces,
                    memory_reads=EXCLUDED.memory_reads, memory_writes=EXCLUDED.memory_writes,
                    events=EXCLUDED.events,
                    error_code=EXCLUDED.error_code, memory_version=EXCLUDED.memory_version
                """,
                (
                    trace.run_id, trace.request_id, trace.session_id, trace.tenant_id,
                    trace.user_id, trace.purpose, trace.query_hash, trace.started_at,
                    trace.completed_at, trace.outcome, trace.answer_hash, trace.index_version,
                    trace.memory_version, trace.prompt_version, trace.provider, trace.latency_ms,
                    json.dumps(trace.source_ids), json.dumps(trace.tool_names),
                    json.dumps(trace.retrieval_traces), json.dumps(trace.memory_reads),
                    json.dumps(trace.memory_writes),
                    json.dumps([event.model_dump(mode="json") for event in trace.events]),
                    trace.error_code,
                ),
            )
            connection.commit()

    def get(
        self, run_id: str, *, tenant_id: str | None = None, user_id: str | None = None
    ) -> RunTrace | None:
        import psycopg
        from psycopg.rows import dict_row

        if tenant_id is None:
            return None
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
                cursor.execute("SELECT set_config('app.user_id', %s, true)", (user_id or "",))
                cursor.execute(
                    "SELECT * FROM agent_run_trace WHERE run_id=%s AND tenant_id=%s",
                    (run_id, tenant_id),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return RunTrace.model_validate(dict(row))

