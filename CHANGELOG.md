# Changelog

## 6.4.4 - Final Analytics Evidence Routing

- Generalized evidence sufficiency for customer-book derived metrics and temporal comparisons.
- Added deterministic customer/top-book multi-fact and causal fact/abstention capabilities.
- Hardened all ten governed Gold analytics demo prompts against unnecessary provider calls.
- Added semantic capability metadata and clearer insufficiency telemetry.

## 6.4.3 - Evidence Sufficiency & Provider Deadline Hardening

- Fixed the production proof query `Can you prove whether C001 purchased B003?` so canonical
  bare customer/book IDs plus purchase-language route to governed deterministic abstention.
- Prevents customer/book summary aggregates from being sent to the 550B agent lane to infer an
  unavailable order-item relationship; the provider is not invoked for this failure mode.
- Preserves the typed analytics insufficiency explanation instead of replacing it with a generic
  enterprise-context message.
- Increased the bounded agent-provider deadline from 30 s to 45 s while keeping it below the
  end-to-end request budget, and added configuration validation for provider/request deadlines.
- Changed run-trace latency to fractional milliseconds, removing Pydantic serialization warnings.
- Added regression tests for forward/reverse bare-ID purchase questions and timeout configuration.

## 6.4.2 - Provider Context Budget & Knowledge Routing Hardening

- Corrected the Nemotron-3-Ultra provider context ceiling and added an 8K-token safety reserve.
- Caps stale million-token environment configuration to the provider-realistic model limit.
- Removed persistent provider workflow context; legacy mode is rejected to prevent session growth.
- Routes implicit company-knowledge summaries through bounded direct RAG before LLM synthesis.
- Added `NVIDIA_CONTEXT_LENGTH_EXCEEDED` classification and context-budget readiness telemetry.
- Added regression coverage for the observed 258K context-overflow failure.

## 6.4.1 - Reconciliation Audit Routing & Semantic Equality Hardening

- Fixed a deterministic-router false positive where natural-language phrases such as
  `customer spending` or `book revenue` could be parsed as entity IDs.
- Added governed recognition for cross-Gold consistency/audit/double-counting prompts so they
  route to `analytics_query_tool` reconciliation instead of a bogus entity lookup.
- Enriched reconciliation output with explicit `equality_expected`, observed equality, grain
  rationale, and double-count risk while preserving deterministic row-level citations.
- Added regression coverage for the exact production audit prompt and explicit lowercase IDs.

## 6.4.0 - Governed Analytics, Provenance, Completeness & Safe Cache

- Generalized the deterministic comparison pattern into `analytics_query_tool` with a strict typed DSL.
- Added application-owned semantic metric/grain registry and safe derived metrics.
- Added row-level provenance plus allowlisted formula recomputation validation.
- Added answer-completeness gate so citation repair cannot silently return partial/empty analytics.
- Cache admission now rejects repaired/incomplete answers and includes tenant/auth/purpose plus Delta-version freshness.
- Added grain-aware cross-Gold reconciliation and deterministic fail-closed unsupported analytics.
- Fixed deterministic provider trace semantics, fractional latency telemetry, source freshness fields, and evidence-origin naming.
- Restricted full production debug telemetry to privileged `X-Debug-Trace` requests.
- Standardized tool-budget failure as `503 AGENT_EXECUTION_BUDGET_EXCEEDED`.
- Added bounded direct-RAG/agent provider deadlines and v6.4.0 regression tests.

## 6.3.1 — Deterministic Analytics Comparison & Per-Tool Budgets

- Fixed `AGENT_TOOL_BUDGET_EXCEEDED` for legitimate multi-step analytics where the agent
  needed more than one calculator invocation while the global same-tool limit was `1`.
- Added scoped same-tool limits: strict default remains `1`, while `safe_calculator_tool` and
  typed lakehouse analytics capabilities have independent bounded reuse limits.
- Increased the small global tool-call ceiling from `4` to `6`; corpus/external same-tool
  repetition remains constrained by the strict default.
- Added `compare_customer_spending_to_top_book_tool`, a deterministic capability that reads one
  customer aggregate and the highest-revenue book, performs financial arithmetic with `Decimal`,
  and returns both Delta-backed database citations.
