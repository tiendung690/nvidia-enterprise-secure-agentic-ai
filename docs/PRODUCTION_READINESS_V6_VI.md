# Production readiness v6

## Đã enforce trong code

- JWT/purpose/RBAC/ABAC/clearance.
- Authorization-aware cache và memory-versioned cache.
- Hybrid RAG, RRF, rerank, quality gate, bounded fallback.
- Security trim trước LLM exposure.
- Bounded conversation projection.
- Typed memory + promotion/approval/physical erasure.
- Deterministic explicit preference capture; arbitrary fact/personality/policy inference disabled.
- Exact policy/preference enumeration fails closed instead of truncating.
- Source-run ownership validation.
- SCD2 supersession + tenant-tagged outbox + RLS.
- PostgreSQL security audit and role-gated admin endpoints.
- Provider retry/circuit breaker, admission and deadlines.
- Output DLP, strict citation postcondition.
- Hash-only core trace fields và tenant-scoped replay.

## Phải hoàn tất trong môi trường đích

| Gate | Acceptance evidence |
|---|---|
| Managed vector prefilter | Negative cross-tenant test proves unauthorized vectors are not candidate-scored |
| PostgreSQL migration | Schema checksum, RLS tests, rollback rehearsal |
| Identity | Real issuer/JWKS, key rotation, revoked-token test |
| Secret management | No long-lived secrets in `.env`; workload identity or secret manager |
| Load | p95/p99 under target at expected concurrency and corpus size |
| Soak | 8–24h without memory growth, connection leak or queue collapse |
| Chaos | NVIDIA 429/503, DB restart, network delay, full disk, stale index |
| Security | Prompt injection, indirect injection, IDOR, tenant leak and DLP red-team |
| Data lifecycle | Retention emits outbox events; erasure verification, backup/PITR and legal hold |
| Outbox | Supervised worker, lag/dead-letter alerting, duplicate-event test by `event_id` |
| Operations | SLO, alerts, dashboard, on-call runbook, canary and rollback |

## Suggested SLOs

- Availability: 99.9% excluding declared provider dependency window.
- Cross-tenant leakage: zero tolerated.
- Citation-valid enterprise factual answers: 100% returned answers.
- Trace creation for accepted requests: 100%.
- Memory promotion without source/provenance gate: zero tolerated.
- p95 end-to-end latency: set from actual NVIDIA region/model benchmark, not guessed offline.

## Honest boundary

Offline unit/static validation is necessary but not sufficient. “Production ready” is achieved only
when the deployment-specific gates above have evidence. This repository is a strong executable
reference architecture and production baseline, not a certification of an environment that was not
available during packaging.


## Required production commands

```bash
# Render first: missing mandatory secrets must fail before startup.
docker compose -f docker-compose.yml -f docker-compose.production.yml config

# Privileged workers use MAINTENANCE_DATABASE_URL, never DATABASE_URL.
python scripts/retention_job.py --dry-run
python scripts/outbox_dispatcher.py --once
```

Protect `/metrics` at ingress or a service-mesh authorization layer. Do not expose Prometheus,
Grafana, PostgreSQL or trace/admin endpoints publicly.
