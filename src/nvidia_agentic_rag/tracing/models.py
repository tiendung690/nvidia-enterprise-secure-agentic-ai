from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

TraceOutcome = Literal["running", "success", "blocked", "failed"]


class TraceEvent(BaseModel):
    event_type: str = Field(min_length=1, max_length=128)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = Field(default_factory=dict)


class RunTrace(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    request_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=256)
    purpose: str = Field(min_length=1, max_length=128)
    query_hash: str = Field(min_length=64, max_length=64)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    outcome: TraceOutcome = "running"
    answer_hash: str | None = None
    index_version: str = "unknown"
    memory_version: str = "unknown"
    prompt_version: str = "unknown"
    provider: str = "nvidia"
    latency_ms: float = Field(default=0.0, ge=0)
    source_ids: list[str] = Field(default_factory=list)
    tool_names: list[str] = Field(default_factory=list)
    retrieval_traces: list[dict[str, Any]] = Field(default_factory=list)
    memory_reads: dict[str, int] = Field(default_factory=dict)
    memory_writes: dict[str, int] = Field(default_factory=dict)
    events: list[TraceEvent] = Field(default_factory=list)
    error_code: str | None = None


__all__ = ["RunTrace", "TraceEvent", "TraceOutcome"]
