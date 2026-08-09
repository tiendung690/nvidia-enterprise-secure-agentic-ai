from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from nvidia_agentic_rag.agents.service import AgentService, AnswerCompletenessError
from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.data.analytics import BookSalesSummary, CustomerOrderSummary
from nvidia_agentic_rag.identity import IdentityContext
from nvidia_agentic_rag.policy import PolicyEngine
from nvidia_agentic_rag.schemas import SourceReference
from nvidia_agentic_rag.security import DataClassification, DataMasker
from nvidia_agentic_rag.tools import SecureAnalyticsTools

AS_OF = datetime(2026, 8, 8, 15, 54, tzinfo=UTC)


class Repository:
    def __init__(self) -> None:
        self.version = 0
        self.calls = 0
        self.customers = [
            CustomerOrderSummary(
                customer_id="C001",
                first_name="Ada",
                last_name="Lovelace",
                total_orders=2,
                total_quantity=4,
                total_amount=204.9,
                table_version=0,
                as_of=AS_OF,
            ),
            CustomerOrderSummary(
                customer_id="C002",
                first_name="Grace",
                last_name="Hopper",
                total_orders=1,
                total_quantity=2,
                total_amount=91.0,
                table_version=0,
                as_of=AS_OF,
            ),
            CustomerOrderSummary(
                customer_id="C003",
                first_name="Katherine",
                last_name="Johnson",
                total_orders=1,
                total_quantity=1,
                total_amount=55.0,
                table_version=0,
                as_of=AS_OF,
            ),
        ]
        self.books = [
            BookSalesSummary(
                book_id="B003",
                title="Data Engineering Exam",
                category="certification",
                total_orders=2,
                total_quantity=4,
                total_revenue=220.0,
                table_version=0,
                as_of=AS_OF,
            ),
            BookSalesSummary(
                book_id="B002",
                title="Cloud Exam",
                category="certification",
                total_orders=1,
                total_quantity=2,
                total_revenue=91.0,
                table_version=0,
                as_of=AS_OF,
            ),
            BookSalesSummary(
                book_id="B001",
                title="Python Exam",
                category="certification",
                total_orders=1,
                total_quantity=1,
                total_revenue=39.9,
                table_version=0,
                as_of=AS_OF,
            ),
        ]

    def get_customer_summary(self, *, tenant_id: str, customer_id: str):
        if tenant_id != "tenant-a":
            return None
        return next((row for row in self.customers if row.customer_id == customer_id), None)

    def get_book_summary(self, *, tenant_id: str, book_id: str):
        if tenant_id != "tenant-a":
            return None
        return next((row for row in self.books if row.book_id == book_id), None)

    def top_customers(self, *, tenant_id: str, limit: int):
        self.calls += 1
        if tenant_id != "tenant-a":
            return []
        return self.customers[:limit]

    def top_books(self, *, tenant_id: str, limit: int):
        self.calls += 1
        if tenant_id != "tenant-a":
            return []
        return self.books[:limit]

    def aggregate_customer_totals(self, *, tenant_id: str):
        self.calls += 1
        if tenant_id != "tenant-a":
            return {}, -1, None
        return {"total_orders": 4, "total_quantity": 7, "total_amount": 350.9}, 0, AS_OF

    def aggregate_book_totals(self, *, tenant_id: str):
        self.calls += 1
        if tenant_id != "tenant-a":
            return {}, -1, None
        return {"total_orders": 4, "total_quantity": 7, "total_revenue": 350.9}, 0, AS_OF

    def version_fingerprint(self, *, tenant_id: str) -> str:
        return f"{tenant_id}:gold-v{self.version}"


def settings(tmp_path) -> Settings:
    return Settings(
        environment="test",
        nvidia_api_key=SecretStr("x"),
        response_cache_ttl_seconds=300,
        response_cache_max_entries=50,
        audit_backend="memory",
        trace_backend="memory",
        memory_backend="disabled",
        output_dlp_mode="redact",
        citation_validation_mode="strict",
        citation_minimum_coverage=0.9,
        citation_repair_mode="conservative",
        deterministic_router_enabled=True,
        direct_rag_enabled=True,
    )


def identity(tenant: str = "tenant-a") -> IdentityContext:
    return IdentityContext(
        user_id="u",
        tenant_id=tenant,
        roles=("analyst",),
        clearance=DataClassification.CONFIDENTIAL,
    )


