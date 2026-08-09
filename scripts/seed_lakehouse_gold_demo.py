"""Seed demo Delta Lake gold tables without running the Spark medallion pipeline.

Writes `gold_customer_order_summary` and `gold_book_sales_summary` via delta-rs with the
exact rows the DCEA Associate demo pipeline produces from its deterministic sample data,
so the agentic service can be exercised end to end on a laptop with no Spark runtime.

    python scripts/seed_lakehouse_gold_demo.py
    ANALYTICS_BACKEND=delta uvicorn nvidia_agentic_rag.api:app --port 8000
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = ROOT / "data" / "lakehouse" / "dcea_medallion.db"


def seed(dest_root: Path) -> None:
    import pyarrow as pa
    from deltalake import DeltaTable, write_deltalake

    customer_summary = pa.table(
        {
            "customer_id": ["C001", "C002", "C003"],
            "first_name": ["Ada", "Alan", "Grace"],
            "last_name": ["Lovelace", "Turing", "Hopper"],
            "total_orders": pa.array([2, 1, 1], type=pa.int64()),
            "total_quantity": pa.array([4, 2, 1], type=pa.int64()),
            "total_amount": pa.array([204.9, 91.0, 55.0], type=pa.float64()),
        }
    )
    book_summary = pa.table(
        {
            "book_id": ["B001", "B002", "B003"],
            "title": ["Spark Fundamentals", "Delta Lake Basics", "Data Engineering Exam"],
            "category": ["data", "data", "certification"],
            "total_orders": pa.array([1, 1, 2], type=pa.int64()),
            "total_quantity": pa.array([1, 2, 4], type=pa.int64()),
            "total_revenue": pa.array([39.9, 91.0, 220.0], type=pa.float64()),
        }
    )

    dest_root.mkdir(parents=True, exist_ok=True)
    for table_name, table in (
        ("gold_customer_order_summary", customer_summary),
        ("gold_book_sales_summary", book_summary),
    ):
        path = dest_root / table_name
        write_deltalake(str(path), table, mode="overwrite")
        version = DeltaTable(str(path)).version()
        print(f"seeded {table_name} ({table.num_rows} rows, delta version {version}) -> {path}")

    print(f"Demo lakehouse ready: {dest_root}")
    print("Enable with: ANALYTICS_BACKEND=delta " f"DELTA_WAREHOUSE_ROOT={dest_root}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args()
    seed(args.dest)


if __name__ == "__main__":
    main()
