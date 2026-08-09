#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Protocol

from nvidia_agentic_rag.messaging.contracts import EventEnvelope
from nvidia_agentic_rag.messaging.rabbitmq import RabbitMQPublisher


class Sink(Protocol):
    def publish(self, event: EventEnvelope) -> None: ...
    def close(self) -> None: ...


class JsonlSink:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def publish(self, event: EventEnvelope) -> None:
        with self.path.open("a", encoding="utf-8") as sink:
            sink.write(event.model_dump_json() + "\n")
            sink.flush()
            os.fsync(sink.fileno())

    def close(self) -> None:
        return None


class RabbitSink:
    def __init__(self, url: str) -> None:
        self.publisher = RabbitMQPublisher(url)

    def publish(self, event: EventEnvelope) -> None:
        self.publisher.publish(event, routing_key=event.event_type)

    def close(self) -> None:
        self.publisher.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish transactional outbox events to JSONL or RabbitMQ."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("MAINTENANCE_DATABASE_URL", ""),
        help="Privileged PostgreSQL URL; role must be superuser or BYPASSRLS.",
    )
    parser.add_argument(
        "--sink",
        choices=["jsonl", "rabbitmq"],
        default=os.getenv("OUTBOX_SINK", "jsonl"),
    )
    parser.add_argument(
        "--sink-path",
        type=Path,
        default=Path(os.getenv("OUTBOX_JSONL_PATH", "storage/outbox/events.jsonl")),
    )
    parser.add_argument(
        "--rabbitmq-url",
        default=os.getenv("RABBITMQ_URL", "amqp://lab:labpass@rabbitmq:5672/%2F"),
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def _assert_maintenance_role(cursor: Any) -> str:
    cursor.execute(
        """
        SELECT current_user, rolsuper, rolbypassrls
        FROM pg_roles
        WHERE rolname = current_user
        """
    )
    role_name, is_superuser, bypass_rls = cursor.fetchone()
    if not (is_superuser or bypass_rls):
        raise SystemExit(f"outbox role {role_name!r} must be superuser or BYPASSRLS")
    return str(role_name)


def _publish_batch(database_url: str, sink: Sink, batch_size: int) -> int:
    """Publish then mark rows.

    If the broker confirms an event and PostgreSQL fails before published_at commits, that
    event will be published again on the next run. That is intentional at-least-once
    behavior; consumers deduplicate by event_id.
    """

    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                _assert_maintenance_role(cursor)
                cursor.execute(
                    """
                    SELECT event_id, aggregate_type, aggregate_id, event_type,
                           tenant_id, user_id, payload, created_at, publish_attempts
                    FROM agent_outbox
                    WHERE published_at IS NULL
                    ORDER BY created_at, event_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                    """,
                    (batch_size,),
                )
                rows = cursor.fetchall()
                if not rows:
                    return 0

                published_ids: list[str] = []
                for row in rows:
                    event = EventEnvelope.from_outbox_row(dict(row))
                    sink.publish(event)
                    published_ids.append(event.event_id)

                cursor.execute(
                    """
                    UPDATE agent_outbox
                    SET published_at = now(), publish_attempts = publish_attempts + 1
                    WHERE event_id = ANY(%s) AND published_at IS NULL
                    """,
                    (published_ids,),
                )
                return int(cursor.rowcount)


def _build_sink(args: argparse.Namespace) -> Sink:
    if args.sink == "rabbitmq":
        return RabbitSink(args.rabbitmq_url)
    return JsonlSink(args.sink_path)


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("MAINTENANCE_DATABASE_URL or --database-url is required")
    if args.batch_size <= 0:
        raise SystemExit("batch size must be positive")
    if args.poll_seconds < 0:
        raise SystemExit("poll seconds must not be negative")

    sink = _build_sink(args)
    published_total = 0
    try:
        while True:
            published = _publish_batch(args.database_url, sink, args.batch_size)
            published_total += published
            if args.once:
                print(
                    {
                        "published": published_total,
                        "sink": args.sink,
                        "delivery": "at_least_once; consumers deduplicate by event_id",
                    }
                )
                return 0
            if published == 0:
                time.sleep(args.poll_seconds)
    finally:
        sink.close()


if __name__ == "__main__":
    raise SystemExit(main())
