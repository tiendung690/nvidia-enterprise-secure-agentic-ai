from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from nvidia_agentic_rag.config import Settings


def settings_for(tmp_path, **overrides):
    values = {
        "environment": "test",
        "nvidia_api_key": SecretStr("test-key"),
        "data_dir": tmp_path / "data",
        "course_data_dir": tmp_path / "data/course",
        "papers_data_dir": tmp_path / "data/papers",
        "storage_dir": tmp_path / "storage",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_nvidia_and_enterprise_defaults(tmp_path) -> None:
    settings = settings_for(tmp_path)
    assert settings.nvidia_llm_model == "nvidia/nemotron-3-ultra-550b-a55b"
    assert settings.nvidia_temperature == 0.2
    assert settings.nvidia_max_tokens == 2048
    assert settings.nvidia_reasoning_budget == 768
    assert settings.nvidia_embedding_truncate == "END"
    assert settings.course_rag_top_k == 6
    assert settings.papers_rag_top_k == 5
    assert settings.rag_chunk_size == 256
    assert settings.rag_chunk_overlap == 32
    assert settings.response_cache_ttl_seconds == 1800
    assert settings.agent_max_concurrent_requests == 2
    assert settings.agent_queue_timeout_seconds == 3.0
    assert settings.nvidia_max_retries == 0
    assert settings.nvidia_embedding_max_retries == 1
    assert settings.agent_provider_deadline_seconds == 45.0
    assert settings.model_tier_routing_enabled is True
    assert settings.agent_max_tool_calls == 6
    assert settings.agent_max_same_tool_calls == 1
    assert settings.agent_max_calculator_calls == 3
    assert settings.agent_max_analytics_same_tool_calls == 3
    assert settings.session_concurrency_policy == "reject"
    assert settings.citation_validation_mode == "strict"
    assert settings.citation_minimum_coverage == 0.90
    assert "ollama" not in settings.model_dump()


def test_rejects_invalid_score(tmp_path) -> None:
    with pytest.raises(ValidationError):
        settings_for(tmp_path, papers_rag_min_score=1.1)


def test_rejects_production_auto_ingest(tmp_path) -> None:
    with pytest.raises(ValidationError):
        settings_for(
            tmp_path,
            environment="production",
            auto_ingest=True,
            allow_dev_identity_headers=False,
        )


def test_rejects_same_tool_budget_above_total(tmp_path) -> None:
    with pytest.raises(ValidationError):
        settings_for(tmp_path, agent_max_tool_calls=2, agent_max_same_tool_calls=3)


def test_rejects_specialized_same_tool_budget_above_total(tmp_path) -> None:
    with pytest.raises(ValidationError):
        settings_for(tmp_path, agent_max_tool_calls=2, agent_max_calculator_calls=3)
    with pytest.raises(ValidationError):
        settings_for(tmp_path, agent_max_tool_calls=2, agent_max_analytics_same_tool_calls=3)


def test_rejects_provider_deadline_at_or_above_request_budget(tmp_path) -> None:
    with pytest.raises(ValidationError):
        settings_for(
            tmp_path,
            agent_request_timeout_seconds=45,
            agent_provider_deadline_seconds=45,
        )
    with pytest.raises(ValidationError):
        settings_for(
            tmp_path,
            agent_request_timeout_seconds=30,
            direct_rag_provider_deadline_seconds=30,
        )


def test_rejects_nonpositive_provider_timeouts(tmp_path) -> None:
    with pytest.raises(ValidationError):
        settings_for(tmp_path, nvidia_timeout_seconds=0)
    with pytest.raises(ValidationError):
        settings_for(tmp_path, agent_provider_deadline_seconds=0)
