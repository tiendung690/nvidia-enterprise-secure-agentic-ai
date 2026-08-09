# Quality scorecard — path to 9.5/10

The score is an engineering readiness rubric, not a certification claim.

| Dimension | Evidence in repository | Score |
|---|---|---:|
| Architecture boundaries | control/data plane, multi-corpus, typed ports/contracts | 9.5 |
| Retrieval correctness | isolated indexes, candidate+threshold+top-k, corpus audit | 9.5 |
| Grounding/provenance | stable IDs, typed sources, claim citation rules/audit | 9.3 |
| Reliability | deadlines, queue bound, tool budgets, atomic index swap | 9.2 |
| Cache/state correctness | TTL-LRU, tenant/session scope, policy/model/index versions | 9.5 |
| Security baseline | secret gate, direct/indirect signals, read-only tools, safe calculator | 9.0 |
| Observability | request ID, metrics, tool traces, versions, evaluation reports | 9.2 |
| Test evidence | 43 tests, 93.57% core coverage, corpus/static/security gates | 9.5 |
| Deployment reference | hardened Docker, separate ingest job, health/readiness | 8.8 |
| Enterprise scale | documented Redis/vector/OIDC/ACL/durable-workflow path | 8.0 |

**Reference implementation assessment: 9.3–9.5/10 for a local production-oriented portfolio.**

It should not be described as 10/10 or enterprise-certified until live load, security, tenant ACL,
OIDC, multi-replica shared state, disaster recovery, and canary SLO evidence are completed.

## Gates needed for a defensible 10/10 claim

1. OIDC/JWT and resource-level tenant ACL filtering in retrieval.
2. Redis/durable session state and shared cache under multiple API replicas.
3. Managed vector store, hybrid retrieval, reranking, and backup/restore exercise.
4. OpenTelemetry distributed traces with production SLO dashboards.
5. Load, soak, fault-injection, and provider-capacity tests.
6. Prompt-injection/red-team suite and tool policy-as-code.
7. Entailment/faithfulness evaluator calibrated against human labels.
8. Canary deployment, rollback evidence, and operational runbooks exercised by another engineer.