def service(tmp_path, repo: Repository) -> AgentService:
    tool = SecureAnalyticsTools(
        analytics_repository=repo,
        policy_engine=PolicyEngine(
            policy_version="enterprise-policy-v1",
            allowed_purposes=("business-analytics", "operations-review"),
        ),
        masker=DataMasker(mode="pseudonymize", salt="s"),
        max_rows=10,
    )
    return AgentService(
        settings(tmp_path),
        object(),
        lambda: "index-v1",
        direct_tools={"analytics_query_tool": tool.analytics_query},
        analytics_version_provider=lambda tenant: repo.version_fingerprint(tenant_id=tenant),
    )


@pytest.mark.asyncio
async def test_customer_ranking_is_deterministic_complete_and_provenance_valid(tmp_path) -> None:
    repo = Repository()
    svc = service(tmp_path, repo)
    result = await svc.chat(
        "Rank all customers by total_amount and show average spending per order.",
        "rank-customers",
        identity=identity(),
        purpose="business-analytics",
        answer_mode="enterprise_factual",
    )

    assert result.request_outcome == "success"
    assert result.tools == ["analytics_query_tool"]
    assert result.tool_call_count == 1
    assert result.provider_trace.execution_mode == "deterministic"
    assert result.provider_trace.invoked is False
    assert result.provider_trace.provider is None
    assert result.provider_trace.model_tier == "not_used"
    assert result.evidence_origin == "live_lakehouse_tool"
    assert "| 1 | C001 | 2 | 4 | 204.90 | 102.45 |" in result.answer
    assert "| 2 | C002 | 1 | 2 | 91.00 | 91.00 |" in result.answer
    assert "| 3 | C003 | 1 | 1 | 55.00 | 55.00 |" in result.answer
    assert result.citation_audit.valid
    assert result.citation_audit.coverage == 1.0
    assert result.answer_completeness.valid
    assert result.answer_completeness.expected_entities == 3
    assert result.answer_completeness.validated_entities == 3
    assert result.answer_completeness.ratio == 1.0
    assert result.provenance_audit.valid
    assert result.provenance_audit.derivation_count == 3
    assert result.provenance_audit.validated_count == 3
    assert len(result.provenance) == 3
    assert result.cache_admitted is True
    assert all(source.masked for source in result.sources)


@pytest.mark.asyncio
async def test_analytics_cache_is_delta_version_aware_and_tenant_isolated(tmp_path) -> None:
    repo = Repository()
    svc = service(tmp_path, repo)
    query = "Rank all books by total_revenue and show revenue per unit."

    first = await svc.chat(
        query,
        "cache",
        identity=identity(),
        purpose="business-analytics",
        answer_mode="enterprise_factual",
    )
    calls_after_first = repo.calls
    second = await svc.chat(
        query,
        "cache",
        identity=identity(),
        purpose="business-analytics",
        answer_mode="enterprise_factual",
    )
    assert first.request_outcome == "success"
    assert second.request_outcome == "cache_hit"
    assert second.evidence_origin == "cached_lakehouse_answer"
    assert repo.calls == calls_after_first

    repo.version = 1
    third = await svc.chat(
        query,
        "cache",
        identity=identity(),
        purpose="business-analytics",
        answer_mode="enterprise_factual",
    )
    assert third.request_outcome == "success"
    assert third.response_cache_hit is False
    assert repo.calls > calls_after_first

    other_tenant = await svc.chat(
        query,
        "cache",
        identity=identity("tenant-b"),
        purpose="business-analytics",
        answer_mode="enterprise_factual",
    )
    assert other_tenant.request_outcome == "insufficient_context"
    assert other_tenant.response_cache_hit is False
    assert "B003" not in other_tenant.answer


@pytest.mark.asyncio
async def test_reconciliation_respects_metric_grain_and_avoids_double_count_claim(tmp_path) -> None:
    repo = Repository()
    svc = service(tmp_path, repo)
    result = await svc.chat(
        "Run a cross-Gold reconciliation audit for customer and book totals.",
        "reconcile",
        identity=identity(),
        purpose="business-analytics",
        answer_mode="enterprise_factual",
    )

    assert result.request_outcome == "success"
    assert "amount_vs_revenue" in result.answer
    assert "quantity_vs_quantity" in result.answer
    assert "not_semantically_comparable" in result.answer
    assert "distinct-count metric at different grains" in result.answer
    assert result.answer_completeness.valid
    assert result.answer_completeness.expected_entities == 3
    assert result.provenance_audit.valid
    assert result.provenance_audit.derivation_count == 2
    assert any(source.source_kind == "semantic" for source in result.sources)


