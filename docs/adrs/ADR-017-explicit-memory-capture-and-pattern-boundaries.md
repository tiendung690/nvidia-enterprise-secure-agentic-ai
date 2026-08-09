# ADR-017 — Explicit memory capture and evidence-based RAG pattern boundaries

## Status

Accepted for v6.0.0.

## Context

The target architecture separates query transformation, retrieval, refinement, orchestration and
memory write governance. Adding every named RAG pattern without the required source structure
would create silent quality and security failures.

## Decision

1. Auto-capture is restricted to user-stated durable response preferences on a deterministic
   allow-list. It never infers facts, personality, policy or sensitive attributes.
2. The original request is inspected for direct and indirect prompt-injection signals before any
   normalized preference candidate is produced.
3. Exact policy/preference enumeration fails closed when it exceeds count or prompt budgets.
4. Document retrieval composes guarded Multi-Query, vector + BM25, RRF, reranking and a bounded
   corrective fallback.
5. HyDE remains an optional provider-backed extension because hypothetical documents must not be
   silently introduced into a secure evidence path.
6. Hierarchical RAG is not enabled until the corpus has a canonical hierarchy and a tested coarse-
   branch fallback.
7. Graph RAG is not enabled until entity resolution, relationship provenance, incremental update
   and deletion propagation exist as governed write-path components.
8. The PostgreSQL memory adapter currently provides exact lookup and scope-filtered full-text
   discovery. A production deployment that needs semantic fact/episode memory must add a managed
   pgvector/vector-store adapter with metadata pre-filter; the repository does not claim that FTS
   alone is semantic vector retrieval.

## Consequences

- The implementation is smaller, auditable and safer than a pattern checklist.
- Explicit preferences compound safely across turns without arbitrary model-authored memory.
- Retrieval and memory limits can return a typed 503 rather than silently dropping policy.
- A deployment-specific vector memory adapter remains an acceptance gate for large or highly
  paraphrased fact/episode memory workloads.