- Added a deterministic router fast path for the exact customer-spending vs highest-revenue-book
  comparison, bypassing the planning model and calculator chain entirely.
- Added regression tests for the reported C001 / top-book comparison, specialized budget limits,
  multi-source citations, missing records, and direct-route provider bypass.
- Added structured tool-budget logging with attempted/limit metadata for production diagnosis.

## 6.3.0 — Lakehouse Gold Read Path (Delta Lake)

- Added a read-only Delta Lake gold analytics repository (`data/analytics.py`) backed by
  delta-rs: the API consumes the medallion pipeline's curated `gold_customer_order_summary`
  and `gold_book_sales_summary` serving tables without embedding Spark (ADR-020).
- Added `SecureAnalyticsTools` with three bounded typed capabilities (customer aggregate,
  book aggregate, clamped top-N) behind a new `analytics.read` policy capability
  (roles `analyst|operations|admin`, purposes `business-analytics|operations-review`) and
  tenant-declared warehouse ownership; cross-tenant reads observe `not_found`.
- Every lakehouse observation cites its exact Delta commit version in `source_id`/`section`,
  with a short-TTL pinned snapshot for per-request read consistency.
- Added an explicit `DataMasker.mask_value` DLP path so schema-known direct identifiers
  (customer names) are pseudonymized/redacted before entering the model context.
- Fail-closed availability: unreachable gold tables return a sourced-empty
  `analytics_unavailable` payload.
- New settings (`ANALYTICS_BACKEND`, `DELTA_WAREHOUSE_ROOT`, table names,
  `ANALYTICS_TENANT_ID`, `ANALYTICS_MAX_ROWS`, `ANALYTICS_SNAPSHOT_TTL_SECONDS`), new
  `business-analytics` purpose, docker-compose wiring, and `.env.example` documentation;
  the backend is disabled by default so v6.2.1 behavior is unchanged.
- New scripts: `scripts/sync_lakehouse_gold.py` (copies only `gold_*` tables from the DCEA
  export; bronze/silver are refused) and `scripts/seed_lakehouse_gold_demo.py`
  (Spark-free local seeding via delta-rs).
- System prompt v6.3 adds the lakehouse tool-routing rule and extends the
  source-of-authority rule to lakehouse-gold observations.
- New unit suites for the Delta repository (lookup, tenancy, clamping, snapshot pinning,
  failure paths) and the analytics tools (policy, masking, citations, availability), both
  included in the coverage gate.


## 6.2.1 — Live Latency & Capacity Hardening

- Enabled the fast direct-RAG synthesis profile by default. When no alternate fast model is
  configured, the primary model is reused with thinking disabled and a tighter output cap.
- Routed single-corpus direct-RAG **comparison** queries to the fast synthesis profile; v6.2
  previously routed them to the complex 550B profile, including the production load-test query.
- Added a 30-second total provider deadline for direct-RAG synthesis.
- Removed nested retry amplification: chat SDK retries default to zero and the runtime is the
  single retry owner; embedding retries have an independent setting.
- Capacity exhaustion on the active fast tier now fails fast instead of immediately retrying the
  same saturated tier. Complex direct synthesis may downgrade before same-tier retry.
- Split provider circuit state by `fast`/`complex` tier and added tier-aware Prometheus metrics.
- Changed interactive admission defaults to `AGENT_QUEUE_TIMEOUT_SECONDS=3`,
  `SESSION_CONCURRENCY_POLICY=reject`, and `SESSION_LOCK_WAIT_TIMEOUT_SECONDS=5`.
- Provider error classification now prefers structured HTTP status and `Retry-After` headers.
- Load sweep now reports controlled-overload and acceptable rates so intentional 409/429/503
  shedding is not confused with correctness failure.

## 6.2.0 — Governance Deltas: Tiered Gateway, Tenant Budgets, Symmetric Trimming

- Added a tiered model gateway (ADR-018): optional fast NIM model for simple direct-RAG
  synthesis, deterministic application-owned tier selection, and one-shot degrade-to-fast
  when complex synthesis exhausts transient retries (targets 550B capacity incidents).
