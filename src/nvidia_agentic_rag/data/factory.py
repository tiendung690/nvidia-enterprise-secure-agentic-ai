from __future__ import annotations

from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.data.analytics import (
    AnalyticsRepository,
    DeltaGoldAnalyticsRepository,
)
from nvidia_agentic_rag.data.document_registry import (
    DocumentRegistry,
    JsonDocumentRegistry,
    PostgresDocumentRegistry,
)
from nvidia_agentic_rag.data.operational import (
    JsonOrderRepository,
    OrderRepository,
    PostgresOrderRepository,
)


def build_document_registry(settings: Settings) -> DocumentRegistry:
    if settings.document_registry_backend == "postgres":
        return PostgresDocumentRegistry(
            settings.document_registry_database_url or settings.database_url
        )
    return JsonDocumentRegistry(settings.document_security_manifest)


def build_order_repository(settings: Settings) -> OrderRepository:
    if settings.operational_data_backend == "postgres":
        return PostgresOrderRepository(settings.database_url)
    return JsonOrderRepository(settings.operational_orders_file)


def build_analytics_repository(settings: Settings) -> AnalyticsRepository | None:
    if settings.analytics_backend != "delta":
        return None
    return DeltaGoldAnalyticsRepository(
        warehouse_root=settings.delta_warehouse_root,
        customer_table=settings.delta_gold_customer_summary_table,
        book_table=settings.delta_gold_book_sales_table,
        owner_tenant_id=settings.analytics_tenant_id,
        max_rows=settings.analytics_max_rows,
        snapshot_ttl_seconds=float(settings.analytics_snapshot_ttl_seconds),
    )
