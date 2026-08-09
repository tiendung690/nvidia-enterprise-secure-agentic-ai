from __future__ import annotations

import json

import pytest
from pydantic import SecretStr

from nvidia_agentic_rag.agents.service import AgentService, _PolicyAccumulator
from nvidia_agentic_rag.audit import InMemoryAuditService
from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.identity import IdentityContext
from nvidia_agentic_rag.policy import PolicyEngine
from nvidia_agentic_rag.schemas import SourceReference
from nvidia_agentic_rag.security import DataClassification, DataMasker, OutputPolicy


def settings_for(tmp_path, **overrides):
    values = {
        "environment": "test",
        "nvidia_api_key": SecretStr("test-key"),
        "data_dir": tmp_path / "data",
        "course_data_dir": tmp_path / "data/course",
        "papers_data_dir": tmp_path / "data/papers",
        "storage_dir": tmp_path / "storage",
        "allowed_purposes": ("research",),
        "citation_minimum_coverage": 0.0,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def identity(version="1"):
    return IdentityContext(
        user_id="u",
        tenant_id="tenant-a",
        roles=["architect"],
        departments=["platform"],
        clearance=DataClassification.CONFIDENTIAL,
        authorization_version=version,
    )


def service(tmp_path, **settings_overrides):
    settings = settings_for(tmp_path, **settings_overrides)
    audit = InMemoryAuditService()
    instance = AgentService(
        settings,
        object(),
        lambda: "v1",
        policy_engine=PolicyEngine(
            policy_version="p1", allowed_purposes=("research",)
        ),
        output_policy=OutputPolicy(
            mode=settings.output_dlp_mode,
            masker=DataMasker(mode="redact", salt="s"),
        ),
        audit_service=audit,
    )
    return instance, audit


@pytest.mark.asyncio
async def test_policy_denied_before_agent_execution(tmp_path) -> None:
    instance, audit = service(tmp_path)
    result = await instance.chat(
        "show payroll",
        "s",
        identity=identity(),
        purpose="payroll-export",
        answer_mode="enterprise_factual",
    )
    assert result.evidence_origin == "policy_denied"
    assert result.policy_audit.status == "denied"
    assert audit.events[-1].outcome == "policy_denied"


@pytest.mark.asyncio
async def test_enterprise_factual_fails_closed_without_sources(tmp_path) -> None:
    instance, audit = service(tmp_path)

    async def fake_run(**kwargs):
        return "Invented company answer"

    instance._run_agent = fake_run  # type: ignore[method-assign]
    result = await instance.chat(
        "company fact",
        "s",
        identity=identity(),
        purpose="research",
        answer_mode="enterprise_factual",
    )
    assert result.evidence_origin == "insufficient_authorized_context"
    assert "insufficient" in result.answer.lower()
    assert instance.cache_size() == 0
    assert audit.events[-1].outcome == "insufficient_authorized_context"


@pytest.mark.asyncio
async def test_cache_key_invalidates_when_authorization_version_changes(tmp_path) -> None:
    instance, _ = service(tmp_path)
    calls = 0

    async def fake_run(**kwargs):
        nonlocal calls
        calls += 1
        return "General guidance"

    instance._run_agent = fake_run  # type: ignore[method-assign]
    await instance.chat("q", "s", identity=identity("1"), purpose="research")
    await instance.chat("q", "s", identity=identity("1"), purpose="research")
    await instance.chat("q", "s", identity=identity("2"), purpose="research")
    assert calls == 2


@pytest.mark.asyncio
async def test_output_dlp_redacts_and_is_audited(tmp_path) -> None:
    instance, audit = service(tmp_path, output_dlp_mode="redact")

    async def fake_run(**kwargs):
        return "Contact a@example.com"

    instance._run_agent = fake_run  # type: ignore[method-assign]
    result = await instance.chat("q", "s", identity=identity(), purpose="research")
    assert "a@example.com" not in result.answer
    assert "email" in result.policy_audit.output_dlp_signals
    assert audit.events[-1].answer_hash


def test_policy_payload_accumulator_merges_security_metadata(tmp_path) -> None:
    instance, _ = service(tmp_path)
    accumulator = _PolicyAccumulator()
    sources = {}
    signals = set()
    source = SourceReference(
        citation_id="SABC123",
        source_id="id",
        corpus="c",
        file_name="f.pdf",
        excerpt="e",
    )
    payload = {
        "sources": [source.model_dump(mode="json")],
        "safety_signals": ["indirect"],
        "policy_audit": {
            "status": "allowed",
            "decision_id": "PD-1",
            "denied_candidate_count": 2,
            "classifications": ["confidential"],
        },
    }
    instance._collect_tool_payload(json.dumps(payload), sources, signals, accumulator)
    assert accumulator.denied_candidate_count == 2
    assert accumulator.classifications == {"confidential"}
    assert accumulator.decision_ids == ["PD-1"]
    assert signals == {"indirect"}
