#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply trace retention and expire governed memory in PostgreSQL."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("MAINTENANCE_DATABASE_URL", ""),
        help=(
            "Privileged PostgreSQL URL; defaults to MAINTENANCE_DATABASE_URL. "
            "The role must be superuser or BYPASSRLS."
        ),
    )
    parser.add_argument(
        "--trace-retention-days",
        type=int,
        default=int(os.getenv("TRACE_RETENTION_DAYS", "30")),
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("MAINTENANCE_DATABASE_URL or --database-url is required")
    if args.trace_retention_days <= 0:
        raise SystemExit("trace retention days must be positive")

    import psycopg

    with psycopg.connect(args.database_url) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT current_user, rolsuper, rolbypassrls
                    FROM pg_roles
                    WHERE rolname = current_user
                    """
                )
                role_name, is_superuser, bypass_rls = cursor.fetchone()
                if not (is_superuser or bypass_rls):
                    raise SystemExit(
                        f"maintenance role {role_name!r} must be superuser or BYPASSRLS"
                    )

                cursor.execute(
                    """
                    SELECT count(*) FROM agent_run_trace
                    WHERE started_at < now() - (%s * interval '1 day')
                    """,
                    (args.trace_retention_days,),
                )
                trace_count = int(cursor.fetchone()[0])
                cursor.execute(
                    """
                    SELECT memory_id, tenant_id, user_id
                    FROM agent_memory
                    WHERE status IN ('active','provisional')
                      AND effective_until IS NOT NULL
                      AND effective_until <= now()
                    FOR UPDATE
                    """
                )
                expired_rows = cursor.fetchall()
                memory_count = len(expired_rows)

                if not args.dry_run:
                    cursor.execute(
                        """
                        DELETE FROM agent_run_trace
                        WHERE started_at < now() - (%s * interval '1 day')
                        """,
                        (args.trace_retention_days,),
                    )
                    for memory_id, tenant_id, user_id in expired_rows:
                        cursor.execute(
                            """
                            INSERT INTO agent_outbox (
                                event_id, aggregate_type, aggregate_id, event_type,
                                tenant_id, user_id, payload
                            ) VALUES (%s, 'memory', %s, 'memory.expired', %s, %s, %s::jsonb)
                            """,
                            (
                                "EVT-" + uuid.uuid4().hex[:20].upper(),
                                memory_id,
                                tenant_id,
                                user_id,
                                json.dumps({"memory_id": memory_id}),
                            ),
                        )
                    if expired_rows:
                        cursor.execute(
                            """
                            UPDATE agent_memory
                            SET status='deleted', updated_at=now()
                            WHERE memory_id = ANY(%s)
                            """,
                            ([row[0] for row in expired_rows],),
                        )

    print(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database_role": role_name,
            "dry_run": args.dry_run,
            "trace_rows": trace_count,
            "expired_memory_rows": memory_count,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
