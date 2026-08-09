# NVIDIA `ResourceExhausted (33/32)`

## Meaning

The local FastAPI service and persisted RAG index can be healthy while the hosted NVIDIA LLM worker is temporarily full. The error:

```text
ResourceExhausted: Worker local total request limit reached (33/32)
```

is raised during the remote chat-completions call. It is not a Docker health-check or embedding-index error.

## Isolate provider vs agent

Run the minimal direct probes inside the same container and with the same API key:

```bash
docker compose exec app python scripts/nvidia_capacity_probe.py
```

- If `minimal-no-thinking` fails with the same message, the hosted model endpoint/account is at capacity. Wait and retry, or temporarily select another hosted model.
- If both probes pass but `/v1/chat` fails, inspect agent events. Version 2.2 defaults to retrieval-only RAG to remove the nested LLM call used by `QueryEngineTool`.

## Capacity-safe defaults

```dotenv
NVIDIA_MAX_TOKENS=4096
NVIDIA_REASONING_BUDGET=2048
NVIDIA_MEDIUM_EFFORT=true
NVIDIA_MAX_RETRIES=1
AGENT_MAX_CONCURRENT_REQUESTS=1
AGENT_QUEUE_TIMEOUT_SECONDS=10
RAG_TOOL_MODE=retriever
```

The previous 16,384-token output and reasoning budgets were valid for demonstrations but kept the 550B hosted worker occupied for longer. The new defaults are more suitable for local integration tests.

## Retry behavior

The API maps upstream capacity failures to:

```http
HTTP/1.1 503 Service Unavailable
Retry-After: 20
```

```json
{
  "detail": "NVIDIA hosted inference is temporarily at capacity. Retry after a short delay.",
  "error_code": "NVIDIA_CAPACITY_EXHAUSTED",
  "retry_after_seconds": 20
}
```

Client example:

```bash
for attempt in 1 2 3 4; do
  code=$(curl -sS -o response.json -w '%{http_code}' \
    http://localhost:8000/v1/chat \
    -H 'Content-Type: application/json' \
    -H 'X-User-Id: local-user' \
    -d '{"query":"Explain Basic RAG versus Agentic RAG from the indexed documents.","session_id":"capacity-test"}')
  cat response.json; echo
  [ "$code" = "200" ] && break
  [ "$code" != "503" ] && break
  sleep $((attempt * 20))
done
```

## Course-compatible mode

`RAG_TOOL_MODE=query_engine` preserves the original LlamaIndex `QueryEngineTool`, but a RAG turn then typically requires an additional hosted LLM synthesis call. Use `retriever` for hosted capacity-constrained development and `query_engine` only when specifically testing the course pipeline.

## Retry with a clean session

A failed LlamaIndex workflow can retain partial state in its session context. Version 2.2 clears that context automatically after a timeout or provider failure. On older versions, restart the app or use a new `session_id` before retrying.
