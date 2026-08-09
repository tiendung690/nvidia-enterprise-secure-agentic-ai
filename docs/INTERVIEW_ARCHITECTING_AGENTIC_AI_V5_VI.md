# Interview Playbook — Architecting Agentic AI v5

## Câu mở đầu 90 giây

> Tôi không thiết kế agent như một chatbot có thêm tools. Tôi tách giải pháp thành identity/policy,
> admission-controlled agent runtime, secure context/tool plane, resilient model gateway và strict
> output postconditions. LLM chỉ reasoning và synthesis; authorization, tenant isolation, budgets,
> DLP, citation validation, retries và circuit breaker đều deterministic. Các test P01–P10 giúp tôi
> phát hiện lỗi thực tế: invalid citation vẫn HTTP 200, provider capacity cần retry tay, long-context
> 76 giây, concurrency=2 bị generic 504 và same-session lock timeout. v5 sửa bằng typed timeout
> taxonomy, session serialize/reject, global backpressure, bounded provider retry/circuit breaker,
> table-aware citation gate và dynamic answer budgets.

## Câu hỏi: Vì sao Context Store không phải source of truth?

Vector index tối ưu similarity, không đảm bảo ACL, freshness hoặc operational consistency. Document
registry/database mới là authority. Sau retrieval, Secure Context Broker phải authorization lại từng
candidate, áp lifecycle/version, masking và purpose filter trước khi gửi text vào LLM.

## Câu hỏi: Vì sao không chỉ tăng timeout từ 10 lên 120 giây?

Tăng timeout không giải quyết semantics. P09 timeout lúc chờ capacity, P10 timeout lúc chờ session,
khác với provider timeout hoặc execution deadline. Tôi tách chúng thành 409/429/503/504 để client
backoff đúng, SRE biết bottleneck và hệ thống không che giấu saturation.

## Câu hỏi: Retry Agentic AI khác retry HTTP bình thường thế nào?

Agent có mutable context và có thể đã gọi tools. Retry phải discard partial attempt state, tạo fresh
workflow context và chỉ an toàn khi tools read-only/idempotent. Khi có write tool, cần idempotency key,
HITL/approval, write audit và compensation; không thể retry mù.

## Câu hỏi: Prompt yêu cầu citation đã đủ chưa?

Không. Test cho thấy model vẫn tạo uncited summary/table. Tôi dùng deterministic postcondition:
extract claim units, validate current-turn IDs, conservative repair không invent citation, validate
lại và reject nếu vẫn fail. Prompt chỉ là preventive control; validator là detective/preventive gate.

## Câu hỏi: Làm sao tối ưu latency?

Đo breakdown trước. Retrieval thường <1 giây nhưng model inference 17–76 giây, nên tối ưu vector thêm
100 ms không có nhiều ý nghĩa. Tôi giảm same-tool calls, final sources, answer word budget; tăng cache
hit; quản lý concurrency/provider occupancy; và tách queue wait khỏi execution để capacity planning.

## Câu hỏi: Scale nhiều replica thế nào?

In-process cache/session chỉ phù hợp local. Production dùng Redis hoặc distributed state, external
policy engine, managed vector store metadata pre-filter, PostgreSQL RLS, OpenTelemetry và centralized
audit. Cache key vẫn phải giữ tenant/user/authz/purpose/policy/index/prompt/model dimensions.
