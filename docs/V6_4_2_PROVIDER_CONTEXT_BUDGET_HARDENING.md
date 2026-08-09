# v6.4.2 — Provider Context Budget Hardening

## Incident signature

A short request reached NVIDIA with an assembled prompt of 258,459 tokens while the request also
reserved 2,048 output tokens. The hosted endpoint reported a 258,048-token maximum total context,
so the request exceeded the provider budget by 2,459 tokens.

The user query itself was not large. The failure was therefore an orchestration/context-management
bug, not a malformed client request.

## Root causes

1. `NVIDIA_CONTEXT_WINDOW` defaulted to `1_000_000`, so LlamaIndex was told it could retain far
   more workflow history than the managed Nemotron-3-Ultra endpoint accepted.
2. The legacy workflow-context mode could persist LlamaIndex agent/tool observations across
   requests. Reusing a session could therefore accumulate hidden provider-facing history even
   though the application also maintained a separate bounded conversation projection.
3. Ordinary company-knowledge wording such as `our strategy` was sent to the complex agent lane
   unless the user explicitly named an indexed corpus. This added an avoidable planning call
   before retrieval.
4. Context-length rejection was classified only as a generic 400/provider rejection, obscuring
   the actionable failure mode.

## Fixes

- Default provider context ceiling: `258048` tokens.
- Runtime safety reserve: `8192` tokens.
- The model capability guard caps a stale `NVIDIA_CONTEXT_WINDOW=1000000` environment value to
  the known managed-endpoint ceiling for `nvidia/nemotron-3-ultra-550b-a55b`.
- LlamaIndex receives an effective context window of `249856` tokens, leaving provider-side
  headroom for chat templates, tool schemas, tokenization differences, and output reservation.
- Provider workflow `Context` is request-scoped. Conversation continuity comes only from the
  bounded conversation store and governed memory.
- `CONVERSATION_CONTEXT_MODE=legacy` is rejected at startup.
- Implicit company-knowledge questions route to bounded multi-corpus direct RAG before synthesis.
  If relevant authorized evidence is unavailable, the existing enterprise fail-closed gate returns
  insufficient context instead of asking the LLM to invent company facts.
- Provider context overflow now maps to `NVIDIA_CONTEXT_LENGTH_EXCEEDED` and is non-transient.
- `/health/ready` exposes the hard provider limit, effective LLM window, safety reserve, and output
  budget so deployment configuration can be verified without reading source code.
- Response cache keys include the effective provider context contract so a context-policy upgrade
  cannot reuse an answer cached under the old model budget.

## Expected runtime contract

For the primary model with default settings:

```text
provider hard ceiling             258048
runtime context safety reserve      8192
LlamaIndex effective window        249856
max generated tokens                2048
```

The effective LlamaIndex window is deliberately below the provider ceiling. LlamaIndex can compact
agent workflow memory before the request approaches the upstream hard limit.

## Deployment check

After rebuilding, verify:

```bash
curl -s http://localhost:8000/health/ready | jq
```

Expected fields include:

```json
{
  "llm_provider_context_limit_tokens": 258048,
  "llm_effective_context_window_tokens": 249856,
  "llm_context_safety_tokens": 8192,
  "llm_max_output_tokens": 2048,
  "conversation_context_mode": "bounded"
}
```

Then retry the regression query using a new session ID and again using a previously reused session.
Neither path should reach the provider with an oversized prompt.
