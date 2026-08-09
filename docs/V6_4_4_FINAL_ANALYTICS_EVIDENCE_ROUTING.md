# v6.4.4 — Final Analytics Evidence Routing

## Goal

The ten governed Gold analytics demo prompts must remain correct even when hosted NVIDIA inference
is slow or unavailable. Structured facts, formulas, reconciliation, and known evidence gaps are
application-owned capabilities and therefore do not require a model call.

## Execution contract

| Case | Capability | Expected outcome | Hosted provider |
| --- | --- | --- | --- |
| 1 | customer + top-book facts | success | not used |
| 2 | deterministic comparison | success | not used |
| 3 | book ranking + revenue/unit | success | not used |
| 4 | customer ranking + avg/order | success | not used |
| 5 | cross-Gold reconciliation | success | not used |
| 6 | customer-book proof | insufficient_context | not used |
| 7 | customer-book contribution metric | insufficient_context | not used |
| 8 | prior-period growth | insufficient_context | not used |
| 9 | supported facts + causal abstention | success | not used |
| 10 | grain-aware full audit | success | not used |

## Evidence-sufficiency rules

1. Customer-book purchase/contribution claims require governed `customer_book` or `order_item`
   evidence. Marginal customer and book summaries cannot prove or calculate that relationship.
2. Period-over-period growth requires a governed time dimension and comparable prior-period values.
3. Descriptive Gold aggregates can prove observed rankings and metrics, but cannot establish why a
   ranking occurred. Causal explanations are explicitly separated from supported facts.
4. Distinct-count order metrics are non-additive across book grain and are never reconciled merely
   because their observed sums happen to be numerically equal.

## Failure semantics

Known missing evidence is a valid domain outcome: HTTP 200 with
`request_outcome=insufficient_context`, one deterministic analytics-tool call, and
`provider_trace.invoked=false`. Provider 503/timeout is reserved for requests that genuinely need
hosted inference and cannot be served by a deterministic capability.
