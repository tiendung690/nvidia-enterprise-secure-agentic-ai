# v6.4.0 - Governed Analytics Control Plane Hardening

This release generalizes the v6.3.1 deterministic comparison fix into a governed structured-
analytics execution lane. The goal is to prevent correct Gold data from being turned into an
incomplete or stale answer by LLM synthesis, citation repair, cache reuse, or cross-grain metric
assumptions.

## 1. Deterministic structured analytics lane

`Capability / Intent Router -> analytics_query_tool -> SemanticMetricRegistry -> Delta Gold ->
Provenance -> Deterministic Renderer -> DLP -> Citation Validation -> Completeness Gate -> Cache`

Supported typed plans:

- exact customer/book lookup;
- rank customers by `total_amount`;
- rank books by `total_revenue`;
- allowlisted `average_spending_per_order`, `revenue_per_unit`, and
  `average_units_per_order` derivations;
- customer spending vs highest-revenue-book comparison;
- cross-Gold reconciliation with grain-aware metric semantics;
- deterministic fail-closed handling for unsupported time-trend, causal, and customer-to-book
  relationship questions.

The DSL rejects extra fields. The application, not the LLM, owns datasets, metrics, formulas,
row limits, tenant filtering, masking, and query complexity.

## 2. Provenance-aware derived metrics

Every application-derived metric carries:

```json
{
  "output_name": "average_spending_per_order",
  "formula_id": "customer.average_spending_per_order.v1",
  "formula": "total_amount / total_orders",
  "inputs": {"total_amount": 204.9, "total_orders": 2},
  "source_citation_ids": ["D......"],
  "value": 102.45
}
```

`validate_provenance()` does not evaluate arbitrary expressions. It recomputes only allowlisted
formula IDs and rejects altered formula text, unknown citations, and value mismatches.

## 3. Answer completeness is independent from citation coverage

Structured analytics tools emit an `answer_contract` with the required entity/row count.
After citation repair the service checks:

- expected entities;
- generated entities;
- validated entities;
- removed entities;
- completeness ratio.

A table that retained one cited row but lost required rows is rejected with
`ANSWER_VALIDATION_FAILED`; it is never returned as a successful empty/partial table.

## 4. Strict cache admission and source-version freshness

Cache admission now requires all of:

- successful request outcome;
- valid citations;
- valid provenance;
- 100% required answer completeness;
- no citation repair attempt;
- zero removed claims;
- a safe source-version fingerprint for structured analytics.

The cache key already isolates tenant/user authorization scope and purpose. v6.4.0 additionally
binds structured analytics entries to current Delta Gold versions. `version_fingerprint()` checks
Delta metadata directly and invalidates an in-process row snapshot when the table has advanced,
preventing a new-version cache key from storing old-snapshot data. The cache contract version is
bumped to `cache-contract-v3`, invalidating old in-process entries on upgrade/restart.

## 5. Metric/grain semantics

`SemanticMetricRegistry` records dataset grain and metric behavior. In particular,
`total_orders` is not treated as additive across the book dimension. Cross-Gold reconciliation
therefore compares safe additive metrics (`total_amount` vs `total_revenue`, `total_quantity`)
but marks order totals as `not_semantically_comparable` instead of claiming equality from two
coincidentally identical sums.

## 6. Provider control plane

Structured analytics bypasses the NVIDIA provider entirely. Provider telemetry now distinguishes
`deterministic`, `provider`, and `not_used`; a deterministic path reports `provider=null` and
`model_tier=not_used`.

Direct-RAG synthesis has a 15-second end-to-end provider deadline by default. The agent lane has a
30-second hosted-model budget across attempts. Capacity/timeout failures can degrade to the fast
tier when an independent fast backend exists; capacity exhaustion otherwise fails cleanly instead
of repeatedly waiting on the same expensive tier.

## 7. Telemetry and evidence semantics

- latency stages are fractional milliseconds rather than rounded integer `0 ms` values;
- `source_as_of`, `tool_retrieved_at`, and `data_version` are separate;
- structured Gold retrieval uses `live_lakehouse_tool`;
- vector knowledge retrieval uses `rag_vector_retrieval`;
- cached Gold answers use `cached_lakehouse_answer`;
- production normal responses expose only a compact public response. Full internal source/policy/
  tool/provider traces require `X-Debug-Trace: true` and role `ai_platform_admin` or
  `data_engineer`.

## 8. Error semantics

Tool budget exhaustion is an execution-policy failure, not invalid user input. The API now returns
`503 AGENT_EXECUTION_BUDGET_EXCEEDED` with stage/tool/allowed/attempted/budget-scope metadata.
Completeness and provenance failures return dedicated validation errors and are never cached.

## 9. Regression gates

`tests/unit/test_v6_4_governed_analytics.py` covers deterministic ranking, derived metrics,
provenance recomputation, completeness fail-closed behavior, Delta-version cache invalidation,
cross-tenant isolation, grain-aware reconciliation, and unsupported analytical requests.

Recommended production SLO gates for structured analytics remain: 100% business correctness,
100% citation coverage, 100% required completeness, zero removed claims, zero cross-tenant
violations, zero provider calls, and low sub-second latency for local Gold reads.
