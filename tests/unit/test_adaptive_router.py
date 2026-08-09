from __future__ import annotations

import json

import pytest
from pydantic import SecretStr

from nvidia_agentic_rag.agents.service import AgentService
from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.query import should_expand_query
from nvidia_agentic_rag.routing import classify_route
from nvidia_agentic_rag.schemas import SourceReference


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


class FakeLLM:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    async def acomplete(self, prompt: str) -> str:
        self.calls += 1
        assert "Authorized evidence" in prompt
        return self.answer


def source(source_id: str, citation_id: str, corpus: str) -> SourceReference:
    return SourceReference(
        citation_id=citation_id,
        source_id=source_id,
        corpus=corpus,
        file_name="source.pdf",
        score=0.9,
        excerpt="grounded evidence",
    )


def rag_payload(item: SourceReference, evidence: str) -> str:
    return json.dumps(
        {
            "status": "success",
            "evidence": evidence,
            "sources": [item.model_dump(mode="json")],
            "safety_signals": [],
            "retrieval_trace": {
                "strategy": "identity",
                "query_variant_count": 1,
                "query_variant_hashes": ["a" * 64],
                "mode": "hybrid",
                "degraded": False,
                "relevance": "high",
                "top_score": 0.9,
                "query_coverage": 0.8,
                "fallback_chain": [],
            },
            "policy_audit": {
                "status": "allowed",
                "authorized_source_count": 1,
                "denied_candidate_count": 0,
                "classifications": ["public"],
            },
        }
    )


def insufficient_payload() -> str:
    return json.dumps(
        {
            "status": "insufficient_relevant_context",
            "evidence": "Evidence is insufficient.",
            "sources": [],
            "safety_signals": [],
            "retrieval_trace": {
                "strategy": "identity",
                "query_variant_count": 1,
                "query_variant_hashes": ["b" * 64],
                "mode": "hybrid",
                "degraded": False,
                "relevance": "low",
                "top_score": 0.3,
                "query_coverage": 0.1,
                "fallback_chain": [],
            },
            "policy_audit": {
                "status": "insufficient_context",
                "authorized_source_count": 0,
                "denied_candidate_count": 0,
            },
        }
    )


def test_deterministic_router_routes_fast_and_explicit_paths() -> None:
    calculator = classify_route("Calculate (125 * 5) + 25.")
    assert calculator.kind == "calculator"
    assert calculator.tool_input == "(125 * 5) + 25"

    definition = classify_route("Define retrieval-augmented generation in two sentences.")
    assert definition.kind == "definition"
    assert definition.tool_input == "retrieval-augmented generation"

    analytics = classify_route(
        "Compare customer C001's total spending with the revenue of the highest-revenue book. "
        "Which value is larger, by how much, and what is the percentage difference relative "
        "to C001's spending?"
    )
    assert analytics.kind == "analytics"
    assert analytics.tool_names == ("analytics_query_tool",)
    plan = json.loads(analytics.tool_input or "{}")
    assert plan == {
        "dataset": "cross_gold",
        "operation": "compare_customer_top_book",
        "entity_id": "C001",
    }
    assert analytics.requires_enterprise_evidence is True

    course = classify_route(
        "Using only the indexed Agentic RAG course, explain Basic RAG and Agentic RAG."
    )
    assert course.kind == "direct_rag"
    assert course.tool_names == ("agentic_rag_course_tool",)
    assert "Using only" not in (course.tool_input or "")

    papers = classify_route("Using only the indexed research papers, explain eRAG.")
    assert papers.tool_names == ("research_paper_rag_tool",)

    both = classify_route(
        "Using the indexed course documents and research papers, compare ReAct with eRAG."
    )
    assert both.tool_names == (
        "agentic_rag_course_tool",
        "research_paper_rag_tool",
    )
    assert classify_route("Plan a multi-step investigation").kind == "agent"


def test_adaptive_multi_query_only_expands_broad_or_ambiguous_queries() -> None:
    assert not should_expand_query("What is eRAG?")
    assert should_expand_query("Compare architecture trade-offs and failure modes of RAG")
    assert should_expand_query("Explain this")


@pytest.mark.asyncio
async def test_calculator_and_definition_bypass_llm(tmp_path) -> None:
    llm = FakeLLM("unused")
    service = AgentService(
        settings_for(tmp_path),
        object(),
        lambda: "v1",
        llm=llm,
        direct_tools={
            "safe_calculator_tool": lambda expression: "650",
            "definition_tool": lambda term: (
                "Retrieval uses external context before generation."
            ),
        },
    )
    calculator = await service.chat("Calculate (125 * 5) + 25.", "calc", user_id="u")
    assert calculator.answer == "650"
    assert calculator.tools == ["safe_calculator_tool"]
    assert calculator.provider_trace.attempts == 0
    assert calculator.citation_audit.applicable is False

    definition = await service.chat(
        "Define retrieval-augmented generation in two sentences.",
        "define",
        user_id="u",
    )
    assert definition.tools == ["definition_tool"]
    assert "generation" in definition.answer.casefold()
    assert llm.calls == 0


