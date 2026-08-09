from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest
from deltalake import DeltaTable, write_deltalake

from nvidia_agentic_rag.data.analytics import (
    AnalyticsSourceUnavailableError,
    DeltaGoldAnalyticsRepository,
    _Snapshot,
)

CUSTOMER_TABLE = "gold_customer_order_summary"
BOOK_TABLE = "gold_book_sales_summary"


def _customer_rows() -> pa.Table:
    return pa.table(
        {
            "customer_id": ["C001", "C002", "C003"],
            "first_name": ["Ada", "Alan", "Grace"],
            "last_name": ["Lovelace", "Turing", "Hopper"],
            "total_orders": pa.array([2, 1, 1], type=pa.int64()),
            "total_quantity": pa.array([4, 2, 1], type=pa.int64()),
            "total_amount": pa.array([204.9, 91.0, 55.0], type=pa.float64()),
        }
    )


def _book_rows() -> pa.Table:
    return pa.table(
        {
            "book_id": ["B001", "B002", "B003"],
            "title": ["Spark Fundamentals", "Delta Lake Basics", "Data Engineering Exam"],
            "category": ["data", "data", "certification"],
            "total_orders": pa.array([1, 1, 2], type=pa.int64()),
            "total_quantity": pa.array([1, 2, 4], type=pa.int64()),
            "total_revenue": pa.array([39.9, 91.0, 220.0], type=pa.float64()),
        }
    )


def seed_warehouse(root: Path) -> None:
    write_deltalake(str(root / CUSTOMER_TABLE), _customer_rows(), mode="overwrite")
    write_deltalake(str(root / BOOK_TABLE), _book_rows(), mode="overwrite")


def repository(root: Path, **overrides) -> DeltaGoldAnalyticsRepository:
    values = {
        "warehouse_root": root,
        "customer_table": CUSTOMER_TABLE,
        "book_table": BOOK_TABLE,
        "owner_tenant_id": "tenant-a",
        "max_rows": 10,
        "snapshot_ttl_seconds": 60.0,
    }
    values.update(overrides)
    return DeltaGoldAnalyticsRepository(**values)


def test_exact_lookup_is_case_insensitive_and_carries_delta_version(tmp_path) -> None:
    seed_warehouse(tmp_path)
    repo = repository(tmp_path)

    record = repo.get_customer_summary(tenant_id="Tenant-A", customer_id="c001")
    assert record is not None
    assert record.first_name == "Ada"
    assert record.total_orders == 2
    assert record.total_amount == pytest.approx(204.9)
    assert record.table_version == 0
    assert record.as_of is not None

    book = repo.get_book_summary(tenant_id="tenant-a", book_id="B003")
    assert book is not None
    assert book.category == "certification"
    assert book.total_revenue == pytest.approx(220.0)


def test_unknown_ids_return_none(tmp_path) -> None:
    seed_warehouse(tmp_path)
    repo = repository(tmp_path)
    assert repo.get_customer_summary(tenant_id="tenant-a", customer_id="C999") is None
    assert repo.get_book_summary(tenant_id="tenant-a", book_id="B999") is None


def test_cross_tenant_reads_look_like_not_found(tmp_path) -> None:
    seed_warehouse(tmp_path)
    repo = repository(tmp_path)
    assert repo.get_customer_summary(tenant_id="tenant-b", customer_id="C001") is None
    assert repo.get_book_summary(tenant_id="tenant-b", book_id="B001") is None
    assert repo.top_customers(tenant_id="tenant-b", limit=5) == []
    assert repo.top_books(tenant_id="tenant-b", limit=5) == []


def test_top_reads_are_sorted_desc_and_clamped_to_max_rows(tmp_path) -> None:
    seed_warehouse(tmp_path)
    repo = repository(tmp_path, max_rows=2)

    top_customers = repo.top_customers(tenant_id="tenant-a", limit=50)
    assert [record.customer_id for record in top_customers] == ["C001", "C002"]

    top_books = repo.top_books(tenant_id="tenant-a", limit=50)
    assert [record.book_id for record in top_books] == ["B003", "B002"]

    single = repo.top_books(tenant_id="tenant-a", limit=0)
    assert [record.book_id for record in single] == ["B003"]


def test_missing_table_fails_closed(tmp_path) -> None:
    repo = repository(tmp_path)
    with pytest.raises(AnalyticsSourceUnavailableError):
        repo.get_customer_summary(tenant_id="tenant-a", customer_id="C001")


def test_snapshot_ttl_pins_version_until_expiry(tmp_path) -> None:
    seed_warehouse(tmp_path)
    pinned = repository(tmp_path, snapshot_ttl_seconds=300.0)
    first = pinned.get_book_summary(tenant_id="tenant-a", book_id="B001")
    assert first is not None
    assert first.table_version == 0

    write_deltalake(str(tmp_path / BOOK_TABLE), _book_rows(), mode="append")

    still_pinned = pinned.get_book_summary(tenant_id="tenant-a", book_id="B001")
    assert still_pinned is not None
    assert still_pinned.table_version == 0

    fresh = repository(tmp_path, snapshot_ttl_seconds=0.0)
    reloaded = fresh.get_book_summary(tenant_id="tenant-a", book_id="B001")
    assert reloaded is not None
    assert reloaded.table_version == 1


def test_commit_history_failure_degrades_to_none_as_of(tmp_path, monkeypatch) -> None:
    seed_warehouse(tmp_path)

    def broken_history(self, limit=None):
        raise RuntimeError("history unavailable")

    monkeypatch.setattr(DeltaTable, "history", broken_history)
    repo = repository(tmp_path)
    record = repo.get_customer_summary(tenant_id="tenant-a", customer_id="C001")
    assert record is not None
    assert record.as_of is None


def test_read_failure_on_pinned_snapshot_fails_closed(tmp_path) -> None:
    seed_warehouse(tmp_path)
    repo = repository(tmp_path)

    class BrokenTable:
        def to_pyarrow_table(self, columns=None):
            raise OSError("parquet unreadable")

    snapshot = _Snapshot(table=BrokenTable(), version=0, as_of=None, loaded_monotonic=0.0)
    with pytest.raises(AnalyticsSourceUnavailableError):
        repo._read_rows(snapshot, repo._CUSTOMER_COLUMNS)
