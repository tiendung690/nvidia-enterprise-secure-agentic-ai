# ADR-005: Retrieval tools return evidence, not generated answers

## Decision

Local RAG tools return structured evidence JSON with provenance. Only the agent performs final synthesis.

## Rationale

Nested QueryEngine generation increased latency and cost and weakened source traceability.

## Consequences

The final prompt carries more raw evidence, so top-k, score filtering, and citation validation become essential.
