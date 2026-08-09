from __future__ import annotations

from nvidia_agentic_rag.identity import IdentityContext
from nvidia_agentic_rag.policy import DocumentPolicyRecord, PolicyEngine
from nvidia_agentic_rag.security import DataClassification


def engine() -> PolicyEngine:
    return PolicyEngine(
        policy_version="policy-v1",
        allowed_purposes=("research", "customer-support", "operations-review"),
    )


def record(**overrides) -> DocumentPolicyRecord:
    values = {
        "corpus": "private-docs",
        "relative_path": "policy.pdf",
        "document_id": "doc-1",
        "tenant_id": "tenant-a",
        "classification": "CONFIDENTIAL",
        "is_public": False,
        "allowed_roles": ["architect"],
        "allowed_departments": ["platform"],
        "allowed_purposes": ["research"],
        "source_version": 2,
        "policy_version": "policy-v1",
    }
    values.update(overrides)
    return DocumentPolicyRecord.model_validate(values)


def identity(**overrides) -> IdentityContext:
    values = {
        "user_id": "u1",
        "tenant_id": "tenant-a",
        "roles": ["architect"],
        "departments": ["platform"],
        "clearance": DataClassification.CONFIDENTIAL,
        "authorization_version": "7",
    }
    values.update(overrides)
    return IdentityContext(**values)


def test_query_policy_allows_and_denies_purpose() -> None:
    allowed = engine().authorize_query(
        identity=identity(), purpose="research", answer_mode="enterprise_factual"
    )
    denied = engine().authorize_query(
        identity=identity(), purpose="payroll-export", answer_mode="enterprise_factual"
    )
    assert allowed.allowed
    assert allowed.obligations["fail_closed_without_context"] is True
    assert not denied.allowed
    assert allowed.decision_id != denied.decision_id


def test_document_policy_enforces_tenant_clearance_role_department_and_purpose() -> None:
    policy = engine()
    metadata = record().model_dump(mode="python")
    assert policy.authorize_document(
        identity=identity(), purpose="research", metadata=metadata
    ).allowed
    assert not policy.authorize_document(
        identity=identity(tenant_id="tenant-b"), purpose="research", metadata=metadata
    ).allowed
    assert not policy.authorize_document(
        identity=identity(clearance=DataClassification.INTERNAL),
        purpose="research",
        metadata=metadata,
    ).allowed
    assert not policy.authorize_document(
        identity=identity(roles=["developer"]), purpose="research", metadata=metadata
    ).allowed
    assert not policy.authorize_document(
        identity=identity(departments=["sales"]), purpose="research", metadata=metadata
    ).allowed
    assert not policy.authorize_document(
        identity=identity(), purpose="customer-support", metadata=metadata
    ).allowed


def test_public_document_is_still_classification_limited() -> None:
    public = record(
        tenant_id="public",
        is_public=True,
        classification="PUBLIC",
        allowed_roles=[],
        allowed_departments=[],
    )
    assert engine().authorize_document(
        identity=IdentityContext.anonymous_public(),
        purpose="research",
        metadata=public.model_dump(mode="python"),
    ).allowed


def test_shared_tenant_and_capability_policy() -> None:
    shared = record(shared_with_tenants=["tenant-b"])
    assert engine().authorize_document(
        identity=identity(tenant_id="tenant-b"),
        purpose="research",
        metadata=shared.model_dump(mode="python"),
    ).allowed

    capability = engine().authorize_capability(
        identity=identity(roles=["support"]),
        purpose="customer-support",
        capability="orders.read",
        tenant_id="tenant-a",
        allowed_roles=("support",),
        allowed_purposes=("customer-support",),
    )
    assert capability.allowed
    assert not engine().authorize_capability(
        identity=identity(tenant_id="tenant-b", roles=["support"]),
        purpose="customer-support",
        capability="orders.read",
        tenant_id="tenant-a",
        allowed_roles=("support",),
        allowed_purposes=("customer-support",),
    ).allowed


def test_record_lifecycle_and_metadata() -> None:
    active = record()
    assert active.is_active()
    metadata = active.metadata()
    assert metadata["classification"] == "confidential"
    expired = record(expires_at="2020-01-01T00:00:00Z")
    assert not expired.is_active()
