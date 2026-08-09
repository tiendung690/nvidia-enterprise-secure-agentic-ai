from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ModelTier = Literal["fast", "complex"]


@dataclass(frozen=True)
class TierDecision:
    """Deterministic routing decision produced before any provider call."""

    tier: ModelTier
    reason: str


class ModelGateway:
    """Single choke point that maps work to a model tier (ADR-018).

    The gateway owns two provider clients that share the same OpenAI-compatible
    NVIDIA endpoint: a ``complex`` tier (the reasoning model used by the agent
    lane and non-trivial synthesis) and a ``fast`` synthesis tier/profile. The
    fast profile may use a smaller model, or the same model with thinking disabled
    and a tighter token cap when no alternate model is configured. Routing is deterministic and
    auditable; the LLM never chooses its own tier.

    Degrade-to-fast is a resilience policy, not a routing policy: when the
    complex path is unhealthy (circuit open or retries exhausted on transient
    errors) the caller may ask for a one-shot downgrade instead of failing the
    request outright.
    """

    def __init__(
        self,
        *,
        complex_llm: Any,
        fast_llm: Any | None = None,
        routing_enabled: bool = False,
        degrade_to_fast: bool = True,
        fast_is_distinct_backend: bool = True,
    ) -> None:
        self._complex_llm = complex_llm
        self._fast_llm = fast_llm
        self.routing_enabled = routing_enabled and fast_llm is not None
        self.degrade_to_fast = degrade_to_fast and fast_llm is not None
        self.fast_is_distinct_backend = fast_is_distinct_backend and fast_llm is not None

    @property
    def fast_available(self) -> bool:
        return self._fast_llm is not None

    def select_tier(
        self, *, route_kind: str, complexity: str, corpus_count: int = 1
    ) -> TierDecision:
        """Choose a tier for one unit of synthesis work.

        Single-corpus ``direct_rag`` synthesis is eligible for the fast tier for
        simple and comparison queries. Multi-corpus/long synthesis and the agent
        lane keep the complex model; deterministic routes never reach a provider.
        """
        if not self.routing_enabled:
            return TierDecision(tier="complex", reason="tier-routing-disabled")
        if (
            route_kind == "direct_rag"
            and corpus_count <= 1
            and complexity in {"simple", "comparison"}
        ):
            return TierDecision(
                tier="fast",
                reason=f"single-corpus-{complexity}-direct-synthesis",
            )
        return TierDecision(tier="complex", reason=f"{route_kind}-{complexity}")

    def llm_for(self, tier: ModelTier) -> Any:
        if tier == "fast" and self._fast_llm is not None:
            return self._fast_llm
        return self._complex_llm

    def degraded(self, current: ModelTier) -> tuple[Any, ModelTier] | None:
        """Return the fast client when a one-shot downgrade is permitted."""
        if not self.degrade_to_fast:
            return None
        if current != "complex" or self._fast_llm is None:
            return None
        return self._fast_llm, "fast"


__all__ = ["ModelGateway", "ModelTier", "TierDecision"]
