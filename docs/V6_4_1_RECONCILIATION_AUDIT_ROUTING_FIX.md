# v6.4.1 - Reconciliation Audit Routing Fix

## Incident reproduced

A valid business-analytics request asked to audit the two Gold summary tables for consistency,
report customer spending vs book revenue, quantity totals, summed order counts, expected equality
from table grain, and possible double-counting.

The API returned `request_outcome=insufficient_context` in about 70 ms while reporting one
`analytics_query_tool` call and zero provider calls.

## Root cause

The v6.4.0 deterministic router used a permissive entity regex:

```text
customer <token>
book <token>
```

The phrase `total customer spending` therefore produced a false customer ID of `spending`.
Because the request said `audit ... for consistency` rather than the exact words `reconcile` or
`reconciliation`, the reconciliation rule did not match. The router eventually generated:

```json
{"dataset":"gold_customer_order_summary","operation":"lookup","entity_id":"spending"}
```

The Gold repository correctly found no customer with that ID, so the control plane failed closed
as `insufficient_context`. Data, authorization, Delta, citations, and the analytics executor were
not the cause.

## Fix

v6.4.1 hardens both sides of the routing decision:

1. Business nouns such as `spending`, `revenue`, `quantity`, `orders`, `amount`, `grain`, and
   `table` are not accepted as shorthand entity IDs.
2. Explicit forms such as `customer id alpha` and `book code catalog-x` remain supported.
3. Shorthand identifiers such as `customer C001`, `customer C001's`, UUID-like values, and
   uppercase codes remain supported.
4. Cross-Gold audit intent recognizes `audit`, `consistency`, `double-counting`, and grain wording
   when customer + book table context is present.
5. Reconciliation rendering now states both expected equality and observed equality. Order-count
   sums remain visible but are marked not semantically comparable and possible double-counting.

## Expected deterministic plan

```json
{"dataset":"cross_gold","operation":"reconcile"}
```

No NVIDIA provider call is required.

## Expected business result for demo Gold v0

| Check | Customer Gold | Book Gold | Equality expected? | Observed equal? |
| --- | ---: | ---: | --- | --- |
| amount vs revenue | 350.90 | 350.90 | Yes | Yes |
| quantity vs quantity | 7 | 7 | Yes | Yes |
| summed order counts | 4 | 4 | No | Yes |

The third equality is observational only. `total_orders` is a distinct-count style metric exposed
at different summary grains; summing across book rows can count one order more than once when the
order contains multiple books. Equal sums therefore do not prove reconciliation.

## Regression protection

The unit suite now includes the exact incident prompt and asserts:

- route = `analytics_query_tool`
- plan = `cross_gold/reconcile`
- provider invoked = false
- request outcome = success
- citation coverage = 1.0
- answer completeness = 1.0
- provenance validation = valid
- double-count warning is present
- `customer spending` and `book revenue` are not parsed as entity lookups
