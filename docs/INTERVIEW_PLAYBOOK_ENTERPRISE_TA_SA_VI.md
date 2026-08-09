# Interview Playbook — Strong SSE/TL lên TA/SA

## Câu mở đầu 60 giây

"Tôi nâng Agentic RAG demo thành controlled execution platform. LLM không giữ credential và không
tự authorize. Verified identity được map thành tenant, role, department và clearance. Policy engine
quyết định purpose và resource access. PDF index chỉ là derived context; document registry hoặc
PostgreSQL là source of truth cho ACL/version. Retrieval candidates được re-authorize và masking
trước khi gửi Nemotron. Operational data đi qua typed read-only tools với parameterized query và
RLS, không có text-to-SQL tự do. Enterprise factual mode fail closed khi thiếu evidence, mọi claim
có citation, output đi qua DLP, cache key chứa authorization/policy/index version và audit chỉ lưu
hash cùng decision/source IDs."

## Bằng chứng chỉ vào code

| Claim | File/hàm |
|---|---|
| JWT/OIDC verification | `identity/jwt.py::JWTAuthenticator` |
| Authorization hash | `identity/models.py::authorization_hash` |
| RBAC/ABAC | `policy/engine.py::authorize_document` |
| Secure context | `context/broker.py::authorize_candidates` |
| Fail-closed ingestion | `rag/index_manager.py::_prepare_documents` |
| Security-trim retrieval | `rag/index_manager.py::retrieve_evidence` |
| Typed DB capability | `tools/secure_operational.py::get_order_status` |
| RLS | `ops/sql/001_enterprise_schema.sql` |
| Closed-book postcondition | `agents/service.py::chat` |
| Authz-aware cache | `agents/service.py::_cache_key` |
| Output DLP | `security/output_policy.py::validate` |
| Audit without raw content | `agents/service.py::_record_audit` |

## Trade-offs cần nói rõ

- Security trimming có thể giảm raw recall; metric đúng là Authorized Recall@K.
- Context masking bảo vệ data nhưng có thể giảm entity resolution; pseudonym ổn định giảm ảnh hưởng.
- Fail closed làm coverage giảm nhưng factual precision và security correctness tăng.
- Local index phù hợp reference; multi-replica cần managed vector store và shared cache.
- Public hosted model không phù hợp restricted data nếu không có enterprise agreement/private NIM.

## Câu hỏi khó

### Vì sao không cho LLM tự viết SQL?

Vì schema guessing, injection, privilege escalation, query cost và non-deterministic authorization.
Typed tool tạo bounded capability, input schema rõ, tenant lấy từ verified identity, query được test.

### Vì sao kiểm tra ACL cả ingestion và retrieval?

Ingestion ngăn dữ liệu không quản trị vào index; retrieval xử lý role/purpose/lifecycle hiện tại.
ACL thay đổi sau ingestion nên authorization phải được evaluate ở request time.

### Làm sao chứng minh cache không leak?

Cache key chứa tenant, user, authorization hash/version, purpose, answer mode, policy/index/prompt
version. Unit test đổi `authorization_version` và xác nhận cache miss.

### Tại sao database và PDF đều cần?

PDF là source cho policy/knowledge versioned; database là source cho operational state mới nhất.
Agent reasoning kết hợp rule `[S...]` và current fact `[D...]` nhưng không thay thế source authority.
