from __future__ import annotations

from typing import Any

from nvidia_agentic_rag.context.models import ContextBrokerResult, SecureCandidate
from nvidia_agentic_rag.identity.context import RequestSecurityContext
from nvidia_agentic_rag.policy.engine import PolicyEngine
from nvidia_agentic_rag.security.masking import DataMasker


class SecureContextBroker:
    """Security-trims retrieved candidates before any text is exposed to the LLM."""

    def __init__(self, *, policy_engine: PolicyEngine, masker: DataMasker) -> None:
        self.policy_engine = policy_engine
        self.masker = masker

    def authorize_candidates(
        self,
        *,
        candidates: list[Any],
        request_context: RequestSecurityContext,
        limit: int,
    ) -> ContextBrokerResult:
        authorized: list[SecureCandidate] = []
        denied = 0
        for item in candidates:
            metadata = dict(item.node.metadata or {})
            decision = self.policy_engine.authorize_document(
                identity=request_context.identity,
                purpose=request_context.purpose,
                metadata=metadata,
            )
            if not decision.allowed:
                denied += 1
                continue

            text = item.node.get_content()
            masking = self.masker.apply(text)
            authorized.append(
                SecureCandidate(
                    node_with_score=item,
                    decision_id=decision.decision_id,
                    classification=str(metadata.get("classification", "unknown")),
                    masked_text=masking.text,
                    masked=masking.masked,
                    dlp_signals=masking.signals,
                )
            )
            if len(authorized) >= limit:
                break
        return ContextBrokerResult(
            authorized=tuple(authorized),
            denied_candidate_count=denied,
            policy_version=self.policy_engine.policy_version,
        )
