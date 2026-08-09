"""Sync curated Delta Lake gold tables from the DCEA medallion export into this repo.

Only `gold_*` serving tables cross the boundary into the agentic AI service; bronze and
silver medallion layers never leave the pipeline environment (data minimization, ADR-020).

Typical flow with the companion `dcea_demo_environment_clean` repo:

    1. In the DCEA container:   /workspace/scripts/run_business_demo.sh
    2. In the DCEA container:   /workspace/scripts/export_warehouse_for_api.sh
    3. On the host:
       python scripts/sync_lakehouse_gold.py \
         --source <dcea>/workspace/databricks_associate_training/warehouse/dcea_medallion.db

The destination defaults to `data/lakehouse/dcea_medallion.db`, which docker-compose
mounts read-only into the app container at `/app/data/lakehouse/dcea_medallion.db`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = ROOT / "data" / "lakehouse" / "dcea_medallion.db"
DEFAULT_TABLES = ("gold_customer_order_summary", "gold_book_sales_summary")


def _validate_delta_table(path: Path) -> None:
    if not path.is_dir():
        raise SystemExit(f"Source table directory not found: {path}")
    if not (path / "_delta_log").is_dir():
        raise SystemExit(f"Source is not a Delta table (missing _delta_log): {path}")


def sync(source_root: Path, dest_root: Path, tables: tuple[str, ...]) -> None:
    source_root = source_root.resolve()
    dest_root = dest_root.resolve()
    if source_root == dest_root:
        raise SystemExit("Source and destination must differ")

    for table in tables:
        if not table.startswith("gold_"):
            raise SystemExit(f"Refusing non-gold table '{table}': only the serving layer syncs")

    dest_root.mkdir(parents=True, exist_ok=True)
    for table in tables:
        source_table = source_root / table
        _validate_delta_table(source_table)
        dest_table = dest_root / table
        shutil.rmtree(dest_table, ignore_errors=True)
        shutil.copytree(source_table, dest_table)
        commits = sorted((dest_table / "_delta_log").glob("*.json"))
        latest = commits[-1].stem.lstrip("0") or "0" if commits else "?"
        print(f"synced {table} -> {dest_table} (delta version {latest})")

    print(f"Lakehouse gold sync complete: {dest_root}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="DCEA exported warehouse directory containing the gold_* Delta tables",
    )
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument(
        "--tables",
        nargs="+",
        default=list(DEFAULT_TABLES),
        help="Gold table names to sync (gold_* only)",
    )
    args = parser.parse_args()
    try:
        sync(args.source, args.dest, tuple(args.tables))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
