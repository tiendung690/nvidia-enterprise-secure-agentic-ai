from __future__ import annotations

import json
from datetime import datetime, timezone

from nvidia_agentic_rag.data.operational import OrderRepository
from nvidia_agentic_rag.identity import get_request_security_context
from nvidia_agentic_rag.policy import PolicyEngine
from nvidia_agentic_rag.rag.provenance import deterministic_citation_id
from nvidia_agentic_rag.schemas import SourceReference
from nvidia_agentic_rag.security import DataMasker


class SecureOperationalTools:
    """Bounded typed capabilities over operational data; no arbitrary SQL is exposed to the LLM."""

    def __init__(
        self,
        *,
        order_repository: OrderRepository,
        policy_engine: PolicyEngine,
        masker: DataMasker,
    ) -> None:
        self.order_repository = order_repository
        self.policy_engine = policy_engine
        self.masker = masker

    def get_order_status(self, order_id: str) -> str:
        """Get one authorized order status by exact order ID for support/operations purposes."""
        scope = get_request_security_context()
        order_id = order_id.strip()
        if not order_id or len(order_id) > 128:
            raise ValueError("order_id must be between 1 and 128 characters")

        decision = self.policy_engine.authorize_capability(
            identity=scope.identity,
            purpose=scope.purpose,
            capability="orders.read",
            tenant_id=scope.identity.tenant_id,
            allowed_roles=("support", "operations", "admin"),
            allowed_purposes=("customer-support", "operations-review"),
        )
        if not decision.allowed:
            return json.dumps(
                {
                    "status": "policy_denied",
                    "reason": decision.reason,
                    "sources": [],
                    "policy_audit": {
                        "status": "denied",
                        "decision_id": decision.decision_id,
                        "policy_version": decision.policy_version,
                        "purpose": scope.purpose,
                        "tenant_id": scope.identity.tenant_id,
                        "reason": decision.reason,
                    },
                }
            )

        record = self.order_repository.get_order(
            tenant_id=scope.identity.tenant_id,
            order_id=order_id,
        )
        if record is None:
            return json.dumps(
                {
                    "status": "not_found",
                    "message": "No authorized order matched the supplied ID.",
                    "sources": [],
                    "policy_audit": {
                        "status": "insufficient_context",
                        "decision_id": decision.decision_id,
                        "policy_version": decision.policy_version,
                        "purpose": scope.purpose,
                        "tenant_id": scope.identity.tenant_id,
                    },
                }
            )

        customer_reference = record.customer_reference or ""
        masked_customer = self.masker.apply(customer_reference).text if customer_reference else None
        source_id = (
            f"db:operational_order:{record.tenant_id}:{record.order_id}:v{record.record_version}"
        )
        citation_id = deterministic_citation_id(source_id, prefix="D")
        observation = {
            "order_id": record.order_id,
            "status": record.status,
            "delivered_at": record.delivered_at.isoformat() if record.delivered_at else None,
            "product_category": record.product_category,
            "customer_reference": masked_customer,
            "record_version": record.record_version,
            "updated_at": record.updated_at.isoformat(),
        }
        source = SourceReference(
            citation_id=citation_id,
            source_id=source_id,
            source_kind="database",
            corpus="operational-database",
            file_name="operational_order",
            title=f"Order {record.order_id}",
            excerpt=json.dumps(observation, ensure_ascii=False),
            tenant_id=record.tenant_id,
            document_id=record.order_id,
            classification="confidential",
            source_version=record.record_version,
            policy_version=decision.policy_version,
            authorization_decision_id=decision.decision_id,
            masked=masked_customer != customer_reference if customer_reference else False,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
        )
        return json.dumps(
            {
                "status": "success",
                "observation": observation,
                "evidence": f"[{citation_id}] Authorized database observation: "
                f"{json.dumps(observation, ensure_ascii=False)}",
                "sources": [source.model_dump(mode="json")],
                "safety_signals": [],
                "policy_audit": {
                    "status": "allowed",
                    "decision_id": decision.decision_id,
                    "policy_version": decision.policy_version,
                    "purpose": scope.purpose,
                    "tenant_id": scope.identity.tenant_id,
                    "authorized_source_count": 1,
                    "classifications": ["confidential"],
                },
            },
            ensure_ascii=False,
        )
