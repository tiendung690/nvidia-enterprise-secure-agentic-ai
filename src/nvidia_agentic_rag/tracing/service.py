from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from nvidia_agentic_rag.identity import IdentityContext
from nvidia_agentic_rag.metrics import TRACE_EVENTS
from nvidia_agentic_rag.tracing.models import RunTrace, TraceEvent
from nvidia_agentic_rag.tracing.repository import TraceRepository


class TraceService:
    def __init__(self, repository: TraceRepository) -> None:
        self.repository = repository

    def ping(self) -> bool:
        return self.repository.ping()

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def start(
        self, *, request_id: str, session_id: str, identity: IdentityContext,
        purpose: str, query: str, index_version: str, memory_version: str,
        prompt_version: str,
    ) -> RunTrace:
        trace = RunTrace(
            request_id=request_id,
            session_id=session_id,
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            purpose=purpose,
            query_hash=self._hash(query),
            index_version=index_version,
            memory_version=memory_version,
            prompt_version=prompt_version,
            events=[TraceEvent(event_type="run.started")],
        )
        self.repository.save(trace)
        TRACE_EVENTS.labels(event="started").inc()
        return trace

    def complete(
        self,
        trace: RunTrace,
        *,
        answer: str,
        latency_ms: float,
        source_ids: list[str],
        tool_names: list[str],
        memory_reads: dict[str, int],
        memory_writes: dict[str, int] | None = None,
        outcome: str = "success",
    ) -> RunTrace:
        trace.completed_at = datetime.now(timezone.utc)
        trace.outcome = "success" if outcome in {"success", "cache_hit"} else "blocked"
        trace.answer_hash = self._hash(answer)
        trace.latency_ms = latency_ms
        trace.source_ids = list(dict.fromkeys(source_ids))
        trace.tool_names = list(dict.fromkeys(tool_names))
        trace.memory_reads = memory_reads
        trace.memory_writes = memory_writes or {}
        trace.events.append(TraceEvent(event_type="run.completed", data={"outcome": outcome}))
        self.repository.save(trace)
        TRACE_EVENTS.labels(event="completed").inc()
        return trace

    def fail(
        self,
        trace: RunTrace,
        *,
        error_code: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        trace.completed_at = datetime.now(timezone.utc)
        trace.outcome = "failed"
        trace.error_code = error_code
        trace.events.append(TraceEvent(event_type="run.failed", data=details or {}))
        self.repository.save(trace)
        TRACE_EVENTS.labels(event="failed").inc()

    def get(
        self, run_id: str, *, identity: IdentityContext | None = None
    ) -> RunTrace | None:
        return self.repository.get(
            run_id,
            tenant_id=identity.tenant_id if identity else None,
            user_id=None,
        )
