from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from nvidia_agentic_rag.identity.models import IdentityContext
from nvidia_agentic_rag.policy.models import DocumentPolicyRecord, PolicyDecision
from nvidia_agentic_rag.security.classification import DataClassification


class PolicyEngine:
    """Deterministic RBAC/ABAC policy engine; the LLM never makes access decisions."""

    def __init__(self, *, policy_version: str, allowed_purposes: tuple[str, ...]) -> None:
        self.policy_version = policy_version
        self.allowed_purposes = {purpose.casefold() for purpose in allowed_purposes}

    def _decision_id(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, default=str).encode()
        return "PD-" + hashlib.sha256(raw).hexdigest()[:16].upper()

    def authorize_query(
        self,
        *,
        identity: IdentityContext,
        purpose: str,
        answer_mode: str,
    ) -> PolicyDecision:
        normalized_purpose = purpose.strip().casefold()
        payload = {
            "policy": self.policy_version,
            "authz": identity.authorization_hash(),
            "purpose": normalized_purpose,
            "answer_mode": answer_mode,
            "action": "agent.chat",
        }
        if not normalized_purpose:
            allowed, reason = False, "purpose is required"
        elif self.allowed_purposes and normalized_purpose not in self.allowed_purposes:
            allowed, reason = False, "purpose is not permitted by enterprise policy"
        else:
            allowed, reason = True, "query purpose is permitted"
        return PolicyDecision(
            allowed=allowed,
            decision_id=self._decision_id(payload | {"allowed": allowed}),
            policy_version=self.policy_version,
            reason=reason,
            action="agent.chat",
            obligations={
                "enterprise_facts_require_citations": answer_mode == "enterprise_factual",
                "fail_closed_without_context": answer_mode == "enterprise_factual",
            },
        )

    def authorize_document(
        self,
        *,
        identity: IdentityContext,
        purpose: str,
        metadata: dict[str, Any],
    ) -> PolicyDecision:
        record = self._record_from_metadata(metadata)
        normalized_purpose = purpose.casefold()
        payload = {
            "policy": self.policy_version,
            "authz": identity.authorization_hash(),
            "purpose": normalized_purpose,
            "action": "document.read",
            "document_id": record.document_id,
            "source_version": record.source_version,
            "document_policy_version": record.policy_version,
        }
        allowed = True
        reason = "document access permitted"

        if not record.is_active(datetime.now(timezone.utc)):
            allowed, reason = False, "document is not active"
        elif record.classification > identity.clearance:
            allowed, reason = False, "identity clearance is below document classification"
        elif record.allowed_purposes and normalized_purpose not in record.allowed_purposes:
            allowed, reason = False, "purpose is not allowed for this document"
        elif not record.is_public:
            tenant_allowed = (
                identity.tenant_id == record.tenant_id
                or identity.tenant_id in record.shared_with_tenants
            )
            if not tenant_allowed:
                allowed, reason = False, "cross-tenant access denied"
            elif record.allowed_roles and not set(identity.roles).intersection(
                record.allowed_roles
            ):
                allowed, reason = False, "required role is missing"
            elif record.allowed_departments and not set(identity.departments).intersection(
                record.allowed_departments
            ):
                allowed, reason = False, "required department is missing"

        return PolicyDecision(
            allowed=allowed,
            decision_id=self._decision_id(payload | {"allowed": allowed}),
            policy_version=self.policy_version,
            reason=reason,
            action="document.read",
            resource_id=record.document_id,
            obligations={
                "classification": record.classification.label(),
                "mask_sensitive_values": record.classification >= DataClassification.CONFIDENTIAL,
            },
        )

    def authorize_capability(
        self,
        *,
        identity: IdentityContext,
        purpose: str,
        capability: str,
        tenant_id: str,
        allowed_roles: tuple[str, ...],
        allowed_purposes: tuple[str, ...],
    ) -> PolicyDecision:
        normalized_purpose = purpose.casefold()
        payload = {
            "policy": self.policy_version,
            "authz": identity.authorization_hash(),
            "purpose": normalized_purpose,
            "action": capability,
            "tenant_id": tenant_id,
        }
        allowed = True
        reason = "capability access permitted"
        if identity.tenant_id != tenant_id:
            allowed, reason = False, "cross-tenant capability access denied"
        elif allowed_roles and not set(identity.roles).intersection(
            role.casefold() for role in allowed_roles
        ):
            allowed, reason = False, "required capability role is missing"
        elif allowed_purposes and normalized_purpose not in {
            item.casefold() for item in allowed_purposes
        }:
            allowed, reason = False, "purpose is not allowed for this capability"
        return PolicyDecision(
            allowed=allowed,
            decision_id=self._decision_id(payload | {"allowed": allowed}),
            policy_version=self.policy_version,
            reason=reason,
            action=capability,
            resource_id=tenant_id,
        )

    @staticmethod
    def _record_from_metadata(metadata: dict[str, Any]) -> DocumentPolicyRecord:
        required = {
            "corpus",
            "relative_path",
            "document_id",
            "tenant_id",
            "classification",
            "is_public",
            "source_version",
            "policy_version",
        }
        missing = sorted(required - set(metadata))
        if missing:
            raise ValueError(f"Document security metadata is incomplete: {missing}")
        return DocumentPolicyRecord.model_validate(metadata)
