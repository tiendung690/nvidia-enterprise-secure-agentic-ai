# Interview playbook — Strong SSE/TL to TA/SA

## 90-second architecture answer

“I designed Agentic RAG as a controlled execution platform rather than a free-running LLM. The agent uses NVIDIA Nemotron for planning and structured tool calls, but deterministic code owns concurrency, deadlines, tool budgets, tenant/session isolation, cache invalidation, and citation validation. I split course material and research papers into separate LlamaIndex indexes and expose each as a retrieval-only tool. Retrieved nodes have deterministic IDs and typed provenance. The final answer must cite source IDs, and a postcondition validator checks citation existence and coverage before the response is cached. Cache keys include user, session, query, index version, model settings, and prompt version, so stale or cross-user answers cannot be reused.”

## Deep-dive questions

### Why two indexes instead of one?

A mixed index produced a real false-negative: research survey chunks dominated similarity results for “Basic RAG vs Agentic RAG.” Corpus isolation makes routing explicit, improves precision, and gives each corpus independent top-k, score thresholds, lifecycle, and access policy.

### Why retrieval-only tools?

`QueryEngineTool` performed generation inside the tool and then the agent generated again. Retrieval-only tools preserve raw evidence and reduce LLM calls, latency, cost, and provenance loss.

### Why deterministic node IDs?

Random IDs change after re-ingestion, making citations, evaluation regressions, cache invalidation, and incident analysis unstable. Deterministic IDs make the same chunk traceable across builds; content changes deliberately change the ID.

### Why does cache include prompt/model/index versions?

The same question can produce a materially different or policy-incompatible answer after a prompt, model, embedding corpus, or generation-budget change. Version-aware keys guarantee safe invalidation.

### Is citation validation enough to prove truth?

No. It proves that citation IDs exist and measures claim coverage. It does not prove entailment. For high-stakes systems I would add a deterministic fact check where possible and a calibrated entailment/faithfulness verifier with human sampling.

### Why not allow the agent to enforce its own loop limit?

A prompt is probabilistic. Cost, latency, and safety limits must be enforced in code. The runtime rejects excessive total calls or repeated calls to the same tool.

### What would change for write tools?

I would introduce tool risk levels, resource-level authorization, idempotency keys, explicit confirmation/HITL, audit logs, and compensation. The LLM would propose the action; a policy gateway would authorize and execute it.

## Evidence to show an interviewer

- `pytest -m 'not live'`: core unit suite and coverage gate.
- `scripts/evaluate_api.py`: live golden routing, citations, source, cache, and latency report.
- `sources` in the API response: stable IDs, scores, sections, excerpts.
- `citation_audit`: valid/invalid, unknown IDs, and coverage.
- `tool_trace`: tool duration and call count.
- `manifest.json`: corpus fingerprint and index version.
- component and sequence diagrams in `docs/diagrams/`.

## Honest production statement

“This is a production-oriented reference implementation with reproducible evidence. It is not a claim that the system has already passed enterprise traffic, security, or disaster-recovery certification. The next deployment gates are OIDC/ACL, shared state, managed vector storage, load/chaos tests, and canary SLO validation.”
