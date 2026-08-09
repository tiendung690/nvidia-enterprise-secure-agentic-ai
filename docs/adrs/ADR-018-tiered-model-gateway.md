# ADR-018 — Tiered model gateway with degrade-to-fast

## Status
Accepted (v6.2)

## Context
v6.1 wired a single reasoning model (`nvidia/nemotron-3-ultra-550b-a55b`) into every
provider call: agent orchestration, direct-RAG synthesis, and memory extraction. Two
consequences followed. First, simple single-corpus synthesis paid flagship-model latency
and capacity cost for work a small model handles. Second, the documented 550B capacity
incidents (`docs/TROUBLESHOOTING_NVIDIA_CAPACITY.md`) turned into hard request failures
once the retry budget was exhausted, even though a smaller model on the same endpoint was
healthy.

## Decision
Introduce `gateway.ModelGateway` as the single tier-selection point:

- Two clients on the same OpenAI-compatible NIM endpoint: `complex` (existing model) and
  an optional `fast` tier (`NVIDIA_FAST_LLM_MODEL`, reasoning disabled, tighter output cap).
- Deterministic routing, application-owned: only **simple direct-RAG synthesis** is
  eligible for the fast tier (`MODEL_TIER_ROUTING_ENABLED=true`). The agent lane keeps the
  complex model for reliable function calling. The LLM never chooses its own tier.
- **Degrade-to-fast** is a resilience policy, separate from routing: when complex
  synthesis exhausts its transient retry budget, the request downgrades once to the fast
  tier instead of failing (`GATEWAY_DEGRADE_TO_FAST`, default on, inert until a fast model
  is configured).
- The chosen tier and any degradation are recorded on `ProviderTrace`
  (`model_tier`, `degraded_to_fast`) and in `agentic_ai_model_tier_selections_total` /
  `agentic_ai_gateway_tier_degrades_total`.

## Consequences
- Model choice becomes configuration, and the cache key already embeds the model name, so
  tier changes stale their own entries.
- The shared provider circuit breaker is intentionally unchanged: an open circuit blocks
  both tiers because it signals endpoint-level distress; degrade targets model-queue
  capacity errors, which are the observed failure mode.
- Agent-lane degradation is explicitly out of scope: mid-run model swaps under a
  function-calling workflow are not supported by the orchestrator and would blur the
  reasoning contract. Revisit only with per-tier circuit breakers and a rebuilt agent.
