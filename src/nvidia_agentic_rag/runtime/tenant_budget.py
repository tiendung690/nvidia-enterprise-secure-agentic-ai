from __future__ import annotations

import threading
import time
from dataclasses import dataclass


def estimate_tokens(text: str) -> int:
    """Cheap, deterministic token estimate used for budget accounting.

    Provider-reported usage is preferable when available; a chars/4 floor keeps
    the ledger conservative and dependency-free.
    """
    return max(1, len(text) // 4)


def _current_day(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // 86_400)


def seconds_until_day_rollover(now: float | None = None) -> int:
    reference = now if now is not None else time.time()
    return max(1, int(((_current_day(reference) + 1) * 86_400) - reference))


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str
    requests_used: int
    tokens_used: int
    retry_after_seconds: int = 0


class TenantBudgetLedger:
    """In-process per-tenant daily request/token budgets (ADR-019).

    A zero budget disables the corresponding check, so the ledger is a no-op by
    default and fully backwards compatible. The window is a UTC day; state is
    process-local by design — production multi-replica deployments should back
    this contract with a shared store (for example Redis or PostgreSQL) while
    preserving the same admit/charge semantics.
    """

    def __init__(self, *, request_budget: int = 0, token_budget: int = 0) -> None:
        if request_budget < 0 or token_budget < 0:
            raise ValueError("budgets must be zero or positive")
        self.request_budget = request_budget
        self.token_budget = token_budget
        self._lock = threading.Lock()
        self._day = _current_day()
        self._requests: dict[str, int] = {}
        self._tokens: dict[str, int] = {}

    @property
    def enabled(self) -> bool:
        return self.request_budget > 0 or self.token_budget > 0

    def _roll_window(self, now: float | None = None) -> None:
        day = _current_day(now)
        if day != self._day:
            self._day = day
            self._requests.clear()
            self._tokens.clear()

    def admit(self, tenant_id: str, *, now: float | None = None) -> BudgetDecision:
        """Reserve one request slot for the tenant, failing closed at the cap."""
        if not self.enabled:
            return BudgetDecision(True, "budgets-disabled", 0, 0)
        with self._lock:
            self._roll_window(now)
            requests_used = self._requests.get(tenant_id, 0)
            tokens_used = self._tokens.get(tenant_id, 0)
            if self.request_budget and requests_used >= self.request_budget:
                return BudgetDecision(
                    False,
                    "daily-request-budget-exhausted",
                    requests_used,
                    tokens_used,
                    retry_after_seconds=seconds_until_day_rollover(now),
                )
            if self.token_budget and tokens_used >= self.token_budget:
                return BudgetDecision(
                    False,
                    "daily-token-budget-exhausted",
                    requests_used,
                    tokens_used,
                    retry_after_seconds=seconds_until_day_rollover(now),
                )
            self._requests[tenant_id] = requests_used + 1
            return BudgetDecision(True, "admitted", requests_used + 1, tokens_used)

    def charge_tokens(self, tenant_id: str, tokens: int, *, now: float | None = None) -> int:
        """Record consumed tokens after a provider round-trip; returns the day total."""
        if tokens <= 0 or not self.enabled:
            return self._tokens.get(tenant_id, 0)
        with self._lock:
            self._roll_window(now)
            total = self._tokens.get(tenant_id, 0) + tokens
            self._tokens[tenant_id] = total
            return total

    def usage(self, tenant_id: str) -> tuple[int, int]:
        with self._lock:
            self._roll_window()
            return self._requests.get(tenant_id, 0), self._tokens.get(tenant_id, 0)


__all__ = [
    "BudgetDecision",
    "TenantBudgetLedger",
    "estimate_tokens",
    "seconds_until_day_rollover",
]
