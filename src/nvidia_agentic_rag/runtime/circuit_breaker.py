from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from nvidia_agentic_rag.schemas import CircuitState


class CircuitOpenError(RuntimeError):
    pass


@dataclass
class CircuitBreaker:
    failure_threshold: int
    reset_seconds: float
    enabled: bool = True
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if self.reset_seconds <= 0:
            raise ValueError("reset_seconds must be positive")
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_probe_in_flight = False

    @property
    def state(self) -> CircuitState:
        if not self.enabled:
            return "disabled"
        if self._opened_at is None:
            return "closed"
        if self.clock() - self._opened_at >= self.reset_seconds:
            return "half_open"
        return "open"

    def before_request(self) -> None:
        state = self.state
        if state in {"closed", "disabled"}:
            return
        if state == "open":
            raise CircuitOpenError("Provider circuit breaker is open")
        if self._half_open_probe_in_flight:
            raise CircuitOpenError("Provider circuit breaker half-open probe is already running")
        self._half_open_probe_in_flight = True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._half_open_probe_in_flight = False

    def record_transient_failure(self) -> None:
        if not self.enabled:
            return
        self._half_open_probe_in_flight = False
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = self.clock()

    def record_non_transient_failure(self) -> None:
        # A malformed request or authentication error should not poison provider capacity state.
        self._half_open_probe_in_flight = False
