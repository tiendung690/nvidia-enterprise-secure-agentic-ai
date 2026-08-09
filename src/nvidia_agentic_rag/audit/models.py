from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    event_id: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: str
    user_id: str
    tenant_id: str
    purpose: str
    action: str
    outcome: str
    policy_decision_id: str | None = None
    policy_version: str
    query_hash: str
    answer_hash: str | None = None
    source_ids: tuple[str, ...] = Field(default_factory=tuple)
    classifications: tuple[str, ...] = Field(default_factory=tuple)
    details: dict[str, str | int | bool | float | None] = Field(default_factory=dict)
