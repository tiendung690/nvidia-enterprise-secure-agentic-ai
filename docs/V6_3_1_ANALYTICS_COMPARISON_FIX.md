# v6.3.1 — Analytics Comparison / Tool Budget Fix

## Incident reproduced

The request below previously failed with HTTP 422 / `AGENT_TOOL_BUDGET_EXCEEDED`:

```text
Compare customer C001's total spending with the revenue of the highest-revenue book.
Which value is larger, by how much, and what is the percentage difference relative to
C001's spending? Show the calculation and cite the source values.
```

The generic agent path could legitimately execute:

1. `get_customer_order_summary_tool`
2. `get_top_performers_tool`
3. `safe_calculator_tool` for the absolute difference
4. `safe_calculator_tool` for the percentage difference

The old global `AGENT_MAX_SAME_TOOL_CALLS=1` rejected step 4 even though the second calculator
call represented a distinct derived metric.

## Production fix

### 1. Deterministic domain capability

`SecureAnalyticsTools.compare_customer_spending_to_top_book()` performs the exact comparison in
application code. It reads only the curated Delta gold tables, authorizes once, keeps tenant
isolation, masks customer direct identifiers, uses `Decimal` for financial arithmetic, and
returns two independent database source references with the exact Delta versions.

The calculation result contains:

- customer total spending
- highest-revenue book and its revenue
- which value is larger
- absolute difference
- percentage difference relative to customer spending
- human-readable calculation formulas
- both database citations

A zero customer-spending baseline returns `null` percentage instead of dividing by zero.

### 2. Deterministic router fast path

`routing/deterministic.py` recognizes the exact semantic shape “customer <id> spending vs
highest-revenue book” and routes to `compare_customer_spending_to_top_book_tool`. The service
formats a cited response without invoking the provider model. This removes planning latency and
avoids arithmetic drift for this high-value business query.

### 3. Scoped tool-call budgets

The fallback agent lane now uses:

```dotenv
AGENT_MAX_TOOL_CALLS=6
AGENT_MAX_SAME_TOOL_CALLS=1
AGENT_MAX_CALCULATOR_CALLS=3
AGENT_MAX_ANALYTICS_SAME_TOOL_CALLS=3
```

The strict default remains `1` for retrieval/external tools. Only the safe calculator and typed,
read-only analytics capabilities receive bounded repeat limits, so legitimate comparisons work
without opening an unlimited agent loop.

### 4. Observability

When a budget is exceeded, logs now include the tool name, budget scope, attempted call number,
and configured limit. Normal tool-start logs include same-tool and total call ordinals/limits.

## Verification

Targeted regression suite covers:

- exact reported C001 comparison route
- one-tool direct execution with zero provider calls
- two Delta-backed citations in the final answer
- deterministic `15.10` absolute difference and `7.37%` relative difference
- calculator repeated-call allowance up to the scoped limit
- analytics repeated-call allowance up to the scoped limit
- strict repeated-call limit for ordinary corpus tools
- missing customer fail-closed behavior

The repository static-quality and secret/local-model validation scripts must pass before packaging.
