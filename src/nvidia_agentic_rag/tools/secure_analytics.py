from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from nvidia_agentic_rag.data.analytics import (
    AnalyticsRepository,
    AnalyticsSourceUnavailableError,
    BookSalesSummary,
    CustomerOrderSummary,
)
from nvidia_agentic_rag.data.semantic import AnalyticsQueryPlan, SemanticMetricRegistry
from nvidia_agentic_rag.identity import get_request_security_context
from nvidia_agentic_rag.policy import PolicyEngine
from nvidia_agentic_rag.rag.provenance import deterministic_citation_id
from nvidia_agentic_rag.schemas import SourceReference
from nvidia_agentic_rag.security import DataMasker

_ALLOWED_ROLES = ("analyst", "operations", "admin")
_ALLOWED_PURPOSES = ("business-analytics", "operations-review")
_TOP_DIMENSIONS = ("customers", "books")


class SecureAnalyticsTools:
    """Bounded typed capabilities over lakehouse gold aggregates; no SQL/Spark reaches the LLM.

    The medallion pipeline owns bronze/silver; only the curated gold serving contract is
    readable here, each observation cites the exact Delta commit version it came from, and
    direct-identifier fields are masked before entering the model context.
    """

    def __init__(
        self,
        *,
        analytics_repository: AnalyticsRepository,
        policy_engine: PolicyEngine,
        masker: DataMasker,
        customer_table: str = "gold_customer_order_summary",
        book_table: str = "gold_book_sales_summary",
        max_rows: int = 10,
    ) -> None:
        self.analytics_repository = analytics_repository
        self.policy_engine = policy_engine
        self.masker = masker
        self.customer_table = customer_table
        self.book_table = book_table
        self.max_rows = max(1, max_rows)
        self.semantic_registry = SemanticMetricRegistry()

    @staticmethod
    def _validated_key(value: str, field_name: str) -> str:
        value = value.strip()
        if not value or len(value) > 128:
            raise ValueError(f"{field_name} must be between 1 and 128 characters")
        return value

    def _authorize(self, scope: Any) -> Any:
        return self.policy_engine.authorize_capability(
            identity=scope.identity,
            purpose=scope.purpose,
            capability="analytics.read",
            tenant_id=scope.identity.tenant_id,
            allowed_roles=_ALLOWED_ROLES,
            allowed_purposes=_ALLOWED_PURPOSES,
        )

    @staticmethod
    def _policy_audit(scope: Any, decision: Any, status: str, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": status,
            "decision_id": decision.decision_id,
            "policy_version": decision.policy_version,
            "purpose": scope.purpose,
            "tenant_id": scope.identity.tenant_id,
        }
        payload.update(extra)
        return payload

    def _denied_payload(self, scope: Any, decision: Any) -> str:
        return json.dumps(
            {
                "status": "policy_denied",
                "reason": decision.reason,
                "sources": [],
                "policy_audit": self._policy_audit(
                    scope, decision, "denied", reason=decision.reason
                ),
            }
        )

    def _not_found_payload(self, scope: Any, decision: Any, message: str) -> str:
        return json.dumps(
            {
                "status": "not_found",
                "message": message,
                "sources": [],
                "policy_audit": self._policy_audit(scope, decision, "insufficient_context"),
            }
        )

    def _unavailable_payload(self, scope: Any, decision: Any) -> str:
        return json.dumps(
            {
                "status": "analytics_unavailable",
                "message": (
                    "The lakehouse gold serving tables are not reachable. "
                    "No analytics answer can be produced from authorized evidence."
                ),
                "sources": [],
                "policy_audit": self._policy_audit(scope, decision, "insufficient_context"),
            }
        )

    def _source(
        self,
        *,
        scope: Any,
        decision: Any,
        table: str,
        record_key: str,
        table_version: int,
        as_of: datetime | None,
        observation: dict[str, Any],
        classification: str,
        masked: bool,
        title: str,
    ) -> SourceReference:
        source_id = f"delta:{table}:{scope.identity.tenant_id}:{record_key}:v{table_version}"
        return SourceReference(
            citation_id=deterministic_citation_id(source_id, prefix="D"),
            source_id=source_id,
            source_kind="database",
            corpus="lakehouse-gold",
            file_name=table,
            title=title,
            section=f"delta_version={table_version}",
            excerpt=json.dumps(observation, ensure_ascii=False),
            tenant_id=scope.identity.tenant_id,
            document_id=record_key,
            classification=classification,
            # SourceReference.source_version is 1-based; Delta commit versions start at 0.
            # The raw commit version is preserved in source_id and section.
            source_version=table_version + 1,
            data_version=f"delta:v{table_version}",
            policy_version=decision.policy_version,
            authorization_decision_id=decision.decision_id,
            masked=masked,
            retrieved_at=datetime.now(UTC).isoformat(),
            source_as_of=as_of.isoformat() if as_of else None,
            tool_retrieved_at=datetime.now(UTC).isoformat(),
        )

    def _success_payload(
        self,
        *,
        scope: Any,
        decision: Any,
        observation: dict[str, Any],
        source: SourceReference,
        classification: str,
    ) -> str:
        return json.dumps(
            {
                "status": "success",
                "observation": observation,
                "evidence": (
                    f"[{source.citation_id}] Authorized lakehouse gold observation: "
                    f"{json.dumps(observation, ensure_ascii=False)}"
                ),
                "sources": [source.model_dump(mode="json")],
                "safety_signals": [],
                "policy_audit": self._policy_audit(
                    scope,
                    decision,
                    "allowed",
                    authorized_source_count=1,
                    classifications=[classification],
                ),
            },
            ensure_ascii=False,
        )

    def _success_payload_many(
        self,
        *,
        scope: Any,
        decision: Any,
        observation: dict[str, Any],
        sources: list[SourceReference],
        classifications: list[str],
    ) -> str:
        citations = " ".join(f"[{source.citation_id}]" for source in sources)
        return json.dumps(
            {
                "status": "success",
                "observation": observation,
                "evidence": (
                    f"{citations} Authorized deterministic lakehouse comparison: "
                    f"{json.dumps(observation, ensure_ascii=False)}"
                ),
                "sources": [source.model_dump(mode="json") for source in sources],
                "safety_signals": [],
                "policy_audit": self._policy_audit(
                    scope,
                    decision,
                    "allowed",
                    authorized_source_count=len(sources),
                    classifications=sorted(set(classifications)),
                ),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _money(value: float) -> Decimal:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        return format(value, ".2f")

    def _customer_observation(
        self, record: CustomerOrderSummary
    ) -> tuple[dict[str, Any], bool]:
        full_name = " ".join(part for part in (record.first_name, record.last_name) if part)
        masking = self.masker.mask_value("CUSTOMER_NAME", full_name)
        observation = {
            "customer_id": record.customer_id,
            "customer_name": masking.text or None,
            "total_orders": record.total_orders,
            "total_quantity": record.total_quantity,
            "total_amount": record.total_amount,
            "delta_table": self.customer_table,
            "delta_version": record.table_version,
            "as_of": record.as_of.isoformat() if record.as_of else None,
        }
        return observation, masking.masked

    def _book_observation(self, record: BookSalesSummary) -> dict[str, Any]:
        return {
            "book_id": record.book_id,
            "title": record.title,
            "category": record.category,
            "total_orders": record.total_orders,
            "total_quantity": record.total_quantity,
            "total_revenue": record.total_revenue,
            "delta_table": self.book_table,
            "delta_version": record.table_version,
            "as_of": record.as_of.isoformat() if record.as_of else None,
        }

    def get_customer_order_summary(self, customer_id: str) -> str:
        """Get one authorized customer order aggregate by exact customer ID."""
        scope = get_request_security_context()
        customer_id = self._validated_key(customer_id, "customer_id")
        decision = self._authorize(scope)
        if not decision.allowed:
            return self._denied_payload(scope, decision)
        try:
            record = self.analytics_repository.get_customer_summary(
                tenant_id=scope.identity.tenant_id,
                customer_id=customer_id,
            )
        except AnalyticsSourceUnavailableError:
            return self._unavailable_payload(scope, decision)
        if record is None:
            return self._not_found_payload(
                scope, decision, "No authorized customer summary matched the supplied ID."
            )
        observation, masked = self._customer_observation(record)
        source = self._source(
            scope=scope,
            decision=decision,
            table=self.customer_table,
            record_key=record.customer_id,
            table_version=record.table_version,
            as_of=record.as_of,
            observation=observation,
            classification="confidential",
            masked=masked,
            title=f"Customer order summary {record.customer_id}",
        )
        return self._success_payload(
            scope=scope,
            decision=decision,
            observation=observation,
            source=source,
            classification="confidential",
        )

    def get_book_sales_summary(self, book_id: str) -> str:
        """Get one authorized book sales aggregate by exact book ID."""
        scope = get_request_security_context()
        book_id = self._validated_key(book_id, "book_id")
        decision = self._authorize(scope)
        if not decision.allowed:
            return self._denied_payload(scope, decision)
        try:
            record = self.analytics_repository.get_book_summary(
                tenant_id=scope.identity.tenant_id,
                book_id=book_id,
            )
        except AnalyticsSourceUnavailableError:
            return self._unavailable_payload(scope, decision)
        if record is None:
            return self._not_found_payload(
                scope, decision, "No authorized book summary matched the supplied ID."
            )
        observation = self._book_observation(record)
        source = self._source(
            scope=scope,
            decision=decision,
            table=self.book_table,
            record_key=record.book_id,
            table_version=record.table_version,
            as_of=record.as_of,
            observation=observation,
            classification="internal",
            masked=False,
            title=f"Book sales summary {record.book_id}",
        )
        return self._success_payload(
            scope=scope,
            decision=decision,
            observation=observation,
            source=source,
            classification="internal",
        )

    def compare_customer_spending_to_top_book(self, customer_id: str) -> str:
        """Compare one customer's total spending with the highest-revenue book deterministically.

        This capability intentionally performs the arithmetic in application code instead of
        asking the model to chain multiple calculator calls. It keeps the comparison grounded in
        two typed gold-table observations and returns both source citations for the derived metrics.
        """
        scope = get_request_security_context()
        customer_id = self._validated_key(customer_id, "customer_id")
        decision = self._authorize(scope)
        if not decision.allowed:
            return self._denied_payload(scope, decision)

        try:
            customer = self.analytics_repository.get_customer_summary(
                tenant_id=scope.identity.tenant_id,
                customer_id=customer_id,
            )
            top_books = self.analytics_repository.top_books(
                tenant_id=scope.identity.tenant_id,
                limit=1,
            )
        except AnalyticsSourceUnavailableError:
            return self._unavailable_payload(scope, decision)

        if customer is None:
            return self._not_found_payload(
                scope, decision, "No authorized customer summary matched the supplied ID."
            )
        if not top_books:
            return self._not_found_payload(
                scope, decision, "The authorized gold table returned no book rows for this tenant."
            )

        top_book = top_books[0]
        customer_observation, customer_masked = self._customer_observation(customer)
        book_observation = self._book_observation(top_book)

        spending = self._money(customer.total_amount)
        revenue = self._money(top_book.total_revenue)
        difference = abs(revenue - spending).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if revenue > spending:
            larger = "highest_revenue_book"
        elif spending > revenue:
            larger = "customer_spending"
        else:
            larger = "equal"

        percentage: Decimal | None
        if spending == 0:
            percentage = None
        else:
            percentage = (
                difference / spending * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        customer_source = self._source(
            scope=scope,
            decision=decision,
            table=self.customer_table,
            record_key=customer.customer_id,
            table_version=customer.table_version,
            as_of=customer.as_of,
            observation=customer_observation,
            classification="confidential",
            masked=customer_masked,
            title=f"Customer order summary {customer.customer_id}",
        )
        book_source = self._source(
            scope=scope,
            decision=decision,
            table=self.book_table,
            record_key=top_book.book_id,
            table_version=top_book.table_version,
            as_of=top_book.as_of,
            observation=book_observation,
            classification="internal",
            masked=False,
            title=f"Highest-revenue book {top_book.book_id}",
        )

        spending_text = self._decimal_text(spending)
        revenue_text = self._decimal_text(revenue)
        difference_text = self._decimal_text(difference)
        percentage_text = self._decimal_text(percentage) if percentage is not None else None
        observation = {
            "customer": customer_observation,
            "highest_revenue_book": book_observation,
            "customer_total_spending": float(spending),
            "top_book_revenue": float(revenue),
            "larger_value": larger,
            "absolute_difference": float(difference),
            "percentage_difference_relative_to_customer_spending": (
                float(percentage) if percentage is not None else None
            ),
            "calculation": {
                "difference": f"abs({revenue_text} - {spending_text}) = {difference_text}",
                "percentage_relative_to_customer_spending": (
                    f"({difference_text} / {spending_text}) * 100 = {percentage_text}%"
                    if percentage is not None
                    else "undefined because customer_total_spending is 0.00"
                ),
            },
            "provenance": {
                "customer_delta_version": customer.table_version,
                "book_delta_version": top_book.table_version,
            },
        }
        return self._success_payload_many(
            scope=scope,
            decision=decision,
            observation=observation,
            sources=[customer_source, book_source],
            classifications=["confidential", "internal"],
        )


    def top_book_facts_with_causal_guard(self, book_id: str | None = None) -> str:
        """Return supported top-book facts while refusing unsupported causal explanations."""
        scope = get_request_security_context()
        decision = self._authorize(scope)
        if not decision.allowed:
            return self._denied_payload(scope, decision)

        requested_id = self._validated_key(book_id, "book_id") if book_id else None
        try:
            top_books = self.analytics_repository.top_books(
                tenant_id=scope.identity.tenant_id,
                limit=1,
            )
            requested = (
                self.analytics_repository.get_book_summary(
                    tenant_id=scope.identity.tenant_id,
                    book_id=requested_id,
                )
                if requested_id
                else None
            )
        except AnalyticsSourceUnavailableError:
            return self._unavailable_payload(scope, decision)

        if not top_books:
            return self._not_found_payload(
                scope, decision, "The authorized Gold table returned no book rows for this tenant."
            )
        if requested_id and requested is None:
            return self._not_found_payload(
                scope, decision, "No authorized book summary matched the supplied ID."
            )

        top_book = top_books[0]
        requested_book = requested or top_book
        requested_observation = self._book_observation(requested_book)
        top_observation = self._book_observation(top_book)
        requested_source = self._source(
            scope=scope,
            decision=decision,
            table=self.book_table,
            record_key=requested_book.book_id,
            table_version=requested_book.table_version,
            as_of=requested_book.as_of,
            observation=requested_observation,
            classification="internal",
            masked=False,
            title=f"Book sales summary {requested_book.book_id}",
        )
        sources = [requested_source]
        if top_book.book_id != requested_book.book_id:
            sources.append(
                self._source(
                    scope=scope,
                    decision=decision,
                    table=self.book_table,
                    record_key=top_book.book_id,
                    table_version=top_book.table_version,
                    as_of=top_book.as_of,
                    observation=top_observation,
                    classification="internal",
                    masked=False,
                    title=f"Highest-revenue book {top_book.book_id}",
                )
            )
        semantic_source = self._semantic_source(scope=scope, decision=decision)
        sources.append(semantic_source)
        return self._analytics_payload(
            scope=scope,
            decision=decision,
            analytics_kind="top_book_causal_guard",
            observation={
                "requested_book": requested_observation,
                "highest_revenue_book": top_observation,
                "requested_book_is_highest_revenue": (
                    requested_book.book_id == top_book.book_id
                ),
                "causal_evidence_available": False,
                "causal_assessment": (
                    "The governed Gold summaries establish observed ranking and descriptive "
                    "metrics only; they do not establish why the ranking occurred."
                ),
            },
            sources=sources,
            classifications=["internal"],
            expected_entities=2,
            structure="fact_causality_separation",
            provenance=[],
        )

    def _semantic_source(self, *, scope: Any, decision: Any) -> SourceReference:
        source_id = f"semantic:{self.semantic_registry.version}"
        return SourceReference(
            citation_id=deterministic_citation_id(source_id, prefix="S"),
            source_id=source_id,
            source_kind="semantic",
            corpus="semantic-registry",
            file_name="metric-registry",
            title="Lakehouse Gold semantic metric and grain registry",
            section=self.semantic_registry.version,
            excerpt=json.dumps(self.semantic_registry.semantic_snapshot(), ensure_ascii=False),
            tenant_id=scope.identity.tenant_id,
            classification="internal",
            source_version=1,
            data_version=self.semantic_registry.version,
            policy_version=decision.policy_version,
            authorization_decision_id=decision.decision_id,
            masked=False,
            retrieved_at=datetime.now(UTC).isoformat(),
            tool_retrieved_at=datetime.now(UTC).isoformat(),
        )

    def _derive_metric(
        self,
        *,
        dataset: str,
        metric_name: str,
        row: dict[str, Any],
        citation_id: str,
    ) -> tuple[float | None, dict[str, Any]]:
        metric = self.semantic_registry.metric(dataset, metric_name)
        if not metric.formula_id or not metric.formula:
            raise ValueError(f"Metric '{metric_name}' is not an allowlisted derived metric")
        inputs = {name: row.get(name) for name in metric.inputs}
        if metric_name == "average_spending_per_order":
            denominator = Decimal(str(inputs["total_orders"] or 0))
            value = (
                None
                if denominator == 0
                else self._money(float(inputs["total_amount"] or 0)) / denominator
            )
        elif metric_name == "revenue_per_unit":
            denominator = Decimal(str(inputs["total_quantity"] or 0))
            value = (
                None
                if denominator == 0
                else self._money(float(inputs["total_revenue"] or 0)) / denominator
            )
        elif metric_name == "average_units_per_order":
            denominator = Decimal(str(inputs["total_orders"] or 0))
            numerator = Decimal(str(inputs["total_quantity"] or 0))
            value = None if denominator == 0 else numerator / denominator
        else:
            raise ValueError(f"Derived metric implementation missing: {metric_name}")
        rounded = (
            value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if value is not None else None
        )
        provenance = {
            "output_name": metric_name,
            "formula_id": metric.formula_id,
            "formula": metric.formula,
            "inputs": inputs,
            "source_citation_ids": [citation_id],
            "value": float(rounded) if rounded is not None else None,
        }
        return (float(rounded) if rounded is not None else None), provenance

    def _analytics_payload(
        self,
        *,
        scope: Any,
        decision: Any,
        analytics_kind: str,
        observation: dict[str, Any],
        sources: list[SourceReference],
        classifications: list[str],
        expected_entities: int,
        structure: str,
        provenance: list[dict[str, Any]],
    ) -> str:
        evidence = "\n".join(
            f"[{source.citation_id}] {source.title or source.file_name}: {source.excerpt}"
            for source in sources
        )
        return json.dumps(
            {
                "status": "success",
                "analytics_kind": analytics_kind,
                "observation": observation,
                "answer_contract": {
                    "expected_entities": expected_entities,
                    "structure": structure,
                    "required": True,
                },
                "provenance": provenance,
                "evidence": evidence,
                "sources": [source.model_dump(mode="json") for source in sources],
                "safety_signals": [],
                "policy_audit": self._policy_audit(
                    scope,
                    decision,
                    "allowed",
                    authorized_source_count=len(sources),
                    classifications=sorted(set(classifications)),
                ),
            },
            ensure_ascii=False,
        )

    def analytics_query(self, plan_json: str) -> str:
        """Execute one governed typed analytics plan over curated Gold data.

        ``plan_json`` is a strict DSL. Arbitrary SQL, table names, columns, and formulas are not
        accepted. The application owns the dataset allowlist, metric registry, grain semantics,
        deterministic formulas, row limit, tenant predicate, masking, and provenance.
        """
        scope = get_request_security_context()
        decision = self._authorize(scope)
        if not decision.allowed:
            return self._denied_payload(scope, decision)
        try:
            raw_plan = json.loads(plan_json)
            plan = AnalyticsQueryPlan.model_validate(raw_plan)
            plan = self.semantic_registry.validate_plan(plan, max_rows=self.max_rows)
        except (json.JSONDecodeError, ValueError) as exc:
            return json.dumps(
                {
                    "status": "invalid_analytics_plan",
                    "message": str(exc),
                    "sources": [],
                    "policy_audit": self._policy_audit(scope, decision, "allowed"),
                }
            )

        if plan.operation == "unsupported":
            messages = {
                "time_dimension_not_available": (
                    "The authorized Gold serving tables expose current summary snapshots but do "
                    "not contain a governed historical/time dimension for period-over-period "
                    "analysis. A prior-period value cannot be inferred from the current snapshot."
                ),
                "causality_not_available": (
                    "The authorized Gold aggregates do not contain causal evidence; a causal "
                    "explanation would be unsupported."
                ),
                "customer_book_relation_not_available": (
                    "The available authorized Gold evidence is insufficient to prove whether a "
                    "specific customer purchased a specific book. The customer and book Gold "
                    "tables are summary-grain aggregates and do not expose a governed "
                    "customer-to-book/order-item relationship. No purchase relationship was "
                    "inferred from aggregate totals."
                ),
                "customer_book_metric_not_available": (
                    "The requested customer-to-book contribution metric cannot be computed from "
                    "the available authorized Gold summaries. The numerator requires governed "
                    "customer-book/order-item grain, while the current serving contract exposes "
                    "customer and book aggregates separately. No cross-grain percentage, share, "
                    "spend, quantity, or contribution was inferred from marginal totals."
                ),
            }
            reason = str(plan.unsupported_reason or "")
            message = messages.get(reason, "The requested analytical capability is unavailable.")
            return json.dumps(
                {
                    "status": "insufficient_context",
                    "message": message,
                    "unsupported_reason": reason,
                    "sources": [],
                    "safety_signals": [],
                    "policy_audit": self._policy_audit(
                        scope,
                        decision,
                        "insufficient_context",
                        reason=message,
                        reason_code=reason,
                    ),
                },
                ensure_ascii=False,
            )

        if plan.operation == "customer_and_top_book":
            payload = json.loads(
                self.compare_customer_spending_to_top_book(plan.entity_id or "")
            )
            if payload.get("status") != "success":
                return json.dumps(payload, ensure_ascii=False)
            observation = payload.get("observation", {})
            payload["analytics_kind"] = "customer_and_top_book"
            payload["observation"] = {
                "customer": observation.get("customer", {}),
                "highest_revenue_book": observation.get("highest_revenue_book", {}),
            }
            payload["answer_contract"] = {
                "expected_entities": 2,
                "structure": "two_fact_claims",
                "required": True,
            }
            payload["provenance"] = []
            return json.dumps(payload, ensure_ascii=False)

        if plan.operation == "top_book_causal_guard":
            return self.top_book_facts_with_causal_guard(plan.entity_id)

        if plan.operation == "compare_customer_top_book":
            payload = json.loads(self.compare_customer_spending_to_top_book(plan.entity_id or ""))
            if payload.get("status") != "success":
                return json.dumps(payload, ensure_ascii=False)
            payload["analytics_kind"] = "compare_customer_top_book"
            payload["answer_contract"] = {
                "expected_entities": 2,
                "structure": "comparison",
                "required": True,
            }
            obs = payload.get("observation", {})
            source_ids = [source.get("citation_id") for source in payload.get("sources", [])]
            payload["provenance"] = [
                {
                    "output_name": "absolute_difference",
                    "formula_id": "comparison.absolute_difference.v1",
                    "formula": "abs(top_book_revenue - customer_total_spending)",
                    "inputs": {
                        "top_book_revenue": obs.get("top_book_revenue"),
                        "customer_total_spending": obs.get("customer_total_spending"),
                    },
                    "source_citation_ids": source_ids,
                    "value": obs.get("absolute_difference"),
                },
                {
                    "output_name": "percentage_difference_relative_to_customer_spending",
                    "formula_id": "comparison.percentage_difference.v1",
                    "formula": "absolute_difference / customer_total_spending * 100",
                    "inputs": {
                        "absolute_difference": obs.get("absolute_difference"),
                        "customer_total_spending": obs.get("customer_total_spending"),
                    },
                    "source_citation_ids": source_ids,
                    "value": obs.get("percentage_difference_relative_to_customer_spending"),
                },
            ]
            return json.dumps(payload, ensure_ascii=False)

        if plan.operation == "lookup":
            if plan.dataset == self.customer_table:
                payload = json.loads(self.get_customer_order_summary(plan.entity_id or ""))
            elif plan.dataset == self.book_table:
                payload = json.loads(self.get_book_sales_summary(plan.entity_id or ""))
            else:
                raise ValueError("lookup is supported only for customer or book Gold datasets")
            if payload.get("status") == "success":
                payload["analytics_kind"] = "lookup"
                payload["answer_contract"] = {
                    "expected_entities": 1,
                    "structure": "entity_fact",
                    "required": True,
                }
                payload["provenance"] = []
            return json.dumps(payload, ensure_ascii=False)

        if plan.operation == "rank":
            try:
                if plan.dataset == self.customer_table:
                    if plan.sort_metric != "total_amount":
                        raise ValueError("Customer ranking currently supports total_amount only")
                    records = self.analytics_repository.top_customers(
                        tenant_id=scope.identity.tenant_id, limit=plan.limit
                    )
                    rows: list[dict[str, Any]] = []
                    sources: list[SourceReference] = []
                    provenance: list[dict[str, Any]] = []
                    for rank, record in enumerate(records, start=1):
                        row, masked = self._customer_observation(record)
                        source = self._source(
                            scope=scope,
                            decision=decision,
                            table=self.customer_table,
                            record_key=record.customer_id,
                            table_version=record.table_version,
                            as_of=record.as_of,
                            observation=row,
                            classification="confidential",
                            masked=masked,
                            title=f"Customer ranking row {record.customer_id}",
                        )
                        row["rank"] = rank
                        row["citation_id"] = source.citation_id
                        for metric_name in plan.derived_metrics:
                            value, lineage = self._derive_metric(
                                dataset=self.customer_table,
                                metric_name=metric_name,
                                row=row,
                                citation_id=source.citation_id,
                            )
                            row[metric_name] = value
                            provenance.append(lineage)
                        rows.append(row)
                        sources.append(source)
                    classifications = ["confidential"]
                elif plan.dataset == self.book_table:
                    if plan.sort_metric != "total_revenue":
                        raise ValueError("Book ranking currently supports total_revenue only")
                    records = self.analytics_repository.top_books(
                        tenant_id=scope.identity.tenant_id, limit=plan.limit
                    )
                    rows = []
                    sources = []
                    provenance = []
                    for rank, record in enumerate(records, start=1):
                        row = self._book_observation(record)
                        source = self._source(
                            scope=scope,
                            decision=decision,
                            table=self.book_table,
                            record_key=record.book_id,
                            table_version=record.table_version,
                            as_of=record.as_of,
                            observation=row,
                            classification="internal",
                            masked=False,
                            title=f"Book ranking row {record.book_id}",
                        )
                        row["rank"] = rank
                        row["citation_id"] = source.citation_id
                        for metric_name in plan.derived_metrics:
                            value, lineage = self._derive_metric(
                                dataset=self.book_table,
                                metric_name=metric_name,
                                row=row,
                                citation_id=source.citation_id,
                            )
                            row[metric_name] = value
                            provenance.append(lineage)
                        rows.append(row)
                        sources.append(source)
                    classifications = ["internal"]
                else:
                    raise ValueError("rank requires a concrete Gold dataset")
            except AnalyticsSourceUnavailableError:
                return self._unavailable_payload(scope, decision)
            if not rows:
                return self._not_found_payload(
                    scope, decision, "The authorized gold table returned no rows for this tenant."
                )
            return self._analytics_payload(
                scope=scope,
                decision=decision,
                analytics_kind="rank",
                observation={
                    "dataset": plan.dataset,
                    "sort_metric": plan.sort_metric,
                    "direction": plan.direction,
                    "derived_metrics": plan.derived_metrics,
                    "row_count": len(rows),
                    "rows": rows,
                },
                sources=sources,
                classifications=classifications,
                expected_entities=len(rows),
                structure="table_rows",
                provenance=provenance,
            )

        if plan.operation == "reconcile":
            try:
                customer, customer_version, customer_as_of = (
                    self.analytics_repository.aggregate_customer_totals(
                        tenant_id=scope.identity.tenant_id
                    )
                )
                books, book_version, book_as_of = self.analytics_repository.aggregate_book_totals(
                    tenant_id=scope.identity.tenant_id
                )
            except AnalyticsSourceUnavailableError:
                return self._unavailable_payload(scope, decision)
            if not customer or not books:
                return self._not_found_payload(
                    scope, decision, "Authorized Gold totals were unavailable for reconciliation."
                )
            customer_obs = {
                **customer,
                "delta_table": self.customer_table,
                "delta_version": customer_version,
                "grain": "one row per customer",
            }
            book_obs = {
                **books,
                "delta_table": self.book_table,
                "delta_version": book_version,
                "grain": "one row per book",
            }
            customer_source = self._source(
                scope=scope,
                decision=decision,
                table=self.customer_table,
                record_key="reconciliation-total",
                table_version=customer_version,
                as_of=customer_as_of,
                observation=customer_obs,
                classification="confidential",
                masked=False,
                title="Customer Gold reconciliation totals",
            )
            book_source = self._source(
                scope=scope,
                decision=decision,
                table=self.book_table,
                record_key="reconciliation-total",
                table_version=book_version,
                as_of=book_as_of,
                observation=book_obs,
                classification="internal",
                masked=False,
                title="Book Gold reconciliation totals",
            )
            semantic_source = self._semantic_source(scope=scope, decision=decision)
            amount_diff = self._money(float(customer["total_amount"])) - self._money(
                float(books["total_revenue"])
            )
            qty_diff = int(customer["total_quantity"]) - int(books["total_quantity"])
            order_counts_equal = int(customer["total_orders"]) == int(books["total_orders"])
            checks = [
                {
                    "metric": "amount_vs_revenue",
                    "customer_metric": "total_amount",
                    "book_metric": "total_revenue",
                    "customer_value": float(customer["total_amount"]),
                    "book_value": float(books["total_revenue"]),
                    "difference": float(amount_diff),
                    "equality_expected": True,
                    "observed_equal": amount_diff == 0,
                    "status": "matched" if amount_diff == 0 else "mismatch",
                    "reason": (
                        "total_amount and total_revenue are additive compatible metrics across "
                        "the governed customer and book Gold summary grains"
                    ),
                    "possible_double_counting": False,
                    "citation_ids": [
                        customer_source.citation_id,
                        book_source.citation_id,
                        semantic_source.citation_id,
                    ],
                },
                {
                    "metric": "quantity_vs_quantity",
                    "customer_metric": "total_quantity",
                    "book_metric": "total_quantity",
                    "customer_value": int(customer["total_quantity"]),
                    "book_value": int(books["total_quantity"]),
                    "difference": qty_diff,
                    "equality_expected": True,
                    "observed_equal": qty_diff == 0,
                    "status": "matched" if qty_diff == 0 else "mismatch",
                    "reason": (
                        "total_quantity is additive and explicitly compatible across the "
                        "governed customer and book Gold summary grains"
                    ),
                    "possible_double_counting": False,
                    "citation_ids": [
                        customer_source.citation_id,
                        book_source.citation_id,
                        semantic_source.citation_id,
                    ],
                },
                {
                    "metric": "summed_order_counts",
                    "customer_metric": "total_orders",
                    "book_metric": "total_orders",
                    "customer_value": int(customer["total_orders"]),
                    "book_value": int(books["total_orders"]),
                    "difference": None,
                    "equality_expected": False,
                    "observed_equal": order_counts_equal,
                    "status": "not_semantically_comparable",
                    "reason": (
                        "total_orders is a distinct-count metric at different grains; "
                        "summing across the book dimension can double count the same order, so "
                        "equal observed sums are not evidence that the metrics reconcile"
                    ),
                    "possible_double_counting": True,
                    "citation_ids": [
                        customer_source.citation_id,
                        book_source.citation_id,
                        semantic_source.citation_id,
                    ],
                },
            ]
            provenance = [
                {
                    "output_name": "amount_vs_revenue_difference",
                    "formula_id": "reconciliation.amount_revenue.v1",
                    "formula": "SUM(customer.total_amount) - SUM(book.total_revenue)",
                    "inputs": {
                        "customer_total_amount": customer["total_amount"],
                        "book_total_revenue": books["total_revenue"],
                    },
                    "source_citation_ids": [
                        customer_source.citation_id,
                        book_source.citation_id,
                    ],
                    "value": float(amount_diff),
                },
                {
                    "output_name": "quantity_difference",
                    "formula_id": "reconciliation.quantity.v1",
                    "formula": "SUM(customer.total_quantity) - SUM(book.total_quantity)",
                    "inputs": {
                        "customer_total_quantity": customer["total_quantity"],
                        "book_total_quantity": books["total_quantity"],
                    },
                    "source_citation_ids": [
                        customer_source.citation_id,
                        book_source.citation_id,
                    ],
                    "value": qty_diff,
                },
            ]
            return self._analytics_payload(
                scope=scope,
                decision=decision,
                analytics_kind="reconciliation",
                observation={
                    "customer_gold": customer_obs,
                    "book_gold": book_obs,
                    "checks": checks,
                    "semantic_registry_version": self.semantic_registry.version,
                },
                sources=[customer_source, book_source, semantic_source],
                classifications=["confidential", "internal"],
                expected_entities=len(checks),
                structure="reconciliation_rows",
                provenance=provenance,
            )

        raise ValueError(f"Unsupported analytics operation: {plan.operation}")

    def get_top_performers(self, dimension: str, limit: int = 5) -> str:
        """List the top customers by amount or top books by revenue from the gold tables."""
        scope = get_request_security_context()
        dimension = dimension.strip().casefold()
        if dimension not in _TOP_DIMENSIONS:
            raise ValueError("dimension must be one of: customers, books")
        bounded_limit = max(1, min(int(limit), self.max_rows))
        decision = self._authorize(scope)
        if not decision.allowed:
            return self._denied_payload(scope, decision)

        try:
            if dimension == "customers":
                customer_records = self.analytics_repository.top_customers(
                    tenant_id=scope.identity.tenant_id, limit=bounded_limit
                )
                table = self.customer_table
                classification = "confidential"
                rows: list[dict[str, Any]] = []
                masked_any = False
                for record in customer_records:
                    observation, masked = self._customer_observation(record)
                    masked_any = masked_any or masked
                    rows.append(observation)
                versions = [record.table_version for record in customer_records]
                as_of_values = [record.as_of for record in customer_records]
            else:
                book_records = self.analytics_repository.top_books(
                    tenant_id=scope.identity.tenant_id, limit=bounded_limit
                )
                table = self.book_table
                classification = "internal"
                masked_any = False
                rows = [self._book_observation(record) for record in book_records]
                versions = [record.table_version for record in book_records]
                as_of_values = [record.as_of for record in book_records]
        except AnalyticsSourceUnavailableError:
            return self._unavailable_payload(scope, decision)

        if not rows:
            return self._not_found_payload(
                scope, decision, "The authorized gold table returned no rows for this tenant."
            )

        table_version = max(versions)
        as_of = next((value for value in as_of_values if value is not None), None)
        observation = {
            "dimension": dimension,
            "requested_limit": bounded_limit,
            "row_count": len(rows),
            "rows": rows,
            "delta_table": table,
            "delta_version": table_version,
        }
        source = self._source(
            scope=scope,
            decision=decision,
            table=table,
            record_key=f"top-{dimension}-{bounded_limit}",
            table_version=table_version,
            as_of=as_of,
            observation=observation,
            classification=classification,
            masked=masked_any,
            title=f"Top {dimension} (limit {bounded_limit})",
        )
        return self._success_payload(
            scope=scope,
            decision=decision,
            observation=observation,
            source=source,
            classification=classification,
        )
