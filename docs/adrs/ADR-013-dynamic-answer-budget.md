# ADR-013: Dynamic Answer Budget

## Status

Accepted in v5.

## Context

Single-component P10 answers were approximately 9 KB, increasing provider occupancy, cost and queue
contention.

## Decision

Classify query complexity as simple/comparison/long and append an internal response contract with a
word/source budget. Keep model max tokens as a hard upper bound.

## Consequences

Answers become more predictable and concise. The heuristic is intentionally simple and should be
replaced by a measured router when traffic patterns justify it.
