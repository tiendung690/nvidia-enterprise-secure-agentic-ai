from __future__ import annotations

from nvidia_agentic_rag.context import SecureContextBroker
from nvidia_agentic_rag.identity import IdentityContext, RequestSecurityContext
from nvidia_agentic_rag.policy import PolicyEngine
from nvidia_agentic_rag.security import DataClassification, DataMasker


class Node:
    def __init__(self, metadata, text):
        self.metadata = metadata
        self._text = text

    def get_content(self):
        return self._text


class Candidate:
    def __init__(self, metadata, text, score=0.9):
        self.node = Node(metadata, text)
        self.score = score


def metadata(tenant="tenant-a", classification="CONFIDENTIAL"):
    return {
        "corpus": "private",
        "relative_path": "a.pdf",
        "document_id": "doc-a",
        "tenant_id": tenant,
        "classification": classification,
        "is_public": False,
        "allowed_roles": ["architect"],
        "allowed_departments": ["platform"],
        "allowed_purposes": ["research"],
        "shared_with_tenants": [],
        "source_version": 1,
        "policy_version": "policy-v1",
    }


def scope(tenant="tenant-a"):
    return RequestSecurityContext(
        identity=IdentityContext(
            user_id="u",
            tenant_id=tenant,
            roles=["architect"],
            departments=["platform"],
            clearance=DataClassification.CONFIDENTIAL,
        ),
        purpose="research",
        answer_mode="enterprise_factual",
        request_id="r1",
        policy_decision_id="pd1",
    )


def test_context_broker_security_trims_and_masks_before_llm() -> None:
    broker = SecureContextBroker(
        policy_engine=PolicyEngine(
            policy_version="policy-v1", allowed_purposes=("research",)
        ),
        masker=DataMasker(mode="pseudonymize", salt="salt"),
    )
    result = broker.authorize_candidates(
        candidates=[
            Candidate(metadata(), "Contact a@example.com"),
            Candidate(metadata(tenant="tenant-b"), "Secret from tenant B"),
        ],
        request_context=scope(),
        limit=5,
    )
    assert len(result.authorized) == 1
    assert result.denied_candidate_count == 1
    assert "a@example.com" not in result.authorized[0].masked_text
    assert result.authorized[0].masked


def test_context_broker_limit() -> None:
    broker = SecureContextBroker(
        policy_engine=PolicyEngine(
            policy_version="policy-v1", allowed_purposes=("research",)
        ),
        masker=DataMasker(mode="off", salt="salt"),
    )
    result = broker.authorize_candidates(
        candidates=[Candidate(metadata(), "one"), Candidate(metadata(), "two")],
        request_context=scope(),
        limit=1,
    )
    assert len(result.authorized) == 1
