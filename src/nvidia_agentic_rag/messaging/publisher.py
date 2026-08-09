from __future__ import annotations

from typing import Protocol

from .contracts import EventEnvelope


class EventPublisher(Protocol):
    def publish(self, event: EventEnvelope, *, routing_key: str | None = None) -> None:
        """Publish one durable event or raise if broker confirmation fails."""

    def close(self) -> None:
        """Release transport resources."""
