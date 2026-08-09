# v6.4.3 Fix Summary

This patch hardens the failure observed for customer-to-book proof questions and the hosted NVIDIA
provider deadline.

## Fixed

- `Can you prove whether C001 purchased B003? Use only available evidence.` now routes to governed
  deterministic analytics insufficiency instead of the 550B agent lane.
- Bare canonical IDs such as `C001`/`B003` are recognized only for purchase-relationship proof
  detection, avoiding accidental broad lookup routing.
- The answer explicitly states that customer/book Gold summaries cannot prove an order-item edge;
  no purchase relationship is inferred from aggregate totals.
- Provider is not invoked for this insufficient-evidence path.
- Default `AGENT_PROVIDER_DEADLINE_SECONDS` increased from 30 to 45 seconds for genuine agent work.
- Added validation that provider deadlines are positive and below `AGENT_REQUEST_TIMEOUT_SECONDS`.
- Run-trace `latency_ms` is now `float`, removing the Pydantic int/float serialization warning.

## Validation performed

- 34 focused regression/unit tests passed.
- Exact relationship-proof regression cases passed:
  - `Can you prove whether C001 purchased B003? Use only available evidence.`
  - `Did C001 buy B003?`
  - `Was B003 purchased by C001?`
- Static quality validation passed for 134 Python files / 19,888 lines.
- Repository validation passed (no packaged `.env`, exposed API-key pattern, or local-inference
  runtime dependency).
- Full unit-suite collection could not run in this execution environment because `pyarrow` is not
  installed; the modified test suites themselves passed.

## Recommended existing local `.env` change

Add or update:

```env
AGENT_PROVIDER_DEADLINE_SECONDS=45
```

Keep:

```env
NVIDIA_TIMEOUT_SECONDS=60
AGENT_REQUEST_TIMEOUT_SECONDS=120
```

Then recreate the app container so the environment is reloaded.
