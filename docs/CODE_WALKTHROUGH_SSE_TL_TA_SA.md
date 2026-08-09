# Code walkthrough — Strong SSE/TL to TA/SA

This document maps architecture decisions to concrete files and functions so the repository
can be defended in an interview rather than presented as a framework demo.

## 1. Request boundary and typed contract

### `src/nvidia_agentic_rag/api.py`

- `ChatRequest`: bounded query/session input and explicit `force_retrieval` control.
- `ChatResponse`: answer, current-turn tools, cache state, evidence origin, typed sources,
  citation audit, tool trace, index version, and prompt version.
- `create_app()`: lifespan-based dependency construction, request ID, no-store response,
  health/readiness, provider error mapping, protected ingestion, and cache administration.
- `ingest()`: rebuilds indexes, clears cached answers, and returns `restart_required=true`
  because startup-created tool retrievers must be rebound by restarting the application.

Interview point: **the API exposes proof of execution, not only natural-language output**.

## 2. Runtime control plane

### `src/nvidia_agentic_rag/agents/service.py`

- `AgentService.chat()`: direct prompt guard, session pruning, versioned cache lookup,
  queue/request timeout, per-session lock, agent execution, citation postcondition, safe cache
  admission, metrics, and failure cleanup.
- `AgentService._run_agent()`: consumes LlamaIndex workflow events, enforces total/same-tool
  budgets, times tool calls, captures structured sources, and accumulates safety signals.
- `AgentService._enforce_tool_budget()`: deterministic loop/cost protection; not prompt based.
- `AgentService._cache_key()`: tenant/session/query/index/model/generation/guard/citation/prompt
  dimensions prevent stale or policy-incompatible reuse.
- `AgentService._prune_sessions()`: TTL and capacity control for contexts and locks.
- `AgentService._collect_tool_payload()`: validates and deduplicates provenance returned by tools.

Interview point: **the LLM proposes; deterministic code enforces**.

## 3. Bounded, versioned cache

### `src/nvidia_agentic_rag/agents/cache.py`

- `TTLResponseCache.get()`: TTL validation plus LRU touch.
- `TTLResponseCache.put()`: capacity-bound insertion and oldest-entry eviction.
- `CachedResponse`: stores answer, immutable source tuple, and citation audit together.

Trade-off: the reference cache is process-local for isolation and simplicity. Multi-replica
production should use Redis with the same versioned key and tenant scope.

## 4. Corpus isolation and retrieval

### `src/nvidia_agentic_rag/rag/index_manager.py`

- `CorpusIndexManager.ingest()`: document load, metadata enrichment, deterministic node build,
  embedding, atomic temporary persist, manifest creation, and safe directory swap.
- `CorpusIndexManager._build_nodes()`: chunk index, inherited page/section, deterministic ID.
- `CorpusIndexManager.build_retrieval_tool()`: candidate retrieval, score threshold, top-k,
  indirect-injection inspection, stable citation IDs, typed sources, and evidence-only output.
- `CorpusIndexManager.version()`: fingerprint plus runtime retrieval configuration.
- `MultiCorpusIndexManager`: independent course/paper lifecycle and combined version.

### `src/nvidia_agentic_rag/rag/provenance.py`

- `deterministic_node_id()`: stable source identity across equivalent rebuilds.
- `deterministic_citation_id()`: compact stable citation ID.
- `extract_section_title()`: section metadata for text/Markdown-like sources.
- `filter_scored_nodes()`: deterministic threshold and top-k behavior.

Interview point: **corpus boundaries are an architecture and governance decision, not merely a
retrieval tuning trick**.

## 5. Grounding and postconditions

### `src/nvidia_agentic_rag/agents/factory.py`

- `PROMPT_VERSION`: explicit behavioral version used in cache invalidation and response evidence.
- `build_agent()`: FunctionAgent/ReAct selection and strict routing/citation instructions.

### `src/nvidia_agentic_rag/grounding/citations.py`

- `extract_citation_ids()`: parses model citations.
- `citation_coverage()`: heuristic coverage over factual statements.
- `validate_citations()`: rejects unknown IDs and reports missing/insufficient citations.

### `src/nvidia_agentic_rag/schemas.py`

- `SourceReference`, `CitationAudit`, and `ToolTrace`: validated evidence/runtime contracts.

Interview point: citation validation proves **reference integrity and coverage**, not semantic
entailment. An enterprise high-stakes roadmap adds an entailment verifier and human calibration.

## 6. NVIDIA adapters

### `src/nvidia_agentic_rag/nvidia/llm.py`

- Builds the OpenAI-compatible Nemotron adapter with thinking and structured-tool settings.

### `src/nvidia_agentic_rag/nvidia/embeddings.py`

- Separates `passage` from `query` embeddings.
- Sends explicit truncation policy.
- Performs local length diagnostics without incorrectly blocking safe server-side truncation.
- Supports synchronous and asynchronous paths.

### `src/nvidia_agentic_rag/nvidia/errors.py`

- Classifies provider capacity/transient errors and supports API 503/Retry-After behavior.

## 7. Security controls

### `src/nvidia_agentic_rag/safety/guards.py`

- Direct prompt-injection signals at the request boundary.
- Indirect prompt-injection signals over retrieved/tool content.

### `src/nvidia_agentic_rag/tools/calculator.py`

- AST allow-list instead of Python `eval()`.

### `scripts/validate_repo.py`

- Distribution gate for `.env`, key-shaped secrets, and local-inference runtime dependencies.

Security boundary statement: regex guards are signals. Actual enforcement comes from read-only
approved tools, typed schemas, authentication/authorization, budgets, and side-effect policy.

## 8. Evidence and regression

- `tests/unit/`: deterministic cache, policy, citation, provenance, safety, budget, and error tests.
- `scripts/static_quality.py`: AST, line length, and whitespace gate.
- `scripts/audit_corpus.py`: verifies that the indexed training evidence actually exists.
- `evaluation/golden_cases.jsonl`: routing and answer expectations.
- `scripts/evaluate_api.py`: live routing/content/source/citation/cache/latency gate.
- `.github/workflows/ci.yml`: compile, static gate, secret audit, corpus audit, Ruff, mypy, tests.

## 9. Whiteboard sequence

```text
Client
  -> FastAPI request/identity scope
  -> direct prompt guard
  -> versioned exact-response cache
  -> bounded AgentService
  -> Nemotron plans one approved tool
  -> corpus-specific retrieval-only tool
  -> NVIDIA query embedding + local persisted index
  -> score filter + structured provenance + indirect guard
  -> Nemotron grounded synthesis with stable citations
  -> deterministic citation validation
  -> cache answer + sources + audit
  -> typed API response
```

## 10. Strong interview trade-offs

- FunctionAgent is default for native tool calls; ReAct remains an explicit compatibility mode.
- Retrieval-only tools reduce nested LLM calls but place final synthesis responsibility on the
  agent prompt and citation validator.
- Strict citation mode raises trust but may reject formatting errors; audit mode supports gradual
  rollout.
- Process-local cache/state is a deliberate reference boundary; Redis/durable workflows are the
  scale path.
- Local persisted vector storage provides reproducibility; managed hybrid retrieval is the
  multi-replica/large-corpus path.
