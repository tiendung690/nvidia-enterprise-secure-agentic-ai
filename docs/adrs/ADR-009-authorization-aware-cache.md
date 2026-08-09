# ADR-009: Authorization-aware cache and session

## Decision

Cache/session scope bao gồm tenant, user, authorization hash/version, purpose, answer mode, policy,
index, prompt và model settings.

## Consequence

Giảm hit rate so với global cache nhưng ngăn stale privilege và cross-tenant answer reuse.