@pytest.mark.asyncio
async def test_completeness_gate_rejects_partially_repaired_analytics_and_does_not_cache(
    tmp_path,
) -> None:
    source1 = SourceReference(
        citation_id="D111111",
        source_id="delta:customer:C001:v0",
        source_kind="database",
        corpus="lakehouse-gold",
        file_name="gold_customer_order_summary",
        excerpt="C001 total_amount 204.9",
    )
    source2 = SourceReference(
        citation_id="D222222",
        source_id="delta:customer:C002:v0",
        source_kind="database",
        corpus="lakehouse-gold",
        file_name="gold_customer_order_summary",
        excerpt="C002 total_amount 91.0",
    )

    def broken_payload(_: str) -> str:
        return json.dumps(
            {
                "status": "success",
                "analytics_kind": "rank",
                "answer_contract": {
                    "expected_entities": 2,
                    "structure": "table_rows",
                    "required": True,
                },
                "provenance": [],
                "observation": {
                    "dataset": "gold_customer_order_summary",
                    "derived_metrics": [],
                    "rows": [
                        {
                            "rank": 1,
                            "customer_id": "C001",
                            "total_orders": 2,
                            "total_quantity": 4,
                            "total_amount": 204.9,
                            "citation_id": "D111111",
                        },
                        {
                            "rank": 2,
                            "customer_id": "C002",
                            "total_orders": 1,
                            "total_quantity": 2,
                            "total_amount": 91.0,
                            "citation_id": "",
                        },
                    ],
                },
                "sources": [
                    source1.model_dump(mode="json"),
                    source2.model_dump(mode="json"),
                ],
                "policy_audit": {"status": "allowed", "authorized_source_count": 2},
            }
        )

    svc = AgentService(
        settings(tmp_path),
        object(),
        lambda: "index-v1",
        direct_tools={"analytics_query_tool": broken_payload},
        analytics_version_provider=lambda tenant: f"{tenant}:v0",
    )

    with pytest.raises(AnswerCompletenessError) as exc_info:
        await svc.chat(
            "Rank all customers by total_amount.",
            "broken",
            identity=identity(),
            purpose="business-analytics",
            answer_mode="enterprise_factual",
        )
    audit = exc_info.value.audit
    assert audit.expected_entities == 2
    assert audit.validated_entities == 1
    assert audit.ratio == 0.5
    assert svc.cache_size() == 0

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("Show customer C001 spending trend over time by month.", "time_dimension_not_available"),
        ("Why did customer C001 total spending increase?", "causality_not_available"),
        (
            "Which books did customer C001 purchase?",
            "customer_book_relation_not_available",
        ),
    ],
)
async def test_known_unsupported_gold_questions_fail_closed_without_llm(
    tmp_path, query: str, reason: str
) -> None:
    repo = Repository()
    svc = service(tmp_path, repo)
    route = __import__(
        "nvidia_agentic_rag.routing", fromlist=["classify_route"]
    ).classify_route(query)
    assert route.kind == "analytics"
    assert json.loads(route.tool_input or "{}")["unsupported_reason"] == reason

    result = await svc.chat(
        query,
        f"unsupported-{reason}",
        identity=identity(),
        purpose="business-analytics",
        answer_mode="enterprise_factual",
    )
    assert result.request_outcome == "insufficient_context"
    assert result.provider_trace.invoked is False
    assert result.sources == []
    assert result.cache_admitted is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "Can you prove whether C001 purchased B003? Use only available evidence.",
        "Did C001 buy B003?",
        "Was B003 purchased by C001?",
    ],
)
async def test_bare_id_customer_book_proof_fails_closed_without_provider(
    tmp_path, query: str
) -> None:
    """Regression for the production 30 s timeout path.

    Customer/book Gold summaries cannot establish an order-item edge.  The router must recognize
    canonical bare IDs in relationship-proof phrasing and abstain deterministically instead of
    sending the question through the 550B agent lane.
    """
    route = __import__(
        "nvidia_agentic_rag.routing", fromlist=["classify_route"]
    ).classify_route(query)
    assert route.kind == "analytics"
    assert json.loads(route.tool_input or "{}") == {
        "dataset": "cross_gold",
        "operation": "unsupported",
        "unsupported_reason": "customer_book_relation_not_available",
    }

    repo = Repository()
    svc = service(tmp_path, repo)
    result = await svc.chat(
        query,
        "relationship-proof",
        identity=identity(),
        purpose="business-analytics",
        answer_mode="enterprise_factual",
    )

    assert result.request_outcome == "insufficient_context"
    assert result.tools == ["analytics_query_tool"]
    assert result.tool_call_count == 1
    assert result.provider_trace.invoked is False
    assert result.provider_trace.execution_mode == "deterministic"
    assert result.provider_trace.model_tier == "not_used"
    assert "insufficient to prove" in result.answer
    assert "customer-to-book/order-item relationship" in result.answer
    assert "No purchase relationship was inferred" in result.answer
    assert result.sources == []
    assert result.cache_admitted is False


