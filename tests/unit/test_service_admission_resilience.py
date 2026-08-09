from __future__ import annotations

import asyncio

import pytest
from pydantic import SecretStr

from nvidia_agentic_rag.agents.service import AgentService
from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.runtime import (
    CapacityWaitTimeoutError,
    ProviderUnavailableError,
    SessionBusyError,
)
from nvidia_agentic_rag.schemas import SourceReference


def settings_for(tmp_path, **overrides) -> Settings:
    values = {
        "environment": "test",
        "nvidia_api_key": SecretStr("test-key"),
        "data_dir": tmp_path / "data",
        "course_data_dir": tmp_path / "data/course",
        "papers_data_dir": tmp_path / "data/papers",
        "storage_dir": tmp_path / "storage",
        "citation_minimum_coverage": 1.0,
        "provider_retry_base_seconds": 0.001,
        "provider_retry_max_seconds": 0.001,
        "provider_retry_jitter": False,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def source() -> SourceReference:
    return SourceReference(
        citation_id="SABC123",
        source_id="paper:chunk-1",
        corpus="research-papers",
        file_name="paper2.txt",
        excerpt="Evidence",
    )


@pytest.mark.asyncio
async def test_transient_provider_failure_is_retried(tmp_path) -> None:
    service = AgentService(
        settings_for(tmp_path, provider_retry_max_attempts=2), object(), lambda: "v1"
    )
    calls = 0

    async def fake_run(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("503 service unavailable")
        return "General guidance."

    service._run_agent = fake_run  # type: ignore[method-assign]
    result = await service.chat("hello", "s", user_id="u")
    assert result.request_outcome == "success"
    assert result.provider_trace.attempts == 2
    assert result.provider_trace.retry_count == 1
    assert result.provider_trace.transient_failures == 1


@pytest.mark.asyncio
async def test_provider_failure_after_retry_budget_returns_typed_error(tmp_path) -> None:
    service = AgentService(
        settings_for(tmp_path, provider_retry_max_attempts=2), object(), lambda: "v1"
    )

    async def fake_run(**kwargs):
        raise RuntimeError("ResourceExhausted: request queue full")

    service._run_agent = fake_run  # type: ignore[method-assign]
    with pytest.raises(ProviderUnavailableError) as captured:
        await service.chat("hello", "s", user_id="u")
    assert captured.value.error_code == "NVIDIA_CAPACITY_EXHAUSTED"
    assert captured.value.provider_trace.attempts == 2


@pytest.mark.asyncio
async def test_reject_policy_returns_session_busy_for_same_session(tmp_path) -> None:
    service = AgentService(
        settings_for(tmp_path, session_concurrency_policy="reject"), object(), lambda: "v1"
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def fake_run(**kwargs):
        entered.set()
        await release.wait()
        return "General guidance."

    service._run_agent = fake_run  # type: ignore[method-assign]
    first = asyncio.create_task(service.chat("one", "same", user_id="u"))
    await entered.wait()
    with pytest.raises(SessionBusyError):
        await service.chat("two", "same", user_id="u")
    release.set()
    await first


@pytest.mark.asyncio
async def test_capacity_wait_timeout_is_not_execution_timeout(tmp_path) -> None:
    service = AgentService(
        settings_for(
            tmp_path,
            agent_max_concurrent_requests=1,
            agent_queue_timeout_seconds=0.01,
        ),
        object(),
        lambda: "v1",
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def fake_run(**kwargs):
        entered.set()
        await release.wait()
        return "General guidance."

    service._run_agent = fake_run  # type: ignore[method-assign]
    first = asyncio.create_task(service.chat("one", "s1", user_id="u"))
    await entered.wait()
    with pytest.raises(CapacityWaitTimeoutError) as captured:
        await service.chat("two", "s2", user_id="u")
    assert captured.value.waited_ms >= 1
    release.set()
    await first


@pytest.mark.asyncio
async def test_serialize_policy_allows_second_same_session_request(tmp_path) -> None:
    service = AgentService(
        settings_for(
            tmp_path,
            session_concurrency_policy="serialize",
            session_lock_wait_timeout_seconds=1.0,
        ),
        object(),
        lambda: "v1",
    )
    calls = 0

    async def fake_run(**kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return "General guidance."

    service._run_agent = fake_run  # type: ignore[method-assign]
    first, second = await asyncio.gather(
        service.chat("one", "same", user_id="u", force_retrieval=True),
        service.chat("two", "same", user_id="u", force_retrieval=True),
    )
    assert calls == 2
    assert first.request_outcome == second.request_outcome == "success"
    assert (
        max(
            first.latency_breakdown.session_wait_ms,
            second.latency_breakdown.session_wait_ms,
        )
        > 0
    )


@pytest.mark.asyncio
async def test_strict_mode_conservatively_repairs_uncited_summary(tmp_path) -> None:
    service = AgentService(settings_for(tmp_path), object(), lambda: "v1")

    async def fake_run(**kwargs):
        item = source()
        kwargs["tool_calls"].append("research_paper_rag_tool")
        kwargs["collected_sources"][item.source_id] = item
        return (
            "| Metric | Result | Citation |\n"
            "|---|---|---|\n"
            "| Speed | 2.468 times faster | [SABC123] |\n\n"
            "In summary, the method is 2.5 times faster."
        )

    service._run_agent = fake_run  # type: ignore[method-assign]
    result = await service.chat("q", "s", user_id="u")
    assert result.citation_audit.valid
    assert result.citation_audit.repair_attempted
    assert result.citation_audit.removed_claim_count == 1
    assert "In summary" not in result.answer
    assert result.cache_admitted is False
