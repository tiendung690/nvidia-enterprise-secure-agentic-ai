# Migration v4 -> v5

## Behavior changes

1. `CITATION_VALIDATION_MODE` default changes from `audit` to `strict`.
2. `CITATION_MINIMUM_COVERAGE` changes from `0.70` to `0.90`.
3. Invalid cited answer is conservatively repaired once; if still invalid, API returns 422.
4. `AGENT_MAX_CONCURRENT_REQUESTS` changes from 1 to 2.
5. `AGENT_MAX_SAME_TOOL_CALLS` changes from 2 to 1.
6. Course final top-k changes from 8 to 6.
7. Same-session behavior is configurable: `serialize` or `reject`.
8. Error responses now use stable error codes instead of generic 504.
9. Chat success response adds request outcome, safety audit, provider trace and latency breakdown.

## New environment variables

```dotenv
PROVIDER_RETRY_MAX_ATTEMPTS=3
PROVIDER_RETRY_BASE_SECONDS=1.5
PROVIDER_RETRY_MAX_SECONDS=20
PROVIDER_RETRY_JITTER=true
PROVIDER_CIRCUIT_BREAKER_ENABLED=true
PROVIDER_CIRCUIT_BREAKER_FAILURES=5
PROVIDER_CIRCUIT_BREAKER_RESET_SECONDS=60

SESSION_CONCURRENCY_POLICY=serialize
SESSION_LOCK_WAIT_TIMEOUT_SECONDS=120

CITATION_REPAIR_MODE=conservative
CITATION_REPAIR_MAX_ATTEMPTS=1

ANSWER_BUDGET_SIMPLE_WORDS=300
ANSWER_BUDGET_COMPARISON_WORDS=700
ANSWER_BUDGET_LONG_WORDS=1200
APP_PORT=8000
```

## Client migration

Clients should handle:

- 409 `SESSION_BUSY` / `SESSION_WAIT_TIMEOUT`
- 429 `CAPACITY_WAIT_TIMEOUT`
- 503 `NVIDIA_*`
- 504 `AGENT_EXECUTION_TIMEOUT`
- 422 `CITATION_VALIDATION_FAILED`

Use `Retry-After` when present. Display `request_id` in support UI.

## Index migration

v5 does not change stored node schema. Existing v4 indexes can be reused when their manifest remains
valid. Re-ingest is recommended when document/security metadata changed, not only because the app
version changed.
