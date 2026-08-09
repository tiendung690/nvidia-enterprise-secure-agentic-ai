from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field


class CustomerOrderSummary(BaseModel):
    """One row of the lakehouse `gold_customer_order_summary` serving aggregate."""

    customer_id: str = Field(min_length=1, max_length=128)
    first_name: str | None = Field(default=None, max_length=256)
    last_name: str | None = Field(default=None, max_length=256)
    total_orders: int = Field(ge=0)
    total_quantity: int = Field(ge=0)
    total_amount: float
    table_version: int = Field(ge=0)
    as_of: datetime | None = None


class BookSalesSummary(BaseModel):
    """One row of the lakehouse `gold_book_sales_summary` serving aggregate."""

    book_id: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=512)
    category: str | None = Field(default=None, max_length=128)
    total_orders: int = Field(ge=0)
    total_quantity: int = Field(ge=0)
    total_revenue: float
    table_version: int = Field(ge=0)
    as_of: datetime | None = None


class AnalyticsSourceUnavailableError(RuntimeError):
    """The lakehouse gold table cannot be opened or read; callers must fail closed."""


class AnalyticsRepository(Protocol):
    def get_customer_summary(
        self, *, tenant_id: str, customer_id: str
    ) -> CustomerOrderSummary | None: ...

    def get_book_summary(self, *, tenant_id: str, book_id: str) -> BookSalesSummary | None: ...

    def top_customers(self, *, tenant_id: str, limit: int) -> list[CustomerOrderSummary]: ...

    def top_books(self, *, tenant_id: str, limit: int) -> list[BookSalesSummary]: ...

    def aggregate_customer_totals(
        self, *, tenant_id: str
    ) -> tuple[dict[str, float | int], int, datetime | None]: ...

    def aggregate_book_totals(
        self, *, tenant_id: str
    ) -> tuple[dict[str, float | int], int, datetime | None]: ...

    def version_fingerprint(self, *, tenant_id: str) -> str: ...


@dataclass(frozen=True)
class _Snapshot:
    table: Any
    version: int
    as_of: datetime | None
    loaded_monotonic: float


