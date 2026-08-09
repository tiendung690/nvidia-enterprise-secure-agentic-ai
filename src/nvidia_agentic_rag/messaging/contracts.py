from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventEnvelope(BaseModel):
    """Versioned event contract shared across broker adapters.

    event_id is the transport/business deduplication key. correlation_id follows the
    end-to-end workflow; causation_id points to the event/request that caused this event.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=3, max_length=160)
    schema_version: int = Field(default=1, ge=1)
    aggregate_type: str = Field(min_length=1, max_length=80)
    aggregate_id: str = Field(min_length=1, max_length=160)
    tenant_id: str | None = None
    user_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    priority: str = "standard"
    payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_outbox_row(cls, row: dict[str, Any]) -> "EventEnvelope":
        payload = dict(row.get("payload") or {})
        correlation_id = payload.pop("correlation_id", None)
        causation_id = payload.pop("causation_id", None)
        priority = str(payload.pop("priority", "standard"))
        return cls(
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            aggregate_type=str(row["aggregate_type"]),
            aggregate_id=str(row["aggregate_id"]),
            tenant_id=row.get("tenant_id"),
            user_id=row.get("user_id"),
            correlation_id=correlation_id,
            causation_id=causation_id,
            occurred_at=row.get("created_at") or datetime.now(timezone.utc),
            priority=priority,
            payload=payload,
        )
