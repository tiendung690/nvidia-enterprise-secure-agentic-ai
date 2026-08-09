# Security Threat Model

## Tài sản cần bảo vệ

- Nội dung PDF nội bộ.
- Operational records.
- Identity/tenant/role/clearance claims.
- NVIDIA API key và database credential.
- Vector index, cache, session state và audit trail.

## Threats và controls

| Threat | Control trong repo |
|---|---|
| Cross-tenant retrieval | Tenant ABAC + candidate re-authorization + authz-scoped cache |
| User giả mạo role | Production JWT verification; role không lấy từ request body |
| Prompt injection trực tiếp | Prompt guard block/audit |
| Injection trong PDF | Treat evidence as data + indirect scan + no side-effect tools |
| Model tự viết SQL | Không có SQL tool; chỉ typed capability |
| Stale access sau role change | Authorization-version trong session/cache key |
| Stale document | Source version, policy version, index fingerprint |
| Sensitive data trong context | Pseudonymize/redact trước LLM |
| Sensitive data trong output | Output DLP audit/redact/block |
| Cache leak | Tenant/user/authz/purpose/policy/index scoped key |
| Audit leak | Chỉ hash prompt/answer; ghi source/decision IDs |
| Missing ACL metadata | Ingestion fail closed |
| Hosted model boundary | Context minimization; restricted data cần private NIM/VPC |

## Hard security invariants

1. Unauthorized source count trong response phải bằng 0.
2. Cross-tenant database lookup không trả record.
3. Enterprise factual answer không có source phải abstain.
4. Unknown citation ID không được coi là valid.
5. Production không cho phép development identity headers.
6. Document thiếu registry metadata không thể ingest.

## Known boundaries

- Local vector store chưa có server-side metadata pre-filter.
- JSONL audit là local reference, chưa immutable/WORM centralized sink.
- In-process cache/session chưa shared giữa replicas.
- Hosted NVIDIA endpoint vẫn là external processing boundary.