def test_provenance_validator_rejects_tampered_derived_value() -> None:
    from nvidia_agentic_rag.grounding import validate_provenance
    from nvidia_agentic_rag.schemas import ProvenanceDerivation

    source = SourceReference(
        citation_id="D111111",
        source_id="delta:customer:C001:v0",
        source_kind="database",
        corpus="lakehouse-gold",
        file_name="gold_customer_order_summary",
        excerpt="total_amount=204.9,total_orders=2",
    )
    audit = validate_provenance(
        [
            ProvenanceDerivation(
                output_name="average_spending_per_order",
                formula_id="customer.average_spending_per_order.v1",
                formula="total_amount / total_orders",
                inputs={"total_amount": 204.9, "total_orders": 2},
                source_citation_ids=["D111111"],
                value=999.0,
            )
        ],
        [source],
    )
    assert audit.valid is False
    assert audit.validated_count == 0
    assert audit.mismatched_outputs == ["average_spending_per_order"]

@pytest.mark.asyncio
async def test_consistency_audit_prompt_routes_to_reconciliation_not_false_customer_lookup(
    tmp_path,
) -> None:
    query = (
        "Audit the two Gold tables for consistency. Determine: 1. total customer spending, "
        "2. total book revenue, 3. total customer quantity, 4. total book quantity, "
        "5. summed customer order counts, 6. summed book order counts. For each comparison, "
        "state whether equality is expected based on the grain of the tables. Flag possible "
        "double-counting. Do not invent explanations for discrepancies. Cite every factual result."
    )
    routing = __import__(
        "nvidia_agentic_rag.routing", fromlist=["classify_route"]
    ).classify_route(query)
    assert routing.kind == "analytics"
    assert json.loads(routing.tool_input or "{}") == {
        "dataset": "cross_gold",
        "operation": "reconcile",
    }

    repo = Repository()
    svc = service(tmp_path, repo)
    result = await svc.chat(
        query,
        "reconcile-consistency-audit",
        identity=identity(),
        purpose="business-analytics",
        answer_mode="enterprise_factual",
    )

    assert result.request_outcome == "success"
    assert result.tools == ["analytics_query_tool"]
    assert result.tool_call_count == 1
    assert result.provider_trace.invoked is False
    assert result.provider_trace.provider is None
    assert result.evidence_origin == "live_lakehouse_tool"
    assert "amount_vs_revenue | 350.90 | 350.90 | Yes | Yes | 0.00" in result.answer
    assert "quantity_vs_quantity | 7 | 7 | Yes | Yes | 0.00" in result.answer
    assert "summed_order_counts | 4 | 4 | No | Yes | N/A" in result.answer
    assert "possible double-counting" in result.answer
    assert "equal observed sums are not evidence that the metrics reconcile" in result.answer
    assert result.citation_audit.valid
    assert result.citation_audit.coverage == 1.0
    assert result.answer_completeness.valid
    assert result.answer_completeness.expected_entities == 3
    assert result.provenance_audit.valid
    assert result.cache_admitted is True


