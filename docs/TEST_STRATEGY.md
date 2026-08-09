# Test and evaluation strategy

## Unit and deterministic core

- cache hit, TTL expiry, LRU capacity, tenant/session scope, index-version invalidation;
- citation-ID existence, unknown-ID rejection, and factual-sentence coverage;
- deterministic node and citation IDs;
- section extraction and retrieval score filtering;
- direct and indirect prompt-injection signals;
- safe calculator allow-list and abuse limits;
- deterministic tool-call budget;
- source preservation across fresh and cached responses;
- mocked agent event stream and tool-result provenance collection.

The default suite enforces >=90% coverage on testable core logic. Framework/provider adapters are validated through integration and live gates rather than counted in that unit metric.

## Integration

- mocked NVIDIA sync/async embedding clients, including query/passage and truncate fields;
- build and reload persisted LlamaIndex indexes;
- atomic index swap after successful ingestion and rollback after failure;
- FastAPI response schema, provider error mapping, admin authorization, and request IDs;
- multi-corpus routing and source metadata.

## Live opt-in

- NVIDIA chat completion;
- NVIDIA query/passage embedding;
- Docker ingest, readiness, grounded chat, cache repeat, and metrics;
- golden evaluation in `scripts/evaluate_api.py`.

## Release gates

- routing accuracy = 100% on the maintained golden set;
- required concept coverage >= 90%;
- citation-valid rate = 100%;
- exact-response cache-hit rate = 100%;
- cache p95 < 500 ms;
- fresh p95 < 60 s for the hosted reference endpoint;
- zero exposed-key pattern and zero packaged `.env`;
- prompt-injection and indirect-injection regression cases pass.
