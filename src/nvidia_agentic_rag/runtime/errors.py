from __future__ import annotations

from dataclasses import dataclass

from nvidia_agentic_rag.schemas import LatencyBreakdown, ProviderTrace


@dataclass
class CapacityWaitTimeoutError(RuntimeError):
    waited_ms: int
    retry_after_seconds: int = 10

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, "The agent execution queue is currently at capacity")


@dataclass
class SessionBusyError(RuntimeError):
    session_id: str
    retry_after_seconds: int = 5

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, "Another request for this session is still being processed")


@dataclass
class SessionWaitTimeoutError(RuntimeError):
    session_id: str
    waited_ms: int
    retry_after_seconds: int = 5

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, "Timed out while waiting for the active session request")


@dataclass
class AgentExecutionTimeoutError(RuntimeError):
    timeout_seconds: float
    latency_breakdown: LatencyBreakdown

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, "The agent did not complete before its execution deadline")


@dataclass
class ProviderUnavailableError(RuntimeError):
    public_message: str
    retry_after_seconds: int
    error_code: str
    provider_trace: ProviderTrace

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.public_message)


@dataclass
class TenantBudgetExceededError(RuntimeError):
    tenant_id: str
    reason: str
    retry_after_seconds: int

    def __post_init__(self) -> None:
        RuntimeError.__init__(
            self, "The tenant's daily AI budget is exhausted; the request was not executed"
        )
