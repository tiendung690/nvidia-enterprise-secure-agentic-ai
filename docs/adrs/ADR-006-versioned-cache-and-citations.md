# ADR-006: Version-aware cache and deterministic citations

## Decision

Scope cached answers by tenant, session, normalized query, index, model configuration, agent mode, and prompt version. Cache only citation-valid grounded answers.

## Rationale

Answers become stale after corpus, prompt, model, or policy changes. Random source IDs make evidence impossible to compare across index builds.

## Consequences

Cache reuse is safe but deliberately conservative. Multi-replica production requires a shared tenant-aware cache.
