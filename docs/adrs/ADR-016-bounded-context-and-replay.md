# ADR-016: Bounded context and replayable trace

**Decision:** use a fresh workflow context per request, reassemble a bounded recent-turn projection,
and persist a separate trace keyed by run ID.

**Why:** raw session context grows without a deterministic token bound and cannot serve as a durable
audit/replay mechanism.

**Consequence:** continuity is explicit and bounded. Long-term facts require promotion; raw forensic
history belongs in trace storage with retention controls.