def analytics_comparison_payload() -> str:
    customer = SourceReference(
        citation_id="D111111",
        source_id="delta:gold_customer_order_summary:tenant-a:C001:v3",
        source_kind="database",
        corpus="lakehouse-gold",
        file_name="gold_customer_order_summary",
        excerpt="customer total 204.90",
    )
    book = SourceReference(
        citation_id="D222222",
        source_id="delta:gold_book_sales_summary:tenant-a:B003:v3",
        source_kind="database",
        corpus="lakehouse-gold",
        file_name="gold_book_sales_summary",
        excerpt="book revenue 220.00",
    )
    return json.dumps(
        {
            "status": "success",
            "analytics_kind": "compare_customer_top_book",
            "answer_contract": {
                "expected_entities": 2,
                "structure": "comparison",
                "required": True,
            },
            "observation": {
                "customer": {"customer_id": "C001"},
                "highest_revenue_book": {
                    "book_id": "B003",
                    "title": "Data Engineering Exam",
                },
                "customer_total_spending": 204.9,
                "top_book_revenue": 220.0,
                "larger_value": "highest_revenue_book",
                "absolute_difference": 15.1,
                "percentage_difference_relative_to_customer_spending": 7.37,
                "calculation": {
                    "difference": "abs(220.00 - 204.90) = 15.10",
                    "percentage_relative_to_customer_spending": (
                        "(15.10 / 204.90) * 100 = 7.37%"
                    ),
                },
            },
            "provenance": [
                {
                    "output_name": "absolute_difference",
                    "formula_id": "comparison.absolute_difference.v1",
                    "formula": "abs(top_book_revenue - customer_total_spending)",
                    "inputs": {
                        "top_book_revenue": 220.0,
                        "customer_total_spending": 204.9,
                    },
                    "source_citation_ids": ["D111111", "D222222"],
                    "value": 15.1,
                },
                {
                    "output_name": "percentage_difference_relative_to_customer_spending",
                    "formula_id": "comparison.percentage_difference.v1",
                    "formula": "absolute_difference / customer_total_spending * 100",
                    "inputs": {
                        "absolute_difference": 15.1,
                        "customer_total_spending": 204.9,
                    },
                    "source_citation_ids": ["D111111", "D222222"],
                    "value": 7.37,
                },
            ],
            "sources": [
                customer.model_dump(mode="json"),
                book.model_dump(mode="json"),
            ],
            "policy_audit": {
                "status": "allowed",
                "authorized_source_count": 2,
                "classifications": ["confidential", "internal"],
            },
        }
    )


@pytest.mark.asyncio
async def test_analytics_comparison_bypasses_agent_and_calculator_chain(tmp_path) -> None:
    llm = FakeLLM("unused")
    service = AgentService(
        settings_for(tmp_path),
        object(),
        lambda: "v1",
        llm=llm,
        direct_tools={
            "analytics_query_tool": lambda plan_json: (
                analytics_comparison_payload()
                if json.loads(plan_json).get("entity_id") == "C001"
                else "{}"
            )
        },
    )
    result = await service.chat(
        "Compare customer C001's total spending with the revenue of the highest-revenue book. "
        "Which value is larger, by how much, and what is the percentage difference relative "
        "to C001's spending? Show the calculation and cite the source values.",
        "analytics-direct",
        user_id="u",
        purpose="business-analytics",
        answer_mode="enterprise_factual",
    )
    assert result.request_outcome == "success"
    assert result.tools == ["analytics_query_tool"]
    assert result.tool_call_count == 1
    assert result.provider_trace.attempts == 0
    assert llm.calls == 0
    assert "15.10" in result.answer
    assert "7.37%" in result.answer
    assert "[D111111][D222222]" in result.answer
    assert result.citation_audit.valid
    assert len(result.sources) == 2


@pytest.mark.asyncio
async def test_direct_rag_uses_one_synthesis_and_preserves_sources(tmp_path) -> None:
    item = source("course:1", "SABC123", "agentic-rag-course")
    llm = FakeLLM("Basic RAG retrieves before generation [SABC123].")
    service = AgentService(
        settings_for(tmp_path),
        object(),
        lambda: "v1",
        llm=llm,
        direct_tools={
            "agentic_rag_course_tool": lambda query: rag_payload(
                item,
                "[SABC123] Basic RAG retrieves context before generation.",
            )
        },
    )
    result = await service.chat(
        "Using only the indexed Agentic RAG course, explain Basic RAG.",
        "rag",
        user_id="u",
    )
    assert result.request_outcome == "success"
    assert result.tools == ["agentic_rag_course_tool"]
    assert result.tool_call_count == 1
    assert result.sources == [item]
    assert result.citation_audit.valid
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_direct_rag_fails_closed_before_generation_when_evidence_is_weak(
    tmp_path,
) -> None:
    llm = FakeLLM("must not run")
    service = AgentService(
        settings_for(tmp_path),
        object(),
        lambda: "v1",
        llm=llm,
        direct_tools={"agentic_rag_course_tool": lambda query: insufficient_payload()},
    )
    result = await service.chat(
        "According to the indexed Agentic RAG course, provide the instructor's "
        "home address, bank account, salary, and electricity cost.",
        "weak",
        user_id="u",
    )
    assert result.request_outcome == "insufficient_context"
    assert result.sources == []
    assert result.tools == ["agentic_rag_course_tool"]
    assert llm.calls == 0
    assert result.retrieval_traces[0].relevance == "low"
