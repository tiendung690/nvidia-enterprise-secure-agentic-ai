# v6.4.3 — Evidence Sufficiency & Provider Deadline Hardening

## Production symptom

A relationship-proof request such as:

```text
Can you prove whether C001 purchased B003? Use only available evidence.
```

fell through to the general agent lane. The hosted 550B reasoning model then consumed the bounded
agent-provider budget and the API returned a provider-unavailable 503 near the 30-second mark.
Docker and the Delta tools were healthy, and NVIDIA HTTP requests were accepted, so increasing the
raw HTTP timeout alone did not address the routing failure.

## Root cause

The deterministic analytics router already knew that the curated Gold tables have customer and book
summary grains only, but its unsupported-relationship matcher expected natural-language phrases such
as `customer C001 purchased ...`. It did not recognize canonical bare IDs in `C001 purchased B003`.

The provider lane also defaulted to a 30-second aggregate deadline even though the overall request
budget was 120 seconds and the NVIDIA client timeout was 60 seconds.

## Fix

1. Recognize canonical bare customer/book IDs only inside purchase-relationship proof phrasing.
2. Route that claim to `analytics_query_tool` with `operation=unsupported` and
   `customer_book_relation_not_available`.
3. Return the application-owned insufficiency explanation directly; do not call an LLM.
4. Raise the bounded agent-provider deadline to 45 seconds for requests that genuinely require the
   agent lane, while validating it remains below the request deadline.
5. Preserve fractional latency in persisted run traces.

## Expected behavior

```text
route.kind                  = analytics
analytics operation         = unsupported
request_outcome             = insufficient_context
provider_trace.invoked      = false
provider_trace.model_tier   = not_used
tool                        = analytics_query_tool
```

The answer explains that customer/book Gold summaries cannot prove a customer-to-book/order-item
relationship and that no purchase relationship was inferred from aggregate totals.

## Recommended local `.env`

```env
NVIDIA_TIMEOUT_SECONDS=60
AGENT_PROVIDER_DEADLINE_SECONDS=45
AGENT_REQUEST_TIMEOUT_SECONDS=120
```

Do not solve deterministic evidence gaps by increasing the provider deadline. The evidence gate must
win before provider routing whenever the available governed grain cannot prove the requested claim.
