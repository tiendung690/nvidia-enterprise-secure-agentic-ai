from __future__ import annotations

import pytest

from nvidia_agentic_rag.runtime import CircuitBreaker, CircuitOpenError
from nvidia_agentic_rag.runtime.budgeting import (
    build_response_contract,
    classify_query_complexity,
    resolve_answer_budget,
)


def test_circuit_breaker_opens_and_recovers_half_open() -> None:
    now = [100.0]
    breaker = CircuitBreaker(
        failure_threshold=2,
        reset_seconds=10,
        clock=lambda: now[0],
    )
    assert breaker.state == "closed"
    breaker.record_transient_failure()
    assert breaker.state == "closed"
    breaker.record_transient_failure()
    assert breaker.state == "open"
    with pytest.raises(CircuitOpenError):
        breaker.before_request()

    now[0] = 111.0
    assert breaker.state == "half_open"
    breaker.before_request()
    with pytest.raises(CircuitOpenError):
        breaker.before_request()
    breaker.record_success()
    assert breaker.state == "closed"


def test_disabled_circuit_never_opens() -> None:
    breaker = CircuitBreaker(failure_threshold=1, reset_seconds=1, enabled=False)
    breaker.record_transient_failure()
    breaker.before_request()
    assert breaker.state == "disabled"


def test_query_complexity_and_response_contract() -> None:
    assert classify_query_complexity("Explain memory.") == "simple"
    assert classify_query_complexity("Compare ReAct versus eRAG.") == "comparison"
    assert classify_query_complexity("Explain the complete lifecycle end-to-end.") == "long"

    budget = resolve_answer_budget(
        "Compare ReAct versus eRAG.",
        simple_words=100,
        comparison_words=300,
        long_words=800,
        simple_sources=4,
        comparison_sources=8,
        long_sources=10,
    )
    assert budget.complexity == "comparison"
    assert budget.max_words == 300
    contract = build_response_contract(budget)
    assert "300 words" in contract
    assert "current-turn evidence" in contract
