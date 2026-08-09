# Deep repository review and remediation

## Baseline findings

The uploaded repository already demonstrated working Docker hosting, NVIDIA chat/embedding calls, multi-corpus routing, retrieval-only RAG, exact-response caching, and structured sources. The review found several correctness and scale risks:

1. The success metric in `AgentService.chat()` was unreachable because the method returned before incrementing it.
2. Cache, session contexts, and per-session locks were unbounded in memory.
3. Cache keys omitted tenant identity, model/generation settings, and prompt version.
4. Different users could collide by choosing the same `session_id`.
5. Tool-call limits existed only in the prompt, not as deterministic runtime policy.
6. Sources were typed as raw dictionaries, with no schema validation.
7. Citation IDs were absent from evidence; citation correctness could not be verified.
8. Node IDs were random and unstable across re-ingestion.
9. Text sources lacked `chunk_index` and section metadata; source IDs could not support stable regression evidence.
10. Index rebuild wrote directly to the active location, allowing partial index state after failure.
11. NVIDIA embedding truncation was not sent explicitly, and local preflight raised even when server-side safe truncation was acceptable.
12. Direct prompt-injection detection existed, but retrieved evidence had no indirect-injection audit.
13. `/v1/chat` did not expose index/prompt versions or tool-duration traces.
14. The archive contained a `.env` file, creating a secret-distribution risk.
15. Tests had drifted from code (`CorpusSpec.min_score`, token defaults), and live tests imported optional dependencies during collection.

## Remediation implemented

- Added deterministic source IDs and stable citation IDs.
- Added page, section, and chunk-index metadata.
- Added candidate retrieval followed by score threshold and top-k limiting.
- Added indirect-injection signals for retrieved text.
- Added claim-level citation prompt rules and deterministic citation validation.
- Added bounded TTL-LRU cache and tenant/session/model/index/prompt-aware keys.
- Added session TTL/capacity cleanup.
- Added deterministic tool-call budgets.
- Added typed `SourceReference`, `CitationAudit`, and `ToolTrace` models.
- Added atomic temporary-index build and swap.
- Added explicit NVIDIA embedding `input_type` and `truncate` policy.
- Added Prometheus cache, tool, retrieval, citation, and security metrics.
- Added live golden evaluation and offline corpus audit across the four course PDFs and eRAG paper.
- Runtime ingestion now clears cached answers and explicitly requires an application restart to
  bind startup-created tools to rebuilt retrievers.
- Removed `.env` from the distributable and strengthened repository secret validation.

## Remaining enterprise gaps

- In-memory cache/session state is process-local; replace with Redis or durable workflow state for multiple replicas.
- Local persisted LlamaIndex storage is single-writer; use a managed vector store for horizontal scale.
- Development identity headers are not an authentication mechanism.
- Retrieval does not yet enforce tenant/document ACL metadata filters.
- External tool authorization remains static because only read-oriented tools are registered.
- Citation validation confirms reference IDs and coverage, not semantic entailment. Add an entailment verifier or calibrated judge for high-stakes use.
- Hosted inference capacity and latency require load tests and retry/backoff validation in the target subscription.
