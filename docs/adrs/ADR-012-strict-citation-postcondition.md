# ADR-012: Strict Citation Postcondition

## Status

Accepted in v5.

## Context

P08 returned an answer with citation coverage 0.50 and `valid=false`. Prompt instructions alone did
not guarantee grounded output.

## Decision

- Parse factual prose, bullets and Markdown table rows.
- Validate current-turn citation IDs and claim coverage.
- Apply one conservative repair that removes uncited claims without inventing citations.
- Reject the answer when postcondition still fails.
- Mark blocked/refusal responses as citation-not-applicable.

## Consequences

Some verbose content may be removed, but no unverified enterprise factual answer is returned in
strict mode.
