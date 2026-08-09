from __future__ import annotations

import asyncio

import pytest
from pydantic import SecretStr

from nvidia_agentic_rag.agents.service import AgentService
from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.gateway import ModelGateway
from nvidia_agentic_rag.runtime import ProviderUnavailableError


class _LLM:
    def __init__(self, *, fail: str | None = None, delay: float = 0.0) -> None:
        self.fail = fail
        self.delay = delay
        self.calls = 0

    async def acomplete(self, prompt: str) -> str:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError(self.fail)
        return "Grounded answer [SABC123]"


def _settings(tmp_path, **overrides) -> Settings:
    values = {
        "environment": "test",
        "nvidia_api_key": SecretStr("test-key"),
        "data_dir": tmp_path / "data",
        "course_data_dir": tmp_path / "data/course",
        "papers_data_dir": tmp_path / "data/papers",
        "storage_dir": tmp_path / "storage",
        "provider_retry_base_seconds": 0.001,
        "provider_retry_max_seconds": 0.001,
        "provider_retry_jitter": False,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_fast_capacity_failure_does_not_retry_storm(tmp_path) -> None:
    fast = _LLM(fail="503 capacity exhausted")
    complex_llm = _LLM()
    service = AgentService(
        _settings(tmp_path, provider_retry_max_attempts=2),
        object(),
        lambda: "v1",
        llm=complex_llm,
        model_gateway=ModelGateway(
            complex_llm=complex_llm, fast_llm=fast, routing_enabled=True
        ),
    )
    with pytest.raises(ProviderUnavailableError) as captured:
        await service._run_direct_synthesis_with_resilience(
            prompt="q",
            provider_trace=service_result_trace(),
            breakdown=service_breakdown(),
            tier="fast",
        )
    assert captured.value.error_code == "NVIDIA_CAPACITY_EXHAUSTED"
    assert fast.calls == 1


@pytest.mark.asyncio
async def test_complex_capacity_failure_degrades_before_same_tier_retry(tmp_path) -> None:
    complex_llm = _LLM(fail="503 capacity exhausted")
    fast = _LLM()
    service = AgentService(
        _settings(tmp_path, provider_retry_max_attempts=2),
        object(),
        lambda: "v1",
        llm=complex_llm,
        model_gateway=ModelGateway(
            complex_llm=complex_llm, fast_llm=fast, routing_enabled=True
        ),
    )
    trace = service_result_trace()
    answer = await service._run_direct_synthesis_with_resilience(
        prompt="q", provider_trace=trace, breakdown=service_breakdown(), tier="complex"
    )
    assert "Grounded answer" in answer
    assert complex_llm.calls == 1
    assert fast.calls == 1
    assert trace.degraded_to_fast is True


@pytest.mark.asyncio
async def test_direct_synthesis_has_total_deadline(tmp_path) -> None:
    fast = _LLM(delay=0.05)
    service = AgentService(
        _settings(
            tmp_path,
            direct_rag_provider_deadline_seconds=0.01,
            provider_retry_max_attempts=2,
        ),
        object(),
        lambda: "v1",
        llm=fast,
        model_gateway=ModelGateway(complex_llm=fast, fast_llm=fast, routing_enabled=True),
    )
    with pytest.raises(ProviderUnavailableError) as captured:
        await service._run_direct_synthesis_with_resilience(
            prompt="q",
            provider_trace=service_result_trace(),
            breakdown=service_breakdown(),
            tier="fast",
        )
    assert captured.value.error_code == "NVIDIA_PROVIDER_DEADLINE_EXCEEDED"
    assert fast.calls == 1


def service_result_trace():
    from nvidia_agentic_rag.schemas import ProviderTrace

    return ProviderTrace()


def service_breakdown():
    from nvidia_agentic_rag.schemas import LatencyBreakdown

    return LatencyBreakdown()
