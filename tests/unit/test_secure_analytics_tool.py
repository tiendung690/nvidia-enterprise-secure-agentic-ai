from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from nvidia_agentic_rag.data.analytics import (
    AnalyticsSourceUnavailableError,
    BookSalesSummary,
    CustomerOrderSummary,
)
from nvidia_agentic_rag.identity import (
    IdentityContext,
    RequestSecurityContext,
    request_security_scope,
)
from nvidia_agentic_rag.policy import PolicyEngine
from nvidia_agentic_rag.security import DataClassification, DataMasker
from nvidia_agentic_rag.tools import SecureAnalyticsTools

AS_OF = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)


class Repository:
    def __init__(self, *, unavailable: bool = False, empty: bool = False) -> None:
        self.unavailable = unavailable
        self.empty = empty

    def _guard(self) -> None:
        if self.unavailable:
            raise AnalyticsSourceUnavailableError("warehouse offline")

    def _customer(self) -> CustomerOrderSummary:
        return CustomerOrderSummary(
            customer_id="C001",
            first_name="Ada",
            last_name="Lovelace",
            total_orders=2,
            total_quantity=4,
            total_amount=204.9,
            table_version=3,
            as_of=AS_OF,
        )

    def _book(self) -> BookSalesSummary:
        return BookSalesSummary(
            book_id="B003",
            title="Data Engineering Exam",
            category="certification",
            total_orders=2,
            total_quantity=4,
            total_revenue=220.0,
            table_version=3,
            as_of=AS_OF,
        )

    def get_customer_summary(self, *, tenant_id: str, customer_id: str):
        self._guard()
        if tenant_id == "tenant-a" and customer_id == "C001":
            return self._customer()
        return None

    def get_book_summary(self, *, tenant_id: str, book_id: str):
        self._guard()
        if tenant_id == "tenant-a" and book_id == "B003":
            return self._book()
        return None

    def top_customers(self, *, tenant_id: str, limit: int):
        self._guard()
        if self.empty or tenant_id != "tenant-a":
            return []
        return [self._customer()][:limit]

    def top_books(self, *, tenant_id: str, limit: int):
        self._guard()
        if self.empty or tenant_id != "tenant-a":
            return []
        return [self._book()][:limit]


def scope(*, roles=("analyst",), tenant="tenant-a", purpose="business-analytics"):
    return RequestSecurityContext(
        identity=IdentityContext(
            user_id="u",
            tenant_id=tenant,
            roles=roles,
            clearance=DataClassification.CONFIDENTIAL,
        ),
        purpose=purpose,
        answer_mode="enterprise_factual",
        request_id="r",
        policy_decision_id="pd",
    )


def tools(repo: Repository | None = None, *, max_rows: int = 3) -> SecureAnalyticsTools:
    return SecureAnalyticsTools(
        analytics_repository=repo or Repository(),
        policy_engine=PolicyEngine(
            policy_version="p1",
            allowed_purposes=("business-analytics", "operations-review"),
        ),
        masker=DataMasker(mode="pseudonymize", salt="s"),
        max_rows=max_rows,
    )


def test_customer_summary_returns_masked_versioned_lakehouse_source() -> None:
    with request_security_scope(scope()):
        payload = json.loads(tools().get_customer_order_summary("C001"))
    assert payload["status"] == "success"
    source = payload["sources"][0]
    assert source["citation_id"].startswith("D")
    assert source["source_kind"] == "database"
    assert source["corpus"] == "lakehouse-gold"
    assert source["section"] == "delta_version=3"
    assert source["source_version"] == 4
    assert source["masked"] is True
    assert source["source_id"] == "delta:gold_customer_order_summary:tenant-a:C001:v3"
    observation = payload["observation"]
    assert observation["delta_version"] == 3
    assert observation["total_amount"] == pytest.approx(204.9)
    assert "Ada" not in json.dumps(payload)
    assert "Lovelace" not in json.dumps(payload)


def test_book_summary_is_internal_and_unmasked() -> None:
    with request_security_scope(scope(purpose="operations-review", roles=("operations",))):
        payload = json.loads(tools().get_book_sales_summary("B003"))
    assert payload["status"] == "success"
    assert payload["observation"]["title"] == "Data Engineering Exam"
    assert payload["sources"][0]["classification"] == "internal"
    assert payload["sources"][0]["masked"] is False
    assert payload["policy_audit"]["status"] == "allowed"


