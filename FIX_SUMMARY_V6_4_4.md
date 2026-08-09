# v6.4.4 Final Analytics Evidence-Routing Fix

This release hardens the ten production-demo Gold analytics cases so they no longer depend on
hosted NVIDIA inference when the answer is deterministic or when the governed serving contract is
known to lack the required evidence.

## What changed

- Added deterministic `customer_and_top_book` execution for the two-fact customer/top-book query.
- Broadened the customer/top-book comparison route to canonical bare IDs such as `C001`.
- Added a generalized customer-book derived-metric evidence guard for percentage/share/spend/unit
  questions that require unavailable customer-book/order-item grain.
- Added temporal evidence sufficiency for prior-period / last-month / MoM / QoQ / YoY requests.
- Added `top_book_causal_guard`: returns supported top-book facts with citations while explicitly
  refusing unsupported causal explanations.
- Hardened reconciliation routing for prompts that say `both Gold tables` without repeating the
  customer/book dataset names.
- Upgraded the semantic registry to `semantic-registry-v2` with explicit capability metadata for
  time, causal evidence, and customer-book grain.
- Preserved human-readable evidence-sufficiency reasons in policy telemetry and safety audit output.
- Added a regression suite covering all ten demo analytics prompts. Every one is deterministic and
  has `provider_trace.invoked == false`.

## Expected behavior for cases 6-8

The API returns HTTP 200 with `request_outcome=insufficient_context`; this is a valid governed
business outcome rather than an infrastructure failure. No hosted provider call is attempted.

## Expected behavior for case 9

The API returns supported descriptive facts and a separately labeled causal-abstention section.
It corrects a false premise if the requested book is not actually the highest-revenue book.
