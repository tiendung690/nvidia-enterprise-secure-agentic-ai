from __future__ import annotations

import json
from datetime import datetime, timezone

from nvidia_agentic_rag.data.operational import OrderRecord
from nvidia_agentic_rag.identity import (
    IdentityContext,
    RequestSecurityContext,
    request_security_scope,
)
from nvidia_agentic_rag.policy import PolicyEngine
from nvidia_agentic_rag.security import DataClassification, DataMasker
from nvidia_agentic_rag.tools import SecureOperationalTools


class Repository:
    def get_order(self, *, tenant_id: str, order_id: str):
        if tenant_id == "tenant-a" and order_id == "ABC-123":
            return OrderRecord(
                order_id=order_id,
                tenant_id=tenant_id,
                status="Delivered",
                customer_reference="customer@example.com",
                record_version=2,
                updated_at=datetime.now(timezone.utc),
            )
        return None


def scope(*, roles=("support",), tenant="tenant-a", purpose="customer-support"):
    return RequestSecurityContext(
        identity=IdentityContext(
            user_id="u",
            tenant_id=tenant,
            roles=roles,
            clearance=DataClassification.CONFIDENTIAL,
        ),
        purpose=purpose,
        answer_mode="enterprise_factual",
        request_id="r",
        policy_decision_id="pd",
    )


def tools() -> SecureOperationalTools:
    return SecureOperationalTools(
        order_repository=Repository(),
        policy_engine=PolicyEngine(
            policy_version="p1",
            allowed_purposes=("customer-support", "operations-review"),
        ),
        masker=DataMasker(mode="pseudonymize", salt="s"),
    )


def test_authorized_order_tool_returns_typed_database_source() -> None:
    with request_security_scope(scope()):
        payload = json.loads(tools().get_order_status("ABC-123"))
    assert payload["status"] == "success"
    assert payload["sources"][0]["citation_id"].startswith("D")
    assert payload["sources"][0]["source_kind"] == "database"
    assert "customer@example.com" not in payload["observation"]["customer_reference"]


def test_order_tool_denies_role_and_hides_cross_tenant_records() -> None:
    with request_security_scope(scope(roles=("developer",))):
        denied = json.loads(tools().get_order_status("ABC-123"))
    assert denied["status"] == "policy_denied"

    with request_security_scope(scope(tenant="tenant-b")):
        not_found = json.loads(tools().get_order_status("ABC-123"))
    assert not_found["status"] == "not_found"