def test_role_and_purpose_are_enforced() -> None:
    with request_security_scope(scope(roles=("developer",))):
        denied_role = json.loads(tools().get_customer_order_summary("C001"))
    assert denied_role["status"] == "policy_denied"

    with request_security_scope(scope(purpose="learning")):
        denied_purpose = json.loads(tools().get_top_performers("books"))
    assert denied_purpose["status"] == "policy_denied"
    assert denied_purpose["policy_audit"]["status"] == "denied"


def test_cross_tenant_records_stay_hidden() -> None:
    with request_security_scope(scope(tenant="tenant-b")):
        payload = json.loads(tools().get_customer_order_summary("C001"))
    assert payload["status"] == "not_found"
    assert payload["sources"] == []


def test_top_performers_clamps_limit_and_emits_one_aggregated_source() -> None:
    with request_security_scope(scope()):
        payload = json.loads(tools(max_rows=3).get_top_performers("customers", limit=99))
    assert payload["status"] == "success"
    observation = payload["observation"]
    assert observation["dimension"] == "customers"
    assert observation["requested_limit"] == 3
    assert observation["row_count"] == 1
    assert len(payload["sources"]) == 1
    assert payload["sources"][0]["document_id"] == "top-customers-3"

    with request_security_scope(scope()):
        books = json.loads(tools().get_top_performers("books", limit=2))
    assert books["observation"]["rows"][0]["book_id"] == "B003"
    assert books["sources"][0]["classification"] == "internal"


def test_top_performers_rejects_unknown_dimension_and_empty_results() -> None:
    with request_security_scope(scope()), pytest.raises(ValueError):
        tools().get_top_performers("tenants")

    with request_security_scope(scope()):
        payload = json.loads(tools(Repository(empty=True)).get_top_performers("books"))
    assert payload["status"] == "not_found"


def test_unavailable_warehouse_fails_closed_for_every_capability() -> None:
    broken = tools(Repository(unavailable=True))
    with request_security_scope(scope()):
        customer = json.loads(broken.get_customer_order_summary("C001"))
        book = json.loads(broken.get_book_sales_summary("B003"))
        top = json.loads(broken.get_top_performers("customers"))
    for payload in (customer, book, top):
        assert payload["status"] == "analytics_unavailable"
        assert payload["sources"] == []
        assert payload["policy_audit"]["status"] == "insufficient_context"


def test_key_validation_rejects_blank_and_oversized_ids() -> None:
    with request_security_scope(scope()), pytest.raises(ValueError):
        tools().get_customer_order_summary("   ")
    with request_security_scope(scope()), pytest.raises(ValueError):
        tools().get_book_sales_summary("B" * 129)


def test_mask_value_supports_all_dlp_modes() -> None:
    pseudonymized = DataMasker(mode="pseudonymize", salt="s").mask_value("CUSTOMER_NAME", "Ada L")
    assert pseudonymized.masked is True
    assert pseudonymized.text.startswith("[CUSTOMER_NAME_")
    assert pseudonymized.signals == ("customer_name",)

    redacted = DataMasker(mode="redact", salt="s").mask_value("customer name", "Ada L")
    assert redacted.text == "[CUSTOMERNAME_REDACTED]"

    passthrough = DataMasker(mode="off", salt="s").mask_value("CUSTOMER_NAME", "Ada L")
    assert passthrough.masked is False
    assert passthrough.text == "Ada L"

    empty = DataMasker(mode="pseudonymize", salt="s").mask_value("CUSTOMER_NAME", "")
    assert empty.masked is False


def test_customer_to_top_book_comparison_is_deterministic_and_multi_source() -> None:
    with request_security_scope(scope()):
        payload = json.loads(tools().compare_customer_spending_to_top_book("C001"))

    assert payload["status"] == "success"
    observation = payload["observation"]
    assert observation["customer_total_spending"] == pytest.approx(204.90)
    assert observation["top_book_revenue"] == pytest.approx(220.00)
    assert observation["larger_value"] == "highest_revenue_book"
    assert observation["absolute_difference"] == pytest.approx(15.10)
    assert observation["percentage_difference_relative_to_customer_spending"] == pytest.approx(7.37)
    assert observation["calculation"]["difference"] == "abs(220.00 - 204.90) = 15.10"
    assert len(payload["sources"]) == 2
    assert {source["file_name"] for source in payload["sources"]} == {
        "gold_customer_order_summary",
        "gold_book_sales_summary",
    }
    assert payload["policy_audit"]["authorized_source_count"] == 2
    assert "Ada" not in json.dumps(payload)


def test_customer_to_top_book_comparison_handles_missing_customer() -> None:
    with request_security_scope(scope()):
        payload = json.loads(tools().compare_customer_spending_to_top_book("C404"))
    assert payload["status"] == "not_found"
    assert payload["sources"] == []
