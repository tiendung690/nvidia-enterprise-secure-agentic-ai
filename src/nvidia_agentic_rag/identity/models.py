from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

from nvidia_agentic_rag.security.classification import DataClassification


class IdentityContext(BaseModel):
    """Verified request identity. Client-supplied values must never bypass authentication."""

    user_id: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=128)
    roles: tuple[str, ...] = Field(default_factory=tuple)
    departments: tuple[str, ...] = Field(default_factory=tuple)
    clearance: DataClassification = DataClassification.PUBLIC
    authorization_version: str = Field(default="1", min_length=1, max_length=128)
    token_id: str | None = Field(default=None, max_length=256)
    claims: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @field_validator("clearance", mode="before")
    @classmethod
    def parse_clearance(cls, value: object) -> DataClassification:
        return DataClassification.parse(value)  # type: ignore[arg-type]

    @field_validator("roles", "departments", mode="before")
    @classmethod
    def normalize_values(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            raw = value.split(",")
        else:
            raw = list(value)  # type: ignore[arg-type]
        return tuple(sorted({str(item).strip().casefold() for item in raw if str(item).strip()}))

    def authorization_hash(self) -> str:
        payload = {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "roles": self.roles,
            "departments": self.departments,
            "clearance": int(self.clearance),
            "authorization_version": self.authorization_version,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def anonymous_public(cls, user_id: str = "anonymous") -> "IdentityContext":
        return cls(user_id=user_id, tenant_id="public", clearance=DataClassification.PUBLIC)
