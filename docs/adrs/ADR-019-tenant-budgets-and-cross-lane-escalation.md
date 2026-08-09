# ADR-019 — Per-tenant daily budgets and opt-in cross-lane escalation

## Status
Accepted (v6.2)

## Context
Admission control in v6.1 was global (concurrency semaphore + queue timeout): one tenant
could consume the entire daily provider capacity of a shared deployment, and there was no
FinOps signal per tenant. Separately, the deterministic router had a default lane but no
failure-driven path between lanes: a direct-RAG route with no authorized evidence failed
closed immediately — a deliberate v6.1 cost guarantee ("no generation on weak evidence"),
but sometimes the bounded agent lane could have answered from other authorized tools.

## Decision
1. **Tenant budgets** (`runtime/tenant_budget.py`): per-tenant daily request and token
   budgets over a UTC window, checked after the response-cache lookup (cache hits stay
   free) and charged after provider-backed lanes complete, using a conservative chars/4
   estimate. Exhaustion raises `TenantBudgetExceededError`, mapped to HTTP 429
   `TENANT_BUDGET_EXCEEDED` with a day-rollover `Retry-After`. Zero budgets (default)
   disable the ledger entirely. The ledger is process-local by contract; multi-replica
   deployments back the same admit/charge semantics with a shared store.
2. **Cross-lane escalation**: when enabled, a direct-RAG route that yields no authorized
   sources escalates once to the bounded agent lane inside the same timeout, capacity, and
   security scope; the evidence-sufficiency gate still applies to whatever the agent
   produces. Telemetry: `agentic_ai_route_decisions_total`,
   `agentic_ai_route_escalations_total`, and `route_escalated` on the result.

## The default-off decision
`CROSS_LANE_ESCALATION_ENABLED` defaults to **false**. Enabling it by default would break
an explicit v6.1 invariant that tests encode
(`test_direct_rag_fails_closed_before_generation_when_evidence_is_weak`): weak evidence
must not trigger generation. Escalation trades tokens for recall; that trade belongs to
the operator, not to a silent default. Teams that enable it accept one extra agent run on
empty-evidence direct routes in exchange for fewer avoidable "insufficient context"
responses.

## Consequences
- Deterministic-lane requests count against the request budget (it is a request cap), but
  never against the token budget.
- Budget rejection is auditable (`tenant_budget_exceeded` audit outcome) and observable
  (`agentic_ai_tenant_budget_events_total`).
- Escalated requests remain fail-closed end to end: if the agent also finds no authorized
  evidence, the insufficient-context template is returned unchanged.
