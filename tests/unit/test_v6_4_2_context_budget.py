from __future__ import annotations

import pytest

from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.nvidia.errors import classify_provider_error
from nvidia_agentic_rag.routing import classify_route


def settings(**overrides: object) -> Settings:
    return Settings(environment="test", **overrides)


def test_nemotron_ultra_stale_million_token_env_is_capped() -> None:
    cfg = settings(nvidia_context_window=1_000_000)

    assert cfg.provider_context_limit(cfg.nvidia_llm_model) == 258_048
    assert cfg.effective_llm_context_window(
        model=cfg.nvidia_llm_model,
        max_tokens=cfg.nvidia_max_tokens,
    ) == 249_856


def test_context_safety_reserves_provider_headroom() -> None:
    cfg = settings(
        nvidia_context_window=258_048,
        nvidia_context_safety_tokens=8_192,
        nvidia_max_tokens=2_048,
    )

    effective = cfg.effective_llm_context_window(
        model=cfg.nvidia_llm_model,
        max_tokens=cfg.nvidia_max_tokens,
    )
    assert effective + cfg.nvidia_context_safety_tokens == 258_048
    assert effective + cfg.nvidia_max_tokens < 258_048


def test_legacy_workflow_context_is_rejected() -> None:
    with pytest.raises(ValueError, match="legacy is no longer supported"):
        settings(conversation_context_mode="legacy")


def test_context_overflow_is_not_classified_as_capacity() -> None:
    class BadRequestError(RuntimeError):
        status_code = 400

    exc = BadRequestError(
        "The combined prompt length (258459) and max_new_tokens (2048) "
        "exceeds the max context length (258048)."
    )
    info = classify_provider_error(exc)

    assert info.error_code == "NVIDIA_CONTEXT_LENGTH_EXCEEDED"
    assert info.transient is False
    assert info.status_code == 400


def test_internal_strategy_summary_routes_to_bounded_knowledge_rag() -> None:
    route = classify_route(
        "Summarize our strategy for GPU-accelerated training and related bottlenecks."
    )

    assert route.kind == "direct_rag"
    assert route.tool_names == (
        "agentic_rag_course_tool",
        "research_paper_rag_tool",
    )
    assert route.requires_enterprise_evidence is True
