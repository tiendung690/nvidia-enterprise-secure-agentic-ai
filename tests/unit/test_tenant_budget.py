from __future__ import annotations

import pytest

from nvidia_agentic_rag.runtime.tenant_budget import (
    TenantBudgetLedger,
    estimate_tokens,
    seconds_until_day_rollover,
)


def test_disabled_ledger_admits_everything() -> None:
    ledger = TenantBudgetLedger()
    assert ledger.enabled is False
    decision = ledger.admit("tenant-a")
    assert decision.allowed is True
    assert decision.reason == "budgets-disabled"
    assert ledger.charge_tokens("tenant-a", 10_000) == 0


def test_request_budget_fails_closed_at_cap() -> None:
    ledger = TenantBudgetLedger(request_budget=2)
    assert ledger.admit("tenant-a").allowed is True
    assert ledger.admit("tenant-a").allowed is True
    decision = ledger.admit("tenant-a")
    assert decision.allowed is False
    assert decision.reason == "daily-request-budget-exhausted"
    assert decision.retry_after_seconds > 0
    # Other tenants are isolated.
    assert ledger.admit("tenant-b").allowed is True


def test_token_budget_blocks_after_charges() -> None:
    ledger = TenantBudgetLedger(token_budget=100)
    assert ledger.admit("tenant-a").allowed is True
    total = ledger.charge_tokens("tenant-a", 120)
    assert total == 120
    decision = ledger.admit("tenant-a")
    assert decision.allowed is False
    assert decision.reason == "daily-token-budget-exhausted"


def test_window_rolls_over_at_utc_day_boundary() -> None:
    ledger = TenantBudgetLedger(request_budget=1)
    day_one = 86_400.0 * 100 + 10
    assert ledger.admit("tenant-a", now=day_one).allowed is True
    assert ledger.admit("tenant-a", now=day_one + 60).allowed is False
    day_two = day_one + 86_400
    assert ledger.admit("tenant-a", now=day_two).allowed is True
    requests_used, tokens_used = ledger.usage("tenant-a")
    assert requests_used >= 0 and tokens_used == 0


def test_negative_budget_rejected() -> None:
    with pytest.raises(ValueError):
        TenantBudgetLedger(request_budget=-1)


def test_estimate_tokens_floor_and_scaling() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("x" * 400) == 100


def test_seconds_until_rollover_bounds() -> None:
    value = seconds_until_day_rollover(now=86_400.0 * 200 + 86_000)
    assert 1 <= value <= 86_400
