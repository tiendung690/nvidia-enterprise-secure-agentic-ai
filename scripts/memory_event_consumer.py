#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from typing import Any

import pika
import psycopg

from nvidia_agentic_rag.messaging.contracts import EventEnvelope
from nvidia_agentic_rag.messaging.rabbitmq import (
    RabbitMQPublisher,
    RabbitMQTopology,
    bump_retry_properties,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RabbitMQ lab consumer: manual ACK + SQL inbox + bounded retry + DLQ."
    )
    parser.add_argument(
        "--rabbitmq-url",
        default=os.getenv("RABBITMQ_URL", "amqp://lab:labpass@rabbitmq:5672/%2F"),
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv(
            "CONSUMER_DATABASE_URL",
            "postgresql://agentic_admin:agentic_admin@postgres:5432/agentic_ai",
        ),
    )
    parser.add_argument("--queue", default=os.getenv("MEMORY_EVENT_QUEUE", "agent.memory.events"))
    parser.add_argument("--binding", default=os.getenv("MEMORY_EVENT_BINDING", "memory.#"))
    parser.add_argument("--prefetch", type=int, default=int(os.getenv("MEMORY_PREFETCH", "10")))
    parser.add_argument("--max-retries", type=int, default=int(os.getenv("MQ_MAX_RETRIES", "3")))
    parser.add_argument(
        "--retry-delay-ms", type=int, default=int(os.getenv("MQ_RETRY_DELAY_MS", "5000"))
    )
    parser.add_argument(
        "--consumer-name", default=os.getenv("MEMORY_CONSUMER_NAME", "memory-audit-consumer")
    )
    return parser.parse_args()


def _declare_topology(channel: Any, *, queue: str, binding: str, retry_delay_ms: int) -> None:
    topology = RabbitMQTopology()
    channel.exchange_declare(exchange=topology.exchange, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=topology.retry_exchange, exchange_type="topic", durable=True)
    channel.exchange_declare(
        exchange=topology.dead_letter_exchange, exchange_type="topic", durable=True
    )

    dlq = f"{queue}.dlq"
    retry_queue = f"{queue}.retry"

    channel.queue_declare(
        queue=queue,
        durable=True,
        arguments={"x-dead-letter-exchange": topology.dead_letter_exchange},
    )
    channel.queue_bind(queue=queue, exchange=topology.exchange, routing_key=binding)

    channel.queue_declare(queue=dlq, durable=True)
    channel.queue_bind(queue=dlq, exchange=topology.dead_letter_exchange, routing_key="#")

    # Retry queue waits, then dead-letters back to the main exchange preserving routing key.
    channel.queue_declare(
        queue=retry_queue,
        durable=True,
        arguments={
            "x-message-ttl": retry_delay_ms,
            "x-dead-letter-exchange": topology.exchange,
        },
    )
    channel.queue_bind(queue=retry_queue, exchange=topology.retry_exchange, routing_key="#")


def _record_dlq(
    database_url: str,
    *,
    consumer_name: str,
    event: EventEnvelope | None,
    error_class: str,
    error_message: str,
    retry_count: int,
    raw_body: bytes,
) -> None:
    payload: dict[str, Any]
    if event is not None:
        payload = event.model_dump(mode="json")
    else:
        payload = {"raw_body": raw_body.decode("utf-8", errors="replace")[:16000]}
    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO agent_dlq_record (
                        consumer_name, event_id, event_type, error_class, error_message,
                        retry_count, correlation_id, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        consumer_name,
                        event.event_id if event else None,
                        event.event_type if event else None,
                        error_class,
                        error_message[:2000],
                        retry_count,
                        event.correlation_id if event else None,
                        json.dumps(payload),
                    ),
                )