- Added per-tenant daily request/token budgets with fail-closed 429 `TENANT_BUDGET_EXCEEDED`,
  day-rollover Retry-After, audit outcome, and Prometheus counters (ADR-019). Disabled by
  default; cache hits never consume budget.
- Added opt-in cross-lane escalation: direct RAG with no authorized evidence may run the
  bounded agent lane once before the evidence gate fails closed; default off to preserve
  the v6.1 no-generation-on-weak-evidence guarantee (ADR-019).
- Made retrieval security trimming symmetric: vector candidates now pass the authorization
  predicate before RRF fusion (previously lexical-only), with `prefiltered_denied_count`
  in the retrieval trace and a dedicated metric.
- Guarded the reranker: any rerank failure falls back to the RRF fused order and records
  `rerank_error_rrf_order` in the fallback chain.
- Added router lane telemetry (`agentic_ai_route_decisions_total`) and escalation metrics.
- Extended `ProviderTrace` with `model_tier` and `degraded_to_fast`; `AgentResult` with
  `route_escalated`.
- Added `docs/GAP_MATRIX_V6_1_TO_V6_2.md`: seventeen-point verification of the reference
  architecture against this codebase with file-level evidence.
- New tests: model gateway tiers/degrade, tenant budget ledger and admission, escalation
  on/off behavior, fast-tier synthesis, degrade-to-fast end to end.

## 6.1.0 — Adaptive Production Optimization

- Added a deterministic request router for arithmetic, definitions, and explicit corpus routes.
- Added direct single/multi-corpus RAG execution to remove unnecessary agent-planning calls.
- Added fail-closed evidence sufficiency before generation for weak enterprise retrieval.
- Made Multi-Query adaptive so simple queries do not pay expansion cost.
- Tightened deterministic reranking and query-coverage requirements for grounded answers.
- Reduced interactive provider retries from three attempts to two by default.
- Added local definition fast path for retrieval-augmented generation.
- Fixed same-session load testing so all serialized requests use the same user and session.
- Added direct-route regression tests for calculator, definition, RAG, and weak evidence.

## 6.0.0

- Added guarded multi-query, hybrid BM25/vector retrieval, RRF, reranking and quality fallback.
- Added bounded conversation reconstruction and memory-versioned cache.
- Added typed governed memory, promotion approval, SCD2 supersession, forgetting and outbox.
- Added replayable tenant-scoped traces, PostgreSQL audit and hardened v6 RLS migrations.
- Added deterministic explicit-preference capture with injection rejection and fail-closed exact memory.
- Added physical memory erasure, retention outbox events and an at-least-once outbox dispatcher.
- Added role-gated admin endpoints and production Compose secret requirements.
- Added v6 API fields/endpoints, architecture ADRs, production checklist and tests.

## 5.0.0 — Production Reliability and Agentic AI Design System

### Added

- Session admission policy: serialize or reject.
- Separate session wait, capacity wait, provider and execution timeout errors.
- NVIDIA transient retry with exponential backoff, jitter and circuit breaker.
- Table-aware citation validation and conservative citation repair.
- Request outcome, safety audit, provider trace and latency breakdown.
- Dynamic answer budgets and current-turn response contract.
- P01–P10 performance suite and production/SRE documentation.
- ADRs for admission control, provider resilience, citation postcondition and answer budgets.

### Changed

- Default concurrent fresh requests: 1 -> 2.
- Default same-tool calls: 2 -> 1.
- Course final top-k: 8 -> 6.
- Citation mode: audit -> strict.
- Citation minimum coverage: 0.70 -> 0.90.
- Docker host port is configurable through `APP_PORT`.
- API version and package version updated to 5.0.0.

### Fixed

- Generic 504 for capacity/session contention.
- Invalid factual answers returned with HTTP 200 in strict scenarios.
- Markdown table citation under-counting.
- Misleading 100% citation coverage for blocked/refusal responses.
- Provider capacity requiring manual retry.
- Excessive single-question answer length and duplicate same-corpus retrieval.

## 4.0.0

Enterprise secure context broker, JWT/policy enforcement, typed operational data tools, output DLP,
authorization-aware cache and audit evidence.
