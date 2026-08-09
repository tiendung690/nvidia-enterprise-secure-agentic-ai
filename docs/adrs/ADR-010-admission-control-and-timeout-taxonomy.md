# ADR-010: Admission Control and Timeout Taxonomy

## Status

Accepted in v5.

## Context

P09/P10 showed generic 504 responses after ~10 seconds while another request was still executing.
Queue wait, session lock wait and actual execution deadline were indistinguishable.

## Decision

- Acquire session admission before global capacity.
- Support `serialize` and `reject` same-session policies.
- Return 409 for session contention, 429 for global capacity wait, and 504 only for actual execution
  deadline.
- Emit stage-level wait latency.

## Consequences

Correctness and client retry behavior become predictable. Serialize mode may increase end-to-end
latency; reject mode shifts retry UX to the client.
