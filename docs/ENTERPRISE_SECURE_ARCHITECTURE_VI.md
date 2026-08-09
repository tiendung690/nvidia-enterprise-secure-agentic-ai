# Enterprise Secure Agentic AI Architecture — Technical Design

## 1. Mục tiêu

Nâng Agentic RAG thành nền tảng có thể chứng minh rằng:

1. LLM không trực tiếp sở hữu hay truy cập database.
2. Mọi enterprise fact đều đi qua identity, policy, authorization và provenance.
3. Dữ liệu trái quyền không được đưa vào model context.
4. Dữ liệu hiện hành lấy từ database typed tool; PDF dùng cho policy/knowledge đã version hóa.
5. Không đủ authorized evidence thì fail closed.

## 2. Security boundary

| Thành phần | Trách nhiệm deterministic |
|---|---|
| API/Auth | Verify JWT, issuer, audience, expiry, claims |
| Policy Engine | Tenant, role, department, purpose, clearance, classification |
| Secure Context Broker | Security trimming, masking, context minimization |
| Tool Gateway | Chỉ expose typed read-only capability |
| Database | RLS, parameterized query, record version |
| Agent Runtime | Tool budgets, timeout, session isolation |
| Grounding | Stable source IDs, citations, citation postcondition |
| Output Policy | DLP/redaction/block |
| Audit | Hash prompt/answer, record decision/source IDs |

LLM chỉ chọn tool và tổng hợp; nó không enforce security.

## 3. Request flow

1. FastAPI tạo `request_id`.
2. `JWTAuthenticator` verify token hoặc local dev identity.
3. `PolicyEngine.authorize_query()` kiểm tra purpose.
4. Cache/session key được tạo từ authorization hash.
5. Agent gọi retrieval hoặc typed database tool.
6. `SecureContextBroker.authorize_candidates()` kiểm tra từng candidate.
7. Chỉ authorized/masked evidence được serialize cho model.
8. Model sinh answer kèm `[Sxxxxxx]` hoặc `[Dxxxxxx]`.
9. Citation validator kiểm tra ID và coverage.
10. Output DLP redact/block.
11. Audit ghi hash và source IDs.

## 4. PDF ingestion

`CorpusIndexManager._prepare_documents()` bắt buộc tìm record trong `DocumentRegistry`.
Record chứa:

- `tenant_id`
- `classification`
- `allowed_roles`
- `allowed_departments`
- `allowed_purposes`
- `source_version`
- `policy_version`
- lifecycle và optional content hash

PDF thiếu record hoặc content hash sai sẽ không được publish. Vector store chỉ là derived index,
có thể xóa và rebuild từ source file + registry.

## 5. Retrieval security

Local LlamaIndex simple vector store chưa có native pre-filter mạnh như managed vector DB, nên reference
implementation retrieve candidate pool lớn rồi security-trim trong process trước khi model nhìn thấy text.
Production scale path là vector DB hỗ trợ metadata pre-filter, sau đó vẫn re-authorize ở application.

```text
metadata pre-filter -> semantic ranking -> application re-authorization -> masking -> LLM
```

## 6. Database source of truth

`get_order_status_tool` là bounded capability:

- Input chỉ có exact `order_id`.
- Tenant lấy từ verified identity, không lấy từ model/client body.
- Repository dùng parameterized query.
- PostgreSQL `operational_order` có RLS.
- Response là typed observation có record version và timestamp.
- Không expose schema explorer, raw SQL hoặc write capability.

## 7. Closed-book mode

`answer_mode=enterprise_factual` áp dụng postcondition:

```text
no authorized sources -> explicit abstention -> no cache admission
```

`general_advisory` cho phép kiến thức chung nhưng không được biến thành company fact.

## 8. Authorization-aware state

Session key và response-cache key chứa:

- tenant ID
- user ID
- authorization hash
- authorization version
- purpose
- answer mode
- policy version
- index version
- model/generation settings
- prompt version

Khi role/clearance/policy/index thay đổi, answer cũ không còn hit cache.

## 9. Data leakage controls

- Context masking trước inference.
- Indirect prompt-injection scan trên retrieved text.
- Output DLP sau generation.
- No raw prompt/answer trong audit.
- No credentials trong tool output.
- No arbitrary network/filesystem/SQL tools.

## 10. Scale path

- OIDC/JWKS production IdP.
- OPA/Cedar/central policy service.
- PostgreSQL/Unity Catalog/Databricks ABAC làm source enforcement.
- Qdrant/PGVector/OpenSearch hybrid retrieval với tenant pre-filter.
- Redis distributed cache/session và authz-version invalidation.
- Kafka/CDC/outbox cho document/ACL/data change.
- OpenTelemetry trace nối gateway, policy, retrieval, tool và LLM.
