# Test Results, Issues & Remediation v5

## 1. Kết quả quan sát trước v5

| Case | Observed result | Đánh giá |
|---|---|---|
| P01 fresh simple | ~28.8 s, one course tool, citation 1.0 | Pass |
| P02 cache | ~6–15 ms, zero tool call | Strong pass |
| P03 repeated fresh | ~29–33 s, stable routing/citations | Pass |
| P04 multi-corpus | lần đầu 503 capacity, retry tay thành công ~42 s | Quality pass, resilience fail |
| P05 long context | ~75.9 s, same tool 2 lần, 15 sources | Performance fail |
| P06 insufficient | correct refusal ~6.8 s | Security pass, latency optimize |
| P07 injection | blocked ~6–10 ms, zero tool call | Strong pass |
| P08 session isolation | no cross-session cache hit | Pass |
| P08 citation | coverage 0.50, invalid answer vẫn trả | Strict grounding fail |
| P09 concurrency=2 | 1 success, 1 generic 504 at 10 s | Availability fail |
| P10 same session | brain/memory success, planner generic 504 | Session UX/error semantics fail |

## 2. Remediation implemented

| Issue | v5 control |
|---|---|
| Generic timeout | Typed capacity/session/provider/execution exceptions |
| Max inflight 1 | Default 2 with explicit queue timeout |
| Same-session race | Configurable serialize/reject policy |
| Provider capacity | Runtime retries + exponential backoff + jitter + circuit breaker |
| Citation table false negative | Table-aware claim parser |
| Invalid answer returned | Strict validation + conservative repair + reject |
| Misleading citation 1.0 for blocked response | `applicable=false`, `coverage=null` |
| Long answer | Dynamic response contract by query complexity |
| Same-tool duplication | Default same-tool limit 1 |
| Too many course chunks | Course top-k reduced 8 -> 6; simple source budget 5 |
| Runtime/PDF facts mixed | Prompt contract separates evidence domains |
| ReAct/Plan contradictions | Prompt contract treats them as alternative branches |
| Missing operational telemetry | Latency breakdown + provider trace + admission metrics |

## 3. Offline verification v5

- Unit tests: 88 passed, 2 live tests skipped.
- Configured core coverage: 91.86%.
- Static AST/line-length/secret validation passed.
- Live NVIDIA performance suite is included but not executed during offline packaging because it
  requires the user's rotated NVIDIA key and running indexes.

## 4. Remaining production boundaries

- In-process cache/session are not multi-replica state.
- No streaming cancellation endpoint yet.
- No managed vector metadata pre-filter; authorization occurs after candidate retrieval.
- No write/action agent; HITL/idempotency framework must be added before side effects.
- Live load, soak, chaos and red-team tests remain deployment responsibilities.
