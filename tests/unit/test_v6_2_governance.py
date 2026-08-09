from __future__ import annotations

import json

import pytest
from pydantic import SecretStr

from nvidia_agentic_rag.agents.service import AgentService
from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.gateway import ModelGateway
from nvidia_agentic_rag.runtime import TenantBudgetExceededError
from nvidia_agentic_rag.tools.calculator import safe_calculate


def settings_for(tmp_path, **overrides) -> Settings:
    values = {
        "environment": "test",
        "nvidia_api_key": SecretStr("test-key"),
        "data_dir": tmp_path / "data",
        "course_data_dir": tmp_path / "data/course",
        "papers_data_dir": tmp_path / "data/papers",
        "storage_dir": tmp_path / "storage",
        "citation_minimum_coverage": 0.0,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def insufficient_payload() -> str:
    return json.dumps(
        {
            "status": "insufficient_context",
            "evidence": "",
            "sources": [],
            "safety_signals": [],
            "retrieval_trace": {
                "strategy": "identity",
                "query_variant_count": 1,
                "mode": "vector",
                "degraded": False,
                "relevance": "low",
                "top_score": 0.05,
                "query_coverage": 0.0,
            },
        }
    )


class _Handler:
    def __init__(self, answer: str) -> None:
        self._answer = answer

    async def stream_events(self):
        return
        yield  # pragma: no cover - makes this an async generator

    def __await__(self):
        async def done() -> str:
            return self._answer

        return done().__await__()


class RecordingAgent:
    """Minimal FunctionAgent stand-in that records whether the agent lane ran."""

    def __init__(self, answer: str = "General guidance without enterprise claims.") -> None:
        self.runs = 0
        self._answer = answer

    def run(self, *, user_msg: str, ctx: object) -> _Handler:
        self.runs += 1
        return _Handler(self._answer)


@pytest.mark.asyncio
async def test_direct_rag_escalates_to_agent_lane_when_enabled(tmp_path) -> None:
    agent = RecordingAgent()
    service = AgentService(
        settings_for(tmp_path, cross_lane_escalation_enabled=True),
        agent,
        lambda: "v1",
        llm=None,
        direct_tools={"agentic_rag_course_tool": lambda query: insufficient_payload()},
    )
    result = await service.chat(
        "According to the indexed Agentic RAG course, provide the instructor's "
        "home address, bank account, salary, and electricity cost.",
        "escalate",
        user_id="u",
    )
    # The agent lane ran once, and the evidence gate still failed closed afterwards
    # because escalation produced no authorized sources either.
    assert agent.runs == 1
    assert result.request_outcome == "insufficient_context"
    assert result.sources == []


@pytest.mark.asyncio
async def test_escalation_disabled_preserves_fail_closed_without_generation(tmp_path) -> None:
    agent = RecordingAgent()
    service = AgentService(
        settings_for(tmp_path, cross_lane_escalation_enabled=False),
        agent,
        lambda: "v1",
        llm=None,
        direct_tools={"agentic_rag_course_tool": lambda query: insufficient_payload()},
    )
    result = await service.chat(
        "According to the indexed Agentic RAG course, list all confidential records.",
        "no-escalate",
        user_id="u",
    )
    assert agent.runs == 0
    assert result.request_outcome == "insufficient_context"


@pytest.mark.asyncio
async def test_tenant_budget_rejects_before_any_lane_runs(tmp_path) -> None:
    agent = RecordingAgent()
    service = AgentService(
        settings_for(tmp_path, tenant_daily_request_budget=1),
        agent,
        lambda: "v1",
        llm=None,
        direct_tools={"safe_calculator_tool": safe_calculate},
    )
    first = await service.chat("2 + 2", "budget", user_id="u")
    assert first.request_outcome == "success"
    with pytest.raises(TenantBudgetExceededError) as excinfo:
        await service.chat("3 + 3", "budget", user_id="u")
    assert excinfo.value.retry_after_seconds > 0
    assert agent.runs == 0


@pytest.mark.asyncio
async def test_cache_hits_bypass_tenant_budget(tmp_path) -> None:
    service = AgentService(
        settings_for(tmp_path, tenant_daily_request_budget=1),
        RecordingAgent(),
        lambda: "v1",
        llm=None,
        direct_tools={"safe_calculator_tool": safe_calculate},
    )
    assert (await service.chat("5 + 5", "cached", user_id="u")).request_outcome == "success"
    repeat = await service.chat("5 + 5", "cached", user_id="u")
    assert repeat.request_outcome == "cache_hit"


class TierRecordingLLM:
    def __init__(self, name: str, *, fail_transient_times: int = 0) -> None:
        self.name = name
        self.calls = 0
        self._fail_transient_times = fail_transient_times

    async def acomplete(self, prompt: str) -> str:
        self.calls += 1
        if self.calls <= self._fail_transient_times:
            raise RuntimeError("429 too many requests: model queue at capacity")
        return f"{self.name} synthesis [S000001]."


def rag_payload_with_source() -> str:
    return json.dumps(
        {
            "status": "success",
            "evidence": "[S000001] governed fact",
            "sources": [
                {
                    "citation_id": "S000001",
                    "source_id": "doc-1",
                    "corpus": "course",
                    "file_name": "source.pdf",
                    "score": 0.9,
                    "excerpt": "grounded evidence",
                }
            ],
            "safety_signals": [],
            "retrieval_trace": {
                "strategy": "identity",
                "query_variant_count": 1,
                "mode": "hybrid",
                "degraded": False,
                "relevance": "high",
                "top_score": 0.9,
                "query_coverage": 1.0,
            },
        }
    )


@pytest.mark.asyncio
async def test_simple_direct_rag_synthesis_uses_fast_tier(tmp_path) -> None:
    complex_llm = TierRecordingLLM("complex")
    fast_llm = TierRecordingLLM("fast")
    gateway = ModelGateway(complex_llm=complex_llm, fast_llm=fast_llm, routing_enabled=True)
    service = AgentService(
        settings_for(tmp_path),
        RecordingAgent(),
        lambda: "v1",
        llm=complex_llm,
        direct_tools={"agentic_rag_course_tool": lambda query: rag_payload_with_source()},
        model_gateway=gateway,
    )
    result = await service.chat(
        "According to the indexed Agentic RAG course, what is a planner?",
        "tier",
        user_id="u",
    )
    assert result.request_outcome == "success"
    assert fast_llm.calls == 1
    assert complex_llm.calls == 0
    assert result.provider_trace.model_tier == "fast"
    assert result.provider_trace.degraded_to_fast is False


@pytest.mark.asyncio
async def test_transient_exhaustion_degrades_complex_synthesis_to_fast(tmp_path) -> None:
    complex_llm = TierRecordingLLM("complex", fail_transient_times=99)
    fast_llm = TierRecordingLLM("fast")
    gateway = ModelGateway(
        complex_llm=complex_llm,
        fast_llm=fast_llm,
        routing_enabled=False,
        degrade_to_fast=True,
    )
    service = AgentService(
        settings_for(
            tmp_path,
            provider_retry_max_attempts=2,
            provider_retry_base_seconds=0.01,
            provider_retry_max_seconds=0.02,
        ),
        RecordingAgent(),
        lambda: "v1",
        llm=complex_llm,
        direct_tools={"agentic_rag_course_tool": lambda query: rag_payload_with_source()},
        model_gateway=gateway,
    )
    result = await service.chat(
        "According to the indexed Agentic RAG course, what is a planner?",
        "degrade",
        user_id="u",
    )
    assert result.request_outcome == "success"
    assert complex_llm.calls == 1
    assert fast_llm.calls == 1
    assert result.provider_trace.degraded_to_fast is True
    assert result.provider_trace.model_tier == "fast"
    assert "fast synthesis" in result.answer