def test_router_does_not_treat_metric_nouns_as_entity_ids() -> None:
    from nvidia_agentic_rag.routing import classify_route

    customer_phrase = classify_route("Show customer spending totals from the Gold table.")
    assert not (
        customer_phrase.kind == "analytics"
        and json.loads(customer_phrase.tool_input or "{}").get("operation") == "lookup"
    )

    book_phrase = classify_route("Show book revenue totals from the Gold table.")
    assert not (
        book_phrase.kind == "analytics"
        and json.loads(book_phrase.tool_input or "{}").get("operation") == "lookup"
    )

    explicit_customer = classify_route("Show customer id alpha spending.")
    assert json.loads(explicit_customer.tool_input or "{}") == {
        "dataset": "gold_customer_order_summary",
        "operation": "lookup",
        "entity_id": "alpha",
    }

    explicit_book = classify_route("Show book code catalog-x revenue.")
    assert json.loads(explicit_book.tool_input or "{}") == {
        "dataset": "gold_book_sales_summary",
        "operation": "lookup",
        "entity_id": "catalog-x",
    }


TEN_CASE_ANALYTICS_REGRESSION = [
    (
        "How much has customer C001 spent in total, and which book generated the highest "
        "revenue? Cite both claims.",
        "success",
        "Customer C001 has spent a total of 204.90",
    ),
    (
        "Compare C001's total spending with the highest book revenue. Calculate the absolute "
        "and percentage difference.",
        "success",
        "percentage difference relative to customer spending is 7.37%",
    ),
    (
        "Rank all books by revenue and calculate revenue per unit for each book.",
        "success",
        "| 1 | B003 | Data Engineering Exam | 2 | 4 | 220.00 | 55.00 |",
    ),
    (
        "Rank all customers by total amount and calculate average spending per order.",
        "success",
        "| 1 | C001 | 2 | 4 | 204.90 | 102.45 |",
    ),
    (
        "Perform a reconciliation between total customer spending and total book revenue.",
        "success",
        "amount_vs_revenue",
    ),
    (
        "Can you prove whether C001 purchased B003? Use only available evidence.",
        "insufficient_context",
        "customer-to-book/order-item relationship",
    ),
    (
        "What percentage of B003 revenue came from C001?",
        "insufficient_context",
        "customer-book/order-item grain",
    ),
    (
        "How much did B003 revenue grow compared with last month?",
        "insufficient_context",
        "historical/time dimension",
    ),
    (
        "Why does B003 have the highest revenue? Separate facts from unsupported causal "
        "explanations.",
        "success",
        "Unsupported causal explanations:",
    ),
    (
        "Audit both Gold tables for total amount/revenue, quantity and order-count consistency. "
        "Explain possible double-counting based on table grain.",
        "success",
        "summed_order_counts",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_outcome", "expected_text"), TEN_CASE_ANALYTICS_REGRESSION
)
async def test_full_ten_case_analytics_regression_is_provider_independent(
    tmp_path, query: str, expected_outcome: str, expected_text: str
) -> None:
    """The production demo analytics suite must never depend on hosted LLM availability."""
    repo = Repository()
    svc = service(tmp_path, repo)

    result = await svc.chat(
        query,
        "ten-case-regression",
        identity=identity(),
        purpose="business-analytics",
        answer_mode="enterprise_factual",
    )

    assert result.request_outcome == expected_outcome
    assert result.tools == ["analytics_query_tool"]
    assert result.tool_call_count == 1
    assert result.provider_trace.invoked is False
    assert result.provider_trace.execution_mode == "deterministic"
    assert result.provider_trace.model_tier == "not_used"
    assert result.latency_breakdown.provider_ms == 0.0
    assert expected_text in result.answer


def test_exact_final_four_cases_resolve_evidence_requirements_before_provider() -> None:
    from nvidia_agentic_rag.routing import classify_route

    expected = {
        "What percentage of B003 revenue came from C001?": (
            "unsupported",
            "customer_book_metric_not_available",
        ),
        "How much did B003 revenue grow compared with last month?": (
            "unsupported",
            "time_dimension_not_available",
        ),
        (
            "Why does B003 have the highest revenue? Separate facts from unsupported causal "
            "explanations."
        ): ("top_book_causal_guard", None),
        (
            "Audit both Gold tables for total amount/revenue, quantity and order-count "
            "consistency. Explain possible double-counting based on table grain."
        ): ("reconcile", None),
    }

    for query, (operation, unsupported_reason) in expected.items():
        route = classify_route(query)
        assert route.kind == "analytics"
        plan = json.loads(route.tool_input or "{}")
        assert plan["operation"] == operation
        if unsupported_reason is not None:
            assert plan["unsupported_reason"] == unsupported_reason
