from __future__ import annotations

from dataclasses import dataclass

from nvidia_agentic_rag.identity import IdentityContext
from nvidia_agentic_rag.memory.models import (
    MemoryCandidate,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    PromotionDecision,
    ProvenanceKind,
)
from nvidia_agentic_rag.memory.repository import MemoryRepository
from nvidia_agentic_rag.safety import inspect_prompt, inspect_untrusted_content


@dataclass(frozen=True)
class PromotionPolicy:
    fact_confidence_threshold: float = 0.70
    preference_confidence_threshold: float = 0.50
    tenant_fact_minimum_sources: int = 2
    inferred_memory_is_provisional: bool = True
    maximum_content_chars: int = 8000


class MemoryPromotionGate:
    """Server-side write validation. The caller never controls active status."""

    def __init__(self, repository: MemoryRepository, policy: PromotionPolicy | None = None) -> None:
        self.repository = repository
        self.policy = policy or PromotionPolicy()

    def evaluate(
        self, candidate: MemoryCandidate, *, identity: IdentityContext
    ) -> tuple[bool, MemoryScope, MemoryStatus, str]:
        if len(candidate.content) > self.policy.maximum_content_chars:
            return False, MemoryScope.USER, MemoryStatus.REJECTED, "content exceeds limit"
        if candidate.effective_until and candidate.effective_from:
            if candidate.effective_until <= candidate.effective_from:
                return (
                    False,
                    MemoryScope.USER,
                    MemoryStatus.REJECTED,
                    "effective_until must be after effective_from",
                )

        if candidate.memory_type != MemoryType.POLICY:
            untrusted_text = " ".join(
                filter(
                    None,
                    (
                        candidate.subject,
                        candidate.predicate,
                        candidate.value,
                        candidate.content,
                    ),
                )
            )
            signals = set(inspect_prompt(untrusted_text).signals)
            signals.update(inspect_untrusted_content(untrusted_text).signals)
            if signals:
                return (
                    False,
                    MemoryScope.USER,
                    MemoryStatus.REJECTED,
                    "memory content contains instruction-injection signals: "
                    + ", ".join(sorted(signals)),
                )

        if candidate.memory_type == MemoryType.POLICY:
            if (
                candidate.provenance != ProvenanceKind.ADMIN_CONFIGURED
                or "memory-admin" not in identity.roles
            ):
                return (
                    False,
                    MemoryScope.TENANT,
                    MemoryStatus.REJECTED,
                    "policy memory is deployment/admin controlled and never auto-promoted",
                )
            if candidate.requested_scope == MemoryScope.GLOBAL:
                return (
                    False,
                    MemoryScope.TENANT,
                    MemoryStatus.REJECTED,
                    "global policy publication is deployment-controlled, not API-controlled",
                )
            return (
                True,
                MemoryScope.TENANT,
                MemoryStatus.ACTIVE,
                "verified tenant policy publication",
            )

        if candidate.memory_type == MemoryType.PREFERENCE:
            if candidate.provenance not in {
                ProvenanceKind.USER_STATED,
                ProvenanceKind.ADMIN_CONFIGURED,
            }:
                return (
                    False,
                    MemoryScope.USER,
                    MemoryStatus.REJECTED,
                    "preferences require explicit user/admin provenance",
                )
            if candidate.confidence < self.policy.preference_confidence_threshold:
                return (
                    False,
                    MemoryScope.USER,
                    MemoryStatus.REJECTED,
                    "preference confidence is below threshold",
                )
            return True, MemoryScope.USER, MemoryStatus.ACTIVE, "explicit user preference"

        if candidate.memory_type == MemoryType.FACT:
            if not candidate.source_run_id:
                return (
                    False,
                    MemoryScope.USER,
                    MemoryStatus.REJECTED,
                    "fact memory requires source_run_id",
                )
            if candidate.confidence < self.policy.fact_confidence_threshold:
                return (
                    False,
                    MemoryScope.USER,
                    MemoryStatus.REJECTED,
                    "fact confidence is below threshold",
                )
            final_scope = MemoryScope.USER
            if candidate.requested_scope == MemoryScope.TENANT:
                tenant_entity = candidate.metadata.get("subject_kind") == "tenant_entity"
                if not tenant_entity:
                    return (
                        False,
                        MemoryScope.USER,
                        MemoryStatus.REJECTED,
                        "tenant fact requires a tenant entity subject",
                    )
                if len(set(candidate.source_ids)) < self.policy.tenant_fact_minimum_sources:
                    return (
                        False,
                        MemoryScope.USER,
                        MemoryStatus.REJECTED,
                        "tenant fact requires independent supporting sources",
                    )
                final_scope = MemoryScope.TENANT
            elif candidate.requested_scope == MemoryScope.GLOBAL:
                return (
                    False,
                    MemoryScope.USER,
                    MemoryStatus.REJECTED,
                    "global facts require administrative publication",
                )
            status = (
                MemoryStatus.PROVISIONAL
                if candidate.provenance == ProvenanceKind.MODEL_INFERRED
                and self.policy.inferred_memory_is_provisional
                else MemoryStatus.ACTIVE
            )
            return True, final_scope, status, "fact passed provenance and scope checks"

        if candidate.memory_type == MemoryType.EPISODIC:
            if not candidate.task_completed or not candidate.source_run_id:
                return (
                    False,
                    MemoryScope.USER,
                    MemoryStatus.REJECTED,
                    "episodic memory requires a completed task and source run",
                )
            if candidate.requested_scope == MemoryScope.GLOBAL:
                return (
                    False,
                    MemoryScope.USER,
                    MemoryStatus.REJECTED,
                    "episodes cannot be global",
                )
            final_scope = (
                MemoryScope.TENANT
                if candidate.requested_scope == MemoryScope.TENANT
                and "memory-admin" in identity.roles
                else MemoryScope.USER
            )
            return True, final_scope, MemoryStatus.ACTIVE, "completed task episode"

        return (
            False,
            MemoryScope.USER,
            MemoryStatus.REJECTED,
            "trace records use the append-only trace service, not the promotion gate",
        )

    def promote(
        self, candidate: MemoryCandidate, *, identity: IdentityContext
    ) -> PromotionDecision:
        accepted, final_scope, status, reason = self.evaluate(candidate, identity=identity)
        if not accepted:
            return PromotionDecision(
                accepted=False,
                final_scope=final_scope,
                status=status,
                reason=reason,
            )
        record, deduplicated, superseded = self.repository.promote(
            candidate=candidate,
            identity=identity,
            final_scope=final_scope,
            status=status,
        )
        return PromotionDecision(
            accepted=True,
            final_scope=final_scope,
            status=record.status,
            reason=reason,
            memory_id=record.memory_id,
            deduplicated=deduplicated,
            superseded_memory_id=superseded,
        )
