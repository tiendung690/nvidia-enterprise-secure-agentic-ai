# ADR-011: Provider Resilience and Circuit Breaker

## Status

Accepted in v5.

## Context

NVIDIA hosted inference can return transient 429/502/503/504/capacity errors. Manual retry is not a
production strategy, while unlimited retry creates retry storms.

## Decision

- Bounded runtime retry with exponential backoff and jitter.
- Discard partial attempt evidence and recreate workflow context before retry.
- Circuit breaker opens after configurable transient failures.
- Retry whole workflow only because current reference tools are read-only.

## Consequences

Transient availability improves and failures become observable. Future write tools require
idempotency/HITL before workflow retry is allowed.
