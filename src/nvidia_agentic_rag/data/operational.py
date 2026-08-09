from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field


class OrderRecord(BaseModel):
    order_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=64)
    delivered_at: datetime | None = None
    product_category: str | None = Field(default=None, max_length=128)
    customer_reference: str | None = Field(default=None, max_length=128)
    record_version: int = Field(default=1, ge=1)
    updated_at: datetime


class OrderRepository(Protocol):
    def get_order(self, *, tenant_id: str, order_id: str) -> OrderRecord | None: ...


class JsonOrderRepository:
    """Local source-of-truth fixture; production uses PostgresOrderRepository."""

    def __init__(self, path: Path) -> None:
        self.path = path
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"orders": []}
        self._orders = {
            (item["tenant_id"].casefold(), item["order_id"].casefold()): OrderRecord.model_validate(
                item
            )
            for item in payload.get("orders", [])
        }

    def get_order(self, *, tenant_id: str, order_id: str) -> OrderRecord | None:
        return self._orders.get((tenant_id.casefold(), order_id.casefold()))


class PostgresOrderRepository:
    """Parameterized tenant-scoped query; database RLS remains the production enforcement layer."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def get_order(self, *, tenant_id: str, order_id: str) -> OrderRecord | None:
        import psycopg

        sql = """
            SELECT order_id, tenant_id, status, delivered_at, product_category,
                   customer_reference, record_version, updated_at
            FROM operational_order
            WHERE tenant_id = %s AND order_id = %s
        """
        with psycopg.connect(self.database_url) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
                    cursor.execute(sql, (tenant_id, order_id))
                    row = cursor.fetchone()
                    if row is None:
                        return None
                    columns = [description.name for description in cursor.description]
                    return OrderRecord.model_validate(dict(zip(columns, row, strict=True)))
