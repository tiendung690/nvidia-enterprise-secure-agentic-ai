from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from nvidia_agentic_rag.security.classification import DataClassification


class DocumentPolicyRecord(BaseModel):
    corpus: str = Field(min_length=1, max_length=128)
    relative_path: str = Field(min_length=1, max_length=512)
    document_id: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=128)
    classification: DataClassification = DataClassification.INTERNAL
    is_public: bool = False
    owner_department: str | None = Field(default=None, max_length=128)
    allowed_roles: tuple[str, ...] = Field(default_factory=tuple)
    allowed_departments: tuple[str, ...] = Field(default_factory=tuple)
    allowed_purposes: tuple[str, ...] = Field(default_factory=tuple)
    shared_with_tenants: tuple[str, ...] = Field(default_factory=tuple)
    source_version: int = Field(default=1, ge=1)
    policy_version: str = Field(default="enterprise-policy-v1", min_length=1, max_length=128)
    valid_from: datetime | None = None
    expires_at: datetime | None = None
    content_hash: str | None = Field(default=None, max_length=128)

    @field_validator("classification", mode="before")
    @classmethod
    def parse_classification(cls, value: object) -> DataClassification:
        return DataClassification.parse(value)  # type: ignore[arg-type]

    @field_validator(
        "allowed_roles",
        "allowed_departments",
        "allowed_purposes",
        "shared_with_tenants",
        mode="before",
    )
    @classmethod
    def normalize_collections(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            items = value.split(",")
        else:
            items = list(value)  # type: ignore[arg-type]
        return tuple(sorted({str(item).strip().casefold() for item in items if str(item).strip()}))

    def is_active(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        valid_from = self.valid_from
        expires_at = self.expires_at
        if valid_from and valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=timezone.utc)
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if valid_from and now < valid_from:
            return False
        return not expires_at or now < expires_at

    def metadata(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "tenant_id": self.tenant_id,
            "classification": self.classification.label(),
            "is_public": self.is_public,
            "owner_department": self.owner_department,
            "allowed_roles": list(self.allowed_roles),
            "allowed_departments": list(self.allowed_departments),
            "allowed_purposes": list(self.allowed_purposes),
            "shared_with_tenants": list(self.shared_with_tenants),
            "source_version": self.source_version,
            "policy_version": self.policy_version,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "content_hash": self.content_hash,
        }


class PolicyDecision(BaseModel):
    allowed: bool
    decision_id: str
    policy_version: str
    reason: str
    action: str
    resource_id: str | None = None
    obligations: dict[str, Any] = Field(default_factory=dict)


class PolicyAudit(BaseModel):
    status: Literal["allowed", "denied", "insufficient_context", "not_applicable"] = (
        "not_applicable"
    )
    decision_id: str | None = None
    policy_version: str = "unknown"
    purpose: str | None = None
    tenant_id: str | None = None
    authorized_source_count: int = Field(default=0, ge=0)
    denied_candidate_count: int = Field(default=0, ge=0)
    classifications: list[str] = Field(default_factory=list)
    output_dlp_signals: list[str] = Field(default_factory=list)
    reason: str | None = None
