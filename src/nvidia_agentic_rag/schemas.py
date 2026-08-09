from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from nvidia_agentic_rag.policy.models import PolicyAudit

RequestOutcome = Literal[
    "success",
    "cache_hit",
    "blocked",
    "policy_denied",
    "insufficient_context",
    "citation_validation_failed",
    "answer_validation_failed",
    "capacity_rejected",
    "session_busy",
    "provider_unavailable",
    "execution_timeout",
    "output_blocked",
    "error",
]

EvidenceOrigin = Literal[
    "fresh_generation",
    "fresh_retrieval",
    "live_lakehouse_tool",
    "rag_vector_retrieval",
    "model_or_session_memory",
    "cached_retrieval_answer",
    "cached_lakehouse_answer",
    "blocked",
    "policy_denied",
    "insufficient_authorized_context",
    "citation_validation_failed",
    "answer_validation_failed",
    "provider_unavailable",
    "capacity_rejected",
    "session_busy",
    "execution_timeout",
]

SafetyStatus = Literal["passed", "blocked", "not_evaluated"]
CircuitState = Literal["closed", "open", "half_open", "disabled"]
ExecutionMode = Literal["deterministic", "provider", "not_used"]


class SourceReference(BaseModel):
    """Stable API-safe provenance for a document chunk or typed data observation."""

    citation_id: str = Field(pattern=r"^[SD][A-F0-9]{6}$")
    source_id: str = Field(min_length=1, max_length=512)
    source_kind: Literal["document", "database", "semantic", "external"] = "document"
    corpus: str = Field(min_length=1, max_length=128)
    file_name: str = Field(min_length=1, max_length=512)
    title: str | None = Field(default=None, max_length=512)
    page: str | int | None = None
    section: str | None = Field(default=None, max_length=512)
    chunk_index: int | None = Field(default=None, ge=0)
    score: float | None = Field(default=None, ge=-1.0, le=1.0)
    excerpt: str = Field(default="", max_length=2400)
    indirect_injection_signals: list[str] = Field(default_factory=list)

    tenant_id: str | None = Field(default=None, max_length=128)
    document_id: str | None = Field(default=None, max_length=256)
    classification: str | None = Field(default=None, max_length=64)
    source_version: int | None = Field(default=None, ge=1)
    data_version: str | None = Field(default=None, max_length=128)
    policy_version: str | None = Field(default=None, max_length=128)
    authorization_decision_id: str | None = Field(default=None, max_length=128)
    masked: bool = False
    # ``retrieved_at`` is retained for API compatibility; new telemetry separates source time
    # from the time the current request read the source.
    retrieved_at: str | None = Field(default=None, max_length=64)
    source_as_of: str | None = Field(default=None, max_length=64)
    tool_retrieved_at: str | None = Field(default=None, max_length=64)

    @field_validator("excerpt", mode="before")
    @classmethod
    def normalize_excerpt(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:2400]


class ToolTrace(BaseModel):
    tool: str
    status: Literal["completed", "failed", "discarded_retry"] = "completed"
    duration_ms: float = Field(ge=0)


class MemoryAudit(BaseModel):
    enabled: bool = False
    version: str = "disabled"
    exact_record_count: int = Field(default=0, ge=0)
    semantic_record_count: int = Field(default=0, ge=0)
    write_candidate_count: int = Field(default=0, ge=0)
    write_accepted_count: int = Field(default=0, ge=0)


class RetrievalTrace(BaseModel):
    strategy: str = "identity"
    query_variant_count: int = Field(default=0, ge=0)
    query_variant_hashes: list[str] = Field(default_factory=list)
    mode: str = "vector"
    degraded: bool = False
    relevance: str = "none"
    top_score: float = 0.0
    query_coverage: float = 0.0
    fallback_chain: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class CitationAudit(BaseModel):
    """Deterministic citation postcondition for one response."""

    applicable: bool = True
    valid: bool = True
    used_ids: list[str] = Field(default_factory=list)
    available_ids: list[str] = Field(default_factory=list)
    unknown_ids: list[str] = Field(default_factory=list)
    coverage: float | None = Field(default=1.0, ge=0.0, le=1.0)
    claim_count: int = Field(default=0, ge=0)
    cited_claim_count: int = Field(default=0, ge=0)
    repair_attempted: bool = False
    removed_claim_count: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)


