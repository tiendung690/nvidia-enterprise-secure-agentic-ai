# Agentic AI Design System v5

Design system này là bộ **contracts, patterns và quality gates** để các team xây nhiều Agentic AI
use case mà không lặp lại các lỗi security/reliability của demo agent.

## 1. Design principles

1. **Deterministic outside, probabilistic inside** — auth, policy, budgets và validation bằng code.
2. **Least agency** — agent chỉ có tool tối thiểu cần cho goal.
3. **Current-turn grounding** — memory hỗ trợ intent, không thay evidence.
4. **Typed capabilities** — business operation là function contract, không phải arbitrary SQL/API.
5. **Fail closed for enterprise facts** — thiếu authorized evidence thì không trả company fact.
6. **Postconditions over prompts** — prompt hướng dẫn; validator quyết định answer có được trả hay không.
7. **Bounded autonomy** — tool count, same-tool count, timeout, retry và concurrency đều có budget.
8. **Observable decisions** — mỗi boundary có outcome và latency riêng.

## 2. Core design tokens

### 2.1 Identity token

```text
user_id + tenant_id + roles + departments + clearance + authz_version
```

Dùng để scope policy, session và cache. Prompt không được phép override identity token.

### 2.2 Purpose token

Mọi request phải khai báo business purpose. Một capability có thể hợp lệ cho `customer-support`
nhưng không hợp lệ cho `research`.

### 2.3 Evidence token

```json
{
  "citation_id": "SABC123",
  "source_id": "corpus:file:chunk",
  "classification": "public",
  "source_version": 1,
  "authorization_decision_id": "PD-..."
}
```

Citation ID là handle để model cite; source metadata là bằng chứng để runtime/auditor kiểm tra.

### 2.4 Outcome token

```text
success | cache_hit | blocked | policy_denied | insufficient_context |
citation_validation_failed | capacity_rejected | session_busy |
provider_unavailable | execution_timeout | output_blocked
```

Outcome phải ổn định để frontend, support, SRE và analytics dùng chung.

## 3. Component contracts

### Agent contract

- Input: verified request context + user goal.
- Output: answer candidate, tool events, no hidden authorization decision.
- Không được bypass tool gateway.
- Không được phát sinh write side effect nếu chưa có approval contract.

### Tool contract

Mỗi tool phải khai báo:

```text
name
business purpose
input schema
output schema
read/write classification
tenant behavior
idempotency behavior
timeout/retry policy
data classification
```

Tool output phải là structured JSON gồm evidence và policy audit; raw prose-only tool output không đủ
cho enterprise observability.

### Context broker contract

```text
vector candidates
 -> document policy authorization
 -> lifecycle/version filter
 -> masking/minimization
 -> indirect injection inspection
 -> source limit
 -> evidence package
```

### Model gateway contract

- Provider timeout riêng.
- Retry transient-only.
- Circuit breaker.
- Attempt telemetry.
- Không retry non-idempotent workflow nếu chưa có idempotency/compensation.

### Grounding contract

- Citation IDs phải thuộc current sources.
- Table row là một factual claim unit.
- Uncited summary vẫn bị tính là claim.
- Strict mode không trả invalid answer.
- Conservative repair không tự gắn citation.

### Memory contract

- Conversation memory: intent/continuity.
- Evidence memory: không mặc định tái sử dụng qua turn.
- Long-term memory: phải có tenant/auth lifecycle và delete/retention policy.
- Cache không đồng nghĩa memory.

## 4. Pattern catalog

### Pattern A — Single-corpus grounded QA

```text
query -> course/paper tool once -> 5–6 sources -> concise cited answer
```

Dùng cho knowledge assistant. Gate: one tool call, citation valid, no external facts.

### Pattern B — Multi-corpus comparison

```text
planner decomposes two source domains
 -> each corpus tool once
 -> separate citation namespaces
 -> synthesis with explicit distinctions
```

Dùng cho ReAct vs eRAG, policy vs operational state.

### Pattern C — Operational source-of-truth lookup

```text
exact entity ID -> typed DB tool -> tenant/RLS -> database citation
```

Không dùng PDF/vector result để khẳng định trạng thái hiện tại của order/account.

### Pattern D — Insufficient authorized context

```text
no authorized evidence -> deterministic refusal -> no company fact -> no cache
```

### Pattern E — Injection fast block

```text
prompt guard -> blocked in milliseconds -> zero tool/provider call
```

### Pattern F — Provider degradation

```text
transient error -> bounded retry -> circuit breaker -> typed 503 + Retry-After
```

### Pattern G — Same-session concurrency

- Chat UI: `reject` + disable Send.
- Batch/API workflow cần ordering: `serialize`.

### Pattern H — Human-in-the-loop write action

Chưa bật trong reference runtime. Khi bổ sung:

```text
plan -> read evidence -> proposed action -> policy -> human approval -> idempotent write -> audit
```

Không cho model tự động retry write side effect.

## 5. Anti-patterns

- Vector DB được coi là source of truth.
- Prompt chứa role/tenant và được tin hơn JWT.
- Một generic tool có quyền HTTP/SQL/shell rộng.
- Session ID là cache key duy nhất.
- Reuse source/citation từ previous turn.
- Citation validator chỉ regex citation existence, không đo claim coverage.
- Same-session requests chạy song song trên cùng mutable context.
- Queue timeout và execution timeout cùng map thành 504.
- Retry toàn workflow có write tool mà không có idempotency.
- Trả `citation_audit.valid=false` nhưng vẫn HTTP 200 trong strict mode.

## 6. API design contract

### Success

```json
{
  "request_outcome": "success",
  "answer": "... [SABC123].",
  "sources": [],
  "citation_audit": {
    "applicable": true,
    "valid": true,
    "coverage": 1.0
  },
  "latency_breakdown": {},
  "provider_trace": {}
}
```

### Session busy

```json
{
  "error_code": "SESSION_BUSY",
  "detail": "Another request for this session is still being processed.",
  "retry_after_seconds": 5,
  "request_id": "..."
}
```

### Citation failure

```json
{
  "error_code": "CITATION_VALIDATION_FAILED",
  "detail": "The answer could not be returned because its citations were not verifiable.",
  "citation_audit": {}
}
```

## 7. Quality gate template cho use case mới

| Gate | Requirement |
|---|---|
| Tool routing | 100% golden cases |
| Citation valid | 100% returned enterprise factual answers |
| Unauthorized source | 0 |
| Cross-tenant leakage | 0 |
| Prompt injection tool call | 0 |
| Cache isolation | tenant/user/auth/purpose/version scoped |
| Concurrency | behavior deterministic (`serialize` hoặc `reject`) |
| Provider failure | typed, retryable, observable |
| End-user answer | within configured complexity budget |

## 8. Definition of Done

Một agent feature chỉ hoàn thành khi có:

- tool schema và policy,
- source authority definition,
- threat model,
- golden cases,
- negative/abuse tests,
- latency/concurrency tests,
- metrics + alert,
- runbook,
- rollback plan,
- evidence report.
