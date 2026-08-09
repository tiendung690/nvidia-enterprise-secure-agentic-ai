# Production Readiness & SRE v5

## 1. SLI/SLO

| SLI | SLO | Alert |
|---|---:|---|
| API availability | >= 99.9% | 5m error rate > 2% |
| Exact cache p95 | < 500 ms | p95 > 1 s |
| Fresh simple p95 | < 60 s | p95 > 75 s |
| Multi-corpus p95 | < 75 s | p95 > 90 s |
| Capacity rejection | < 1% steady state | > 5% for 10m |
| Provider transient recovery | >= 95% | recovery < 90% |
| Citation-valid returned answer | 100% strict mode | any invalid returned |
| Security leakage | 0 | immediate incident |

## 2. Metrics added in v5

- `agentic_ai_latency_stage_seconds{stage=...}`
- `agentic_ai_admission_events_total{scope,result}`
- `agentic_ai_inflight_requests`
- `agentic_ai_provider_attempts_total{provider,result}`
- `agentic_ai_provider_backoff_seconds`
- `agentic_ai_provider_circuit_state`
- `agentic_ai_citation_repair_total{result}`

Existing policy, tool, retrieval, DLP, audit and cache metrics remain.

## 3. Dashboard panels

1. Request volume by outcome.
2. Fresh/cache latency p50/p95/p99.
3. Session wait vs capacity wait vs provider latency.
4. Inflight requests and queue rejection.
5. Provider attempts/retries/circuit state.
6. Tool latency and same-tool budget failures.
7. Citation validation and repair rate.
8. Denied retrieval candidates and DLP signals.

## 4. Runbooks

### NVIDIA capacity exhausted

1. Kiểm tra provider attempt/error metrics.
2. Xác nhận circuit state.
3. Giảm fresh concurrency hoặc reasoning/output budget.
4. Tăng cache hit bằng stable query normalization.
5. Không tăng retry vô hạn; retry storm làm provider tệ hơn.

### CAPACITY_WAIT_TIMEOUT tăng

1. Kiểm tra inflight gauge và provider latency.
2. Xác định answer verbosity/context size.
3. Tăng replicas/distributed queue, không chỉ tăng local semaphore.
4. Giữ 429 + Retry-After để client backoff.

### SESSION_BUSY/WAIT tăng

1. Kiểm tra frontend có gửi nhiều turn cùng session không.
2. Chọn `reject` cho chat UX hoặc `serialize` cho ordered workflow.
3. Không tăng lock timeout mà bỏ qua cancellation/client UX.

### Citation repair tăng

1. Kiểm tra prompt version regression.
2. Xem claim_count, coverage và removed_claim_count.
3. Nếu repair loại nhiều nội dung, sửa retrieval/prompt thay vì hạ threshold.

## 5. Deployment

- Rolling/canary theo prompt version và model config.
- Cache key có prompt/model/policy/index version nên rollout không trả stale answer.
- Ingestion chạy như job riêng; không rebuild index trong app startup.
- Production secrets từ secret manager/workload identity.
- OpenTelemetry export cho trace liên service.
- Redis/managed cache và distributed session coordination khi replicas > 1.

## 6. Capacity model

Fresh throughput bị giới hạn chủ yếu bởi hosted generation, không phải vector retrieval. Test đã cho
thấy retrieval thường dưới 1 giây trong khi end-to-end 17–76 giây. Vì vậy capacity planning phải dựa
trên provider occupancy:

```text
required concurrent slots ~= arrival_rate * average_fresh_latency
```

Sau đó áp dụng cache ratio, rejection budget và provider quota để chọn replicas/semaphore.

## 7. Chaos tests

- Provider 503 trong attempt 1, success attempt 2.
- Provider timeout đến hết retry budget.
- Circuit open/half-open recovery.
- Vector store unavailable.
- Database read timeout.
- Audit sink unavailable.
- Authorization version change trong lúc cache đang tồn tại.
- Pod restart khi same-session request đang chờ.