class AnswerCompletenessAudit(BaseModel):
    """Business-structure postcondition kept separate from citation coverage.

    Citation coverage can be 100% after a conservative repair deletes rows. This gate tracks
    the structure the capability promised and therefore prevents a syntactically grounded but
    semantically empty analytical answer from being returned or cached.
    """

    applicable: bool = False
    valid: bool = True
    expected_entities: int = Field(default=0, ge=0)
    generated_entities: int = Field(default=0, ge=0)
    validated_entities: int = Field(default=0, ge=0)
    removed_entities: int = Field(default=0, ge=0)
    ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    structure: str | None = Field(default=None, max_length=64)
    errors: list[str] = Field(default_factory=list)


class ProvenanceDerivation(BaseModel):
    """Application-owned lineage for a deterministic derived metric."""

    output_name: str = Field(min_length=1, max_length=128)
    formula_id: str = Field(min_length=1, max_length=160)
    formula: str = Field(min_length=1, max_length=256)
    inputs: dict[str, Any] = Field(default_factory=dict)
    source_citation_ids: list[str] = Field(default_factory=list)
    value: Any = None




class ProvenanceAudit(BaseModel):
    """Validation result for application-owned derived-metric lineage."""

    applicable: bool = False
    valid: bool = True
    derivation_count: int = Field(default=0, ge=0)
    validated_count: int = Field(default=0, ge=0)
    unknown_citation_ids: list[str] = Field(default_factory=list)
    invalid_formula_ids: list[str] = Field(default_factory=list)
    mismatched_outputs: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class SafetyAudit(BaseModel):
    status: SafetyStatus = "not_evaluated"
    signals: list[str] = Field(default_factory=list)
    reason: str = ""


class LatencyBreakdown(BaseModel):
    # Fractional milliseconds avoid the misleading ``0 ms`` telemetry seen for controls that
    # executed in hundreds of microseconds.
    authorization_ms: float = Field(default=0.0, ge=0)
    prompt_guard_ms: float = Field(default=0.0, ge=0)
    cache_lookup_ms: float = Field(default=0.0, ge=0)
    memory_read_ms: float = Field(default=0.0, ge=0)
    memory_write_ms: float = Field(default=0.0, ge=0)
    conversation_assembly_ms: float = Field(default=0.0, ge=0)
    session_wait_ms: float = Field(default=0.0, ge=0)
    capacity_wait_ms: float = Field(default=0.0, ge=0)
    execution_ms: float = Field(default=0.0, ge=0)
    tool_ms: float = Field(default=0.0, ge=0)
    provider_ms: float = Field(default=0.0, ge=0)
    provider_backoff_ms: float = Field(default=0.0, ge=0)
    output_dlp_ms: float = Field(default=0.0, ge=0)
    citation_validation_ms: float = Field(default=0.0, ge=0)
    citation_repair_ms: float = Field(default=0.0, ge=0)
    provenance_validation_ms: float = Field(default=0.0, ge=0)
    answer_completeness_ms: float = Field(default=0.0, ge=0)
    total_ms: float = Field(default=0.0, ge=0)


class ProviderTrace(BaseModel):
    invoked: bool = False
    execution_mode: ExecutionMode = "not_used"
    provider: str | None = None
    attempts: int = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    transient_failures: int = Field(default=0, ge=0)
    total_backoff_ms: float = Field(default=0.0, ge=0)
    circuit_state: CircuitState = "disabled"
    last_error_code: str | None = None
    model_tier: Literal["fast", "complex", "not_used"] = "not_used"
    degraded_to_fast: bool = False


__all__ = [
    "AnswerCompletenessAudit",
    "CircuitState",
    "CitationAudit",
    "EvidenceOrigin",
    "ExecutionMode",
    "LatencyBreakdown",
    "MemoryAudit",
    "PolicyAudit",
    "ProvenanceAudit",
    "ProvenanceDerivation",
    "ProviderTrace",
    "RequestOutcome",
    "RetrievalTrace",
    "SafetyAudit",
    "SafetyStatus",
    "SourceReference",
    "ToolTrace",
]
