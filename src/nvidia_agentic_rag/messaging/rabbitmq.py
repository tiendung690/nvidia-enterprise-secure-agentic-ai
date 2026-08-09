from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pika

from .contracts import EventEnvelope


@dataclass(frozen=True)
class RabbitMQTopology:
    exchange: str = "enterprise.events"
    retry_exchange: str = "enterprise.retry"
    dead_letter_exchange: str = "enterprise.dlx"


class RabbitMQPublisher:
    """Small blocking publisher for dispatcher/worker processes.

    The application/domain layer depends on EventPublisher, not Pika. The adapter uses
    durable topic exchanges, persistent messages and broker publisher confirmations.
    """

    def __init__(
        self,
        url: str,
        *,
        topology: RabbitMQTopology | None = None,
    ) -> None:
        self.url = url
        self.topology = topology or RabbitMQTopology()
        self._connection: pika.BlockingConnection | None = None
        self._channel: Any | None = None

    def _ensure_channel(self) -> Any:
        if self._connection is not None and self._connection.is_open and self._channel is not None:
            return self._channel
        parameters = pika.URLParameters(self.url)
        parameters.heartbeat = 30
        parameters.blocked_connection_timeout = 30
        self._connection = pika.BlockingConnection(parameters)
        self._channel = self._connection.channel()
        self._channel.exchange_declare(
            exchange=self.topology.exchange,
            exchange_type="topic",
            durable=True,
        )
        self._channel.confirm_delivery()
        return self._channel

    def publish(self, event: EventEnvelope, *, routing_key: str | None = None) -> None:
        channel = self._ensure_channel()
        key = routing_key or event.event_type
        body = event.model_dump_json().encode("utf-8")
        properties = pika.BasicProperties(
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=pika.DeliveryMode.Persistent,
            message_id=event.event_id,
            type=event.event_type,
            correlation_id=event.correlation_id,
            timestamp=int(event.occurred_at.timestamp()),
            headers={
                "schema_version": event.schema_version,
                "tenant_id": event.tenant_id or "",
                "priority": event.priority,
            },
        )
        channel.basic_publish(
            exchange=self.topology.exchange,
            routing_key=key,
            body=body,
            properties=properties,
            mandatory=False,
        )

    def publish_raw(
        self,
        *,
        exchange: str,
        routing_key: str,
        body: bytes,
        properties: pika.BasicProperties,
    ) -> None:
        channel = self._ensure_channel()
        channel.exchange_declare(exchange=exchange, exchange_type="topic", durable=True)
        channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=body,
            properties=properties,
            mandatory=False,
        )

    def close(self) -> None:
        if self._connection is not None and self._connection.is_open:
            self._connection.close()
        self._connection = None
        self._channel = None


def bump_retry_properties(properties: pika.BasicProperties, retry_count: int) -> pika.BasicProperties:
    headers = dict(properties.headers or {})
    headers["x-lab-retry-count"] = retry_count
    return pika.BasicProperties(
        content_type=properties.content_type,
        content_encoding=properties.content_encoding,
        headers=headers,
        delivery_mode=properties.delivery_mode or pika.DeliveryMode.Persistent,
        priority=properties.priority,
        correlation_id=properties.correlation_id,
        reply_to=properties.reply_to,
        expiration=properties.expiration,
        message_id=properties.message_id,
        timestamp=properties.timestamp,
        type=properties.type,
        user_id=properties.user_id,
        app_id=properties.app_id,
        cluster_id=properties.cluster_id,
    )
