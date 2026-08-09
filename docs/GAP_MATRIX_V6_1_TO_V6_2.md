# Gap Matrix — Reference Architecture v2 (①–⑰) vs Repository v6.1 → v6.2

Scope: verification of the seventeen reference-architecture upgrades against the actual
v6.1 codebase, with file-level evidence, followed by the v6.2 changes applied. Status
values: **Present** (already implemented in v6.1), **Partial**, **Gap**.

| # | Reference change | v6.1 status | Evidence (file · anchor) | v6.2 action |
|---|---|---|---|---|
| ① | Per-tenant token/cost budget at ingress | **Gap** — admission was a global concurrency semaphore only | `agents/service.py` · `_request_slots`, `_acquire_capacity` | **Implemented.** `runtime/tenant_budget.py` ledger (daily request + token budgets, UTC window, fail-closed); admitted after cache lookup so cache hits stay free; HTTP 429 `TENANT_BUDGET_EXCEEDED` with day-rollover `Retry-After` (`api.py`); `agentic_ai_tenant_budget_events_total` metric. Opt-in via `TENANT_DAILY_REQUEST_BUDGET` / `TENANT_DAILY_TOKEN_BUDGET` (ADR-019) |
| ② | Memory read inside request context | **Present** | `agents/service.py` · `memory_service.load_context()` before routing, fail-closed on overflow | None needed |
| ③ | Cache READ/WRITE split, entitlement-aware key | **Present, correctly placed** | `agents/service.py` · `_cache_key` includes tenant, `authorization_hash()`, purpose, `index_version`, `memory_version`, policy version, model params, `PROMPT_VERSION`; read sits before routing (ADR-006/009) | None needed |
| ④ | Router: default lane, misroute telemetry, cross-lane escalation | **Partial** — default agent lane existed; no telemetry, no failure-driven escalation | `routing/deterministic.py` · `classify_route` fallthrough | **Implemented.** `agentic_ai_route_decisions_total` per lane; direct-RAG-without-evidence may escalate once to the agent lane before the evidence gate (`ROUTE_ESCALATIONS` metric, `route_escalated` on the result). Escalation is **opt-in** (`CROSS_LANE_ESCALATION_ENABLED=false` default) to preserve the v6.1 fail-closed-before-generation guarantee (ADR-019) |
| ⑤ | Async agent lane: job queue + checkpoint/resume | **Partial** — outbox exists for memory events only; chat is synchronous behind admission control | `scripts/outbox_dispatcher.py`, `memory/repository.py` | Deferred (P2). Documented direction: job_id + status/webhook contract reusing the existing transactional-outbox pattern |
| ⑥ | Budget / loop control (runaway-agent protection) | **Present** | `config.py` · `agent_max_tool_calls=4`, `agent_max_same_tool_calls=1`, request timeout; `runtime/budgeting.py` dynamic answer budget (ADR-013) | None needed |
| ⑦ | ACL filter at retrieval (security trimming in-query) | **Partial — asymmetric**: lexical pre-filtered, vector post-filtered only | `rag/index_manager.py` · lexical `search(..., allowed=...)` vs vector `retriever.retrieve()` then broker | **Implemented.** Vector candidates now pass the same authorization predicate before RRF fusion, so denied documents no longer occupy fusion/rerank slots; `prefiltered_denied_count` added to `RetrievalExecutionTrace` + `agentic_ai_retrieval_prefiltered_denied_total` metric |
| ⑧ | Tool authZ (OBO) + sandbox | **Present via a stronger mechanism** | `tools/secure_operational.py` typed read-only tools, `identity/context.py` request-scoped identity, PostgreSQL RLS; no shell/SQL/filesystem tools exist (ADR-005) | None needed; OBO token exchange noted as the pattern for future cross-service tools |
| ⑨ | Fallback chains (rerank → RRF order, etc.) | **Partial** — corrective `like_search` fallback existed; rerank itself unguarded | `rag/index_manager.py` · quality-gate fallback | **Implemented.** Rerank wrapped defensively: any failure falls back to the RRF fused order and records `rerank_error_rrf_order` in the fallback chain — matters when the local reranker is swapped for a remote cross-encoder |
| ⑩ | Trust boundary for tool/evidence text (indirect injection) | **Present** | `rag/index_manager.py` · `inspect_untrusted_content` per candidate; `block` mode drops the candidate; system prompt rule 3 | None needed; production compose should set `INDIRECT_PROMPT_GUARD_MODE=block` |
| ⑪ | Corrective FAIL loop before no-generation | **Present (retrieval level)** | `rag/index_manager.py` · degraded corrective fallback; bounded | Extended by ④'s optional lane-level escalation |
| ⑫ | HITL gate on consequential writes | **Present in adapted form** | Write tools do not exist (ADR-005); the one write surface — memory promotion — requires admin approval for `model_inferred` facts (`memory/promotion.py`) | None needed; the framework applies unchanged if write tools are ever added |
| ⑬ | Shared Model Gateway with tiers + degrade-to-fast | **Gap** — one 550B model served every lane | `nvidia/llm.py`, `bootstrap.py` · single `build_nvidia_llm` wired everywhere | **Implemented.** `gateway/model_gateway.py`: deterministic tier selection (simple direct-RAG synthesis → fast tier), `build_nvidia_fast_llm` on the same NIM endpoint, and one-shot degrade-to-fast on transient exhaustion — directly targeting the documented 550B capacity failures (`docs/TROUBLESHOOTING_NVIDIA_CAPACITY.md`). Tier + degradation surfaced on `ProviderTrace` (ADR-018) |
| ⑭ | OTel distributed spans | **Partial — equivalent custom telemetry** | `tracing/` replayable run trace + per-stage Prometheus histograms | Deferred (P1): OTel export can wrap the existing stage boundaries without redesign |
| ⑮ | Eval loop: golden set, judge, shadow/canary | **Partial** | `evaluation/golden_cases.jsonl`, `scripts/evaluate_api.py` | Deferred (P1): shadow-mode comparison job on the gateway is the next increment |
| ⑯ | ACL sync at ingestion | **Present** | `config.py` · `require_document_security_metadata`, `data/security-manifest.json`, registry seeds | None needed |
| ⑰ | Index-update events → cache invalidation | **Present via key versioning** | `_cache_key` and retrieval cache both embed `index_version` — version bump stales every dependent entry (ADR-006) | None needed |

## Net assessment

v6.1 already implemented 8/17 items fully and 5/17 partially — including the two controls most
architectures miss (entitlement-keyed cache and the evidence-sufficiency fail-closed gate).
v6.2 closes the four highest-value deltas (①, ④, ⑦, ⑬ plus the ⑨ hardening) with
opt-in defaults and zero behavioral change for existing deployments; ⑤, ⑭, ⑮ remain the
documented P1/P2 backlog.
