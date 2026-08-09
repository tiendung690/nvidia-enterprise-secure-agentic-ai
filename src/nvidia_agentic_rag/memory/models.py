from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class MemoryType(StrEnum):
    POLICY = "policy"
    PREFERENCE = "preference"
    FACT = "fact"
    EPISODIC = "episodic"
    TRACE = "trace"


class MemoryScope(StrEnum):
    USER = "user"
    TENANT = "tenant"
    GLOBAL = "global"


class MemoryStatus(StrEnum):
    PROVISIONAL = "provisional"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    DELETED = "deleted"


class ProvenanceKind(StrEnum):
    USER_STATED = "user_stated"
    TOOL_OBSERVED = "tool_observed"
    DOCUMENT_DERIVED = "document_derived"
    MODEL_INFERRED = "model_inferred"
    ADMIN_CONFIGURED = "admin_configured"


class MemoryCandidate(BaseModel):
    """Untrusted proposal. Status and final scope are always computed server-side."""

    memory_type: MemoryType
    content: str = Field(min_length=1, max_length=8000)
    subject: str = Field(min_length=1, max_length=512)
    predicate: str | None = Field(default=None, max_length=256)
    value: str | None = Field(default=None, max_length=4000)
    requested_scope: MemoryScope = MemoryScope.USER
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance: ProvenanceKind
    source_run_id: str | None = Field(default=None, max_length=256)
    source_ids: tuple[str, ...] = Field(default_factory=tuple)
    task_completed: bool = False
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content", "subject", "predicate", "value", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if value is None:
            return None
        return " ".join(str(value).split())

    @field_validator("source_ids", mode="before")
    @classmethod
    def normalize_sources(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            values = [value]
        else:
            values = list(value)  # type: ignore[arg-type]
        return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


class MemoryRecord(BaseModel):
    memory_id: str
    memory_type: MemoryType
    status: MemoryStatus
    scope: MemoryScope
    tenant_id: str | None = None
    user_id: str | None = None
    subject: str
    predicate: str | None = None
    value: str | None = None
    content: str
    content_hash: str
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: ProvenanceKind
    source_run_id: str | None = None
    source_ids: tuple[str, ...] = Field(default_factory=tuple)
    effective_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    effective_until: datetime | None = None
    superseded_by: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    def active_at(self, when: datetime | None = None) -> bool:
        when = when or datetime.now(timezone.utc)
        return (
            self.status == MemoryStatus.ACTIVE
            and self.effective_from <= when
            and (self.effective_until is None or when < self.effective_until)
        )


class PromotionDecision(BaseModel):
    accepted: bool
    final_scope: MemoryScope
    status: MemoryStatus
    reason: str
    memory_id: str | None = None
    deduplicated: bool = False
    superseded_memory_id: str | None = None


class MemoryContext(BaseModel):
    exact_records: list[MemoryRecord] = Field(default_factory=list)
    semantic_records: list[MemoryRecord] = Field(default_factory=list)
    prompt_fragment: str = ""
    version: str = "empty"


class MemoryWriteResult(BaseModel):
    decisions: list[PromotionDecision] = Field(default_factory=list)


__all__ = [
    "MemoryCandidate",
    "MemoryContext",
    "MemoryRecord",
    "MemoryScope",
    "MemoryStatus",
    "MemoryType",
    "MemoryWriteResult",
    "PromotionDecision",
    "ProvenanceKind",
]
