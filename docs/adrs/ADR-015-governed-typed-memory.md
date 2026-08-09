# ADR-015: Governed typed durable memory

**Decision:** separate policy, preference, fact, episode and trace. Policy/preference use exact
enumeration; fact/episode use scoped discovery; trace is append-only. All writes pass a server-side
promotion gate.

**Why:** a catch-all vector store cannot enforce deterministic policy, lifecycle, provenance,
supersession or deletion correctly.

**Consequence:** schema and APIs are more explicit, but memory behavior becomes auditable,
idempotent, tenant-safe and replayable.
