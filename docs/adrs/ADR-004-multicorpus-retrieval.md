# ADR-004: Isolate course and research corpora

## Decision

Use one persisted index and one retrieval tool per semantically coherent corpus.

## Rationale

A single mixed index allowed research-survey chunks to crowd out explicit course definitions. Isolation improves routing precision and enables corpus-specific thresholds, top-k, lifecycle, ACLs, and evaluation.

## Consequences

The planner must route correctly, and cross-corpus questions may call both tools. Citation IDs are source-derived and therefore remain unambiguous across calls.
