from __future__ import annotations

from nvidia_agentic_rag.gateway import ModelGateway


class _FakeLLM:
    def __init__(self, name: str) -> None:
        self.name = name


COMPLEX = _FakeLLM("complex")
FAST = _FakeLLM("fast")


def test_routing_disabled_always_selects_complex() -> None:
    gateway = ModelGateway(complex_llm=COMPLEX, fast_llm=FAST, routing_enabled=False)
    decision = gateway.select_tier(route_kind="direct_rag", complexity="simple")
    assert decision.tier == "complex"
    assert decision.reason == "tier-routing-disabled"
    assert gateway.llm_for(decision.tier) is COMPLEX


def test_routing_without_fast_client_stays_complex() -> None:
    gateway = ModelGateway(complex_llm=COMPLEX, fast_llm=None, routing_enabled=True)
    assert gateway.routing_enabled is False
    assert gateway.fast_available is False
    decision = gateway.select_tier(route_kind="direct_rag", complexity="simple")
    assert decision.tier == "complex"


def test_simple_direct_rag_routes_to_fast_tier() -> None:
    gateway = ModelGateway(complex_llm=COMPLEX, fast_llm=FAST, routing_enabled=True)
    decision = gateway.select_tier(route_kind="direct_rag", complexity="simple")
    assert decision.tier == "fast"
    assert gateway.llm_for("fast") is FAST


def test_single_corpus_comparison_routes_fast_but_multi_corpus_and_agent_stay_complex() -> None:
    gateway = ModelGateway(complex_llm=COMPLEX, fast_llm=FAST, routing_enabled=True)
    assert (
        gateway.select_tier(
            route_kind="direct_rag", complexity="comparison", corpus_count=1
        ).tier
        == "fast"
    )
    assert (
        gateway.select_tier(
            route_kind="direct_rag", complexity="comparison", corpus_count=2
        ).tier
        == "complex"
    )
    assert gateway.select_tier(route_kind="agent", complexity="simple").tier == "complex"


def test_degrade_returns_fast_pair_only_from_complex_once() -> None:
    gateway = ModelGateway(
        complex_llm=COMPLEX, fast_llm=FAST, routing_enabled=False, degrade_to_fast=True
    )
    pair = gateway.degraded("complex")
    assert pair is not None
    llm, tier = pair
    assert llm is FAST
    assert tier == "fast"
    assert gateway.degraded("fast") is None


def test_degrade_disabled_or_unavailable_returns_none() -> None:
    assert (
        ModelGateway(
            complex_llm=COMPLEX, fast_llm=FAST, degrade_to_fast=False
        ).degraded("complex")
        is None
    )
    assert (
        ModelGateway(
            complex_llm=COMPLEX, fast_llm=None, degrade_to_fast=True
        ).degraded("complex")
        is None
    )