def _process_once(database_url: str, *, consumer_name: str, event: EventEnvelope) -> bool:
    """Return True only when this delivery caused the business side effect.

    The inbox insert and the demonstration side effect (status transition) share one DB
    transaction. A duplicate event_id therefore becomes a no-op that is safe to ACK.
    """

    payload_json = event.model_dump_json()
    payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO agent_message_inbox (
                        consumer_name, event_id, event_type, payload_hash, correlation_id,
                        tenant_id, status
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'processing')
                    ON CONFLICT (consumer_name, event_id) DO NOTHING
                    RETURNING event_id
                    """,
                    (
                        consumer_name,
                        event.event_id,
                        event.event_type,
                        payload_hash,
                        event.correlation_id,
                        event.tenant_id,
                    ),
                )
                inserted = cursor.fetchone()
                if not inserted:
                    return False

                # Lab side effect: durable processed state. Replace this with a domain write,
                # audit projection, cache invalidation, notification, etc.
                cursor.execute(
                    """
                    UPDATE agent_message_inbox
                    SET status='processed', processed_at=now(), last_error=NULL
                    WHERE consumer_name=%s AND event_id=%s
                    """,
                    (consumer_name, event.event_id),
                )
                return True


def main() -> int:
    args = parse_args()
    if args.max_retries < 0 or args.prefetch <= 0:
        raise SystemExit("max retries must be >= 0 and prefetch must be > 0")

    parameters = pika.URLParameters(args.rabbitmq_url)
    parameters.heartbeat = 30
    parameters.blocked_connection_timeout = 30
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    _declare_topology(
        channel,
        queue=args.queue,
        binding=args.binding,
        retry_delay_ms=args.retry_delay_ms,
    )
    channel.basic_qos(prefetch_count=args.prefetch)
    retry_publisher = RabbitMQPublisher(args.rabbitmq_url)
    topology = RabbitMQTopology()

    def on_message(ch: Any, method: Any, properties: pika.BasicProperties, body: bytes) -> None:
        retry_count = int((properties.headers or {}).get("x-lab-retry-count", 0))
        event: EventEnvelope | None = None
        try:
            event = EventEnvelope.model_validate_json(body)
            processed = _process_once(
                args.database_url,
                consumer_name=args.consumer_name,
                event=event,
            )
            print(
                json.dumps(
                    {
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "result": "processed" if processed else "duplicate_suppressed",
                        "retry_count": retry_count,
                    },
                    sort_keys=True,
                )
            )
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except (json.JSONDecodeError, ValueError) as exc:
            _record_dlq(
                args.database_url,
                consumer_name=args.consumer_name,
                event=event,
                error_class="permanent",
                error_message=str(exc),
                retry_count=retry_count,
                raw_body=body,
            )
            # requeue=False routes the rejected delivery to the configured DLX.
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        except (psycopg.OperationalError, psycopg.errors.SerializationFailure) as exc:
            if retry_count < args.max_retries:
                next_retry = retry_count + 1
                retry_publisher.publish_raw(
                    exchange=topology.retry_exchange,
                    routing_key=method.routing_key,
                    body=body,
                    properties=bump_retry_properties(properties, next_retry),
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)
                print(
                    json.dumps(
                        {
                            "result": "scheduled_retry",
                            "retry_count": next_retry,
                            "error": type(exc).__name__,
                        }
                    )
                )
            else:
                _record_dlq(
                    args.database_url,
                    consumer_name=args.consumer_name,
                    event=event,
                    error_class="transient_exhausted",
                    error_message=str(exc),
                    retry_count=retry_count,
                    raw_body=body,
                )
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        except Exception as exc:
            # Unknown/ambiguous failures get bounded retry, then DLQ.
            if retry_count < args.max_retries:
                next_retry = retry_count + 1
                retry_publisher.publish_raw(
                    exchange=topology.retry_exchange,
                    routing_key=method.routing_key,
                    body=body,
                    properties=bump_retry_properties(properties, next_retry),
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)
            else:
                _record_dlq(
                    args.database_url,
                    consumer_name=args.consumer_name,
                    event=event,
                    error_class="ambiguous_exhausted",
                    error_message=str(exc),
                    retry_count=retry_count,
                    raw_body=body,
                )
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    channel.basic_consume(queue=args.queue, on_message_callback=on_message, auto_ack=False)
    print(
        json.dumps(
            {
                "status": "ready",
                "queue": args.queue,
                "binding": args.binding,
                "prefetch": args.prefetch,
                "max_retries": args.max_retries,
            }
        )
    )
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    finally:
        retry_publisher.close()
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