def _normalize_key(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


class DeltaGoldAnalyticsRepository:
    """Read-only, tenant-declared reader over curated Delta Lake gold tables.

    The medallion pipeline owns writes; this service only consumes the curated serving
    contract through delta-rs. Row reads use a short-lived pinned snapshot. Cache freshness uses
    ``version_fingerprint`` which bypasses that row TTL and checks Delta metadata directly.
    """

    _CUSTOMER_COLUMNS = (
        "customer_id",
        "first_name",
        "last_name",
        "total_orders",
        "total_quantity",
        "total_amount",
    )
    _BOOK_COLUMNS = (
        "book_id",
        "title",
        "category",
        "total_orders",
        "total_quantity",
        "total_revenue",
    )

    def __init__(
        self,
        *,
        warehouse_root: Path,
        customer_table: str,
        book_table: str,
        owner_tenant_id: str,
        max_rows: int = 10,
        snapshot_ttl_seconds: float = 60.0,
    ) -> None:
        self.warehouse_root = warehouse_root
        self.customer_table = customer_table
        self.book_table = book_table
        self.owner_tenant_id = owner_tenant_id
        self.max_rows = max(1, max_rows)
        self.snapshot_ttl_seconds = max(0.0, snapshot_ttl_seconds)
        self._lock = threading.Lock()
        self._snapshots: dict[str, _Snapshot] = {}

    def _tenant_allowed(self, tenant_id: str) -> bool:
        return _normalize_key(tenant_id) == _normalize_key(self.owner_tenant_id)

    def _open_table(self, table_name: str) -> _Snapshot:
        from deltalake import DeltaTable

        table_path = self.warehouse_root / table_name
        try:
            table = DeltaTable(str(table_path))
            version = int(table.version())
        except Exception as exc:
            raise AnalyticsSourceUnavailableError(
                f"Delta gold table '{table_name}' is unavailable at {table_path}"
            ) from exc
        as_of: datetime | None = None
        try:
            history = table.history(1)
            timestamp_ms = history[0].get("timestamp") if history else None
            if isinstance(timestamp_ms, (int, float)):
                as_of = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=UTC)
        except Exception:
            as_of = None
        return _Snapshot(
            table=table,
            version=version,
            as_of=as_of,
            loaded_monotonic=time.monotonic(),
        )

    def _snapshot(self, table_name: str) -> _Snapshot:
        with self._lock:
            cached = self._snapshots.get(table_name)
            if (
                cached is not None
                and time.monotonic() - cached.loaded_monotonic < self.snapshot_ttl_seconds
            ):
                return cached
            snapshot = self._open_table(table_name)
            self._snapshots[table_name] = snapshot
            return snapshot

    @staticmethod
    def _read_rows(snapshot: _Snapshot, columns: tuple[str, ...]) -> list[dict[str, Any]]:
        try:
            arrow_table = snapshot.table.to_pyarrow_table(columns=list(columns))
            rows: list[dict[str, Any]] = arrow_table.to_pylist()
        except Exception as exc:
            raise AnalyticsSourceUnavailableError(
                "Delta gold table read failed for pinned snapshot"
            ) from exc
        return rows

    @staticmethod
    def _sum_columns(
        snapshot: _Snapshot, columns: tuple[str, ...]
    ) -> dict[str, float | int]:
        try:
            import pyarrow.compute as pc

            table = snapshot.table.to_pyarrow_table(columns=list(columns))
            totals: dict[str, float | int] = {}
            for column in columns:
                value = pc.sum(table[column]).as_py()
                totals[column] = 0 if value is None else value
            return totals
        except Exception as exc:
            raise AnalyticsSourceUnavailableError(
                "Delta gold aggregate scan failed for pinned snapshot"
            ) from exc

    @staticmethod
    def _match_one(
        rows: list[dict[str, Any]], key_column: str, key: str
    ) -> dict[str, Any] | None:
        normalized = _normalize_key(key)
        for row in rows:
            if _normalize_key(row.get(key_column)) == normalized:
                return row
        return None

    @staticmethod
    def _top_rows(
        rows: list[dict[str, Any]], *, metric: str, key_column: str, limit: int
    ) -> list[dict[str, Any]]:
        ordered = sorted(
            rows,
            key=lambda row: (-float(row.get(metric) or 0.0), _normalize_key(row.get(key_column))),
        )
        return ordered[:limit]

    def _customer_model(self, row: dict[str, Any], snapshot: _Snapshot) -> CustomerOrderSummary:
        return CustomerOrderSummary.model_validate(
            {**row, "table_version": snapshot.version, "as_of": snapshot.as_of}
        )

    def _book_model(self, row: dict[str, Any], snapshot: _Snapshot) -> BookSalesSummary:
        return BookSalesSummary.model_validate(
            {**row, "table_version": snapshot.version, "as_of": snapshot.as_of}
        )

    def get_customer_summary(
        self, *, tenant_id: str, customer_id: str
    ) -> CustomerOrderSummary | None:
        if not self._tenant_allowed(tenant_id):
            return None
        snapshot = self._snapshot(self.customer_table)
        rows = self._read_rows(snapshot, self._CUSTOMER_COLUMNS)
        row = self._match_one(rows, "customer_id", customer_id)
        return self._customer_model(row, snapshot) if row is not None else None

    def get_book_summary(self, *, tenant_id: str, book_id: str) -> BookSalesSummary | None:
        if not self._tenant_allowed(tenant_id):
            return None
        snapshot = self._snapshot(self.book_table)
        rows = self._read_rows(snapshot, self._BOOK_COLUMNS)
        row = self._match_one(rows, "book_id", book_id)
        return self._book_model(row, snapshot) if row is not None else None

    def top_customers(self, *, tenant_id: str, limit: int) -> list[CustomerOrderSummary]:
        if not self._tenant_allowed(tenant_id):
            return []
        bounded = max(1, min(limit, self.max_rows))
        snapshot = self._snapshot(self.customer_table)
        rows = self._read_rows(snapshot, self._CUSTOMER_COLUMNS)
        top = self._top_rows(rows, metric="total_amount", key_column="customer_id", limit=bounded)
        return [self._customer_model(row, snapshot) for row in top]

    def top_books(self, *, tenant_id: str, limit: int) -> list[BookSalesSummary]:
        if not self._tenant_allowed(tenant_id):
            return []
        bounded = max(1, min(limit, self.max_rows))
        snapshot = self._snapshot(self.book_table)
        rows = self._read_rows(snapshot, self._BOOK_COLUMNS)
        top = self._top_rows(rows, metric="total_revenue", key_column="book_id", limit=bounded)
        return [self._book_model(row, snapshot) for row in top]

    def aggregate_customer_totals(
        self, *, tenant_id: str
    ) -> tuple[dict[str, float | int], int, datetime | None]:
        if not self._tenant_allowed(tenant_id):
            return {}, -1, None
        snapshot = self._snapshot(self.customer_table)
        totals = self._sum_columns(
            snapshot, ("total_orders", "total_quantity", "total_amount")
        )
        return totals, snapshot.version, snapshot.as_of

    def aggregate_book_totals(
        self, *, tenant_id: str
    ) -> tuple[dict[str, float | int], int, datetime | None]:
        if not self._tenant_allowed(tenant_id):
            return {}, -1, None
        snapshot = self._snapshot(self.book_table)
        totals = self._sum_columns(
            snapshot, ("total_orders", "total_quantity", "total_revenue")
        )
        return totals, snapshot.version, snapshot.as_of

    def version_fingerprint(self, *, tenant_id: str) -> str:
        """Tenant + relevant Delta versions used by the answer-cache fingerprint."""
        if not self._tenant_allowed(tenant_id):
            return "analytics-denied"
        from deltalake import DeltaTable

        versions: list[str] = []
        current_versions: dict[str, int] = {}
        for table_name in (self.customer_table, self.book_table):
            table_path = self.warehouse_root / table_name
            try:
                version = int(DeltaTable(str(table_path)).version())
            except Exception as exc:
                raise AnalyticsSourceUnavailableError(
                    f"Delta gold table '{table_name}' is unavailable at {table_path}"
                ) from exc
            current_versions[table_name] = version
            versions.append(f"{table_name}:v{version}")

        # The cache fingerprint must describe the same source version a subsequent tool read will
        # use. If Delta advanced while a row snapshot is still inside its TTL, invalidate that
        # snapshot now; otherwise a vN+1 cache key could accidentally store a vN answer.
        with self._lock:
            for table_name, current_version in current_versions.items():
                cached = self._snapshots.get(table_name)
                if cached is not None and cached.version != current_version:
                    self._snapshots.pop(table_name, None)

        raw = f"tenant={_normalize_key(tenant_id)}|" + "|".join(versions)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
