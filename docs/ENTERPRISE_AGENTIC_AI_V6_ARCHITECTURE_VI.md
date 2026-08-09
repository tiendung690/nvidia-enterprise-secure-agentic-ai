# Enterprise Agentic AI v6 — kiến trúc TA/SA production-oriented

## 1. Mục tiêu

v6 chuyển repository từ một secure Agentic RAG có vector retrieval và session context thành
một nền tảng gồm hai đường dữ liệu tách biệt:

- **Governed read path:** query transformation, hybrid retrieval, RRF, rerank, quality gate,
  authorization, bounded prompt và strict citation.
- **Governed write path:** explicit promotion, typed memory, provenance, scope, SCD2
  supersession, approval, forgetting và transactional outbox.

![Enterprise Agentic AI v6](diagrams/enterprise-agentic-ai-v6.svg)

Nguyên tắc chính: model không phải source of truth, không tự quyết quyền truy cập, không tự
kích hoạt memory, không được dùng memory thay cho evidence hiện tại, và không được điều khiển
trạng thái `active` của durable record.

## 2. Component map vào code

| Component | Code | Trách nhiệm |
|---|---|---|
| Guarded query transformation | `query/transformation.py` | Tạo tối đa N query có thể audit, giữ error code/version/named identifier, tránh LLM drift |
| Hybrid retrieval | `retrieval/hybrid.py`, `rag/index_manager.py` | Vector + BM25, RRF, deterministic rerank, quality assessment, LIKE fallback |
| Secure context broker | `context/broker.py` | Enforce tenant, role, department, purpose, clearance trước khi text vào prompt |
| Bounded conversation | `conversation/bounded.py` | Chỉ giữ recent-turn projection; raw history nằm trong trace, không làm prompt tăng vô hạn |
| Exact memory path | `memory/service.py` | Enumerate toàn bộ active policy/preference theo scope, không top-k/similarity |
| Semantic memory path | `memory/service.py` | Search active fact/episode theo scope và query |
| Promotion gate | `memory/promotion.py` | Server tính scope/status, kiểm tra provenance/confidence/source/task completion |
| Temporal memory repository | `memory/repository.py` | Dedup, SCD2 supersession, provisional/active/deleted, outbox |
| PostgreSQL schema | `ops/sql/004_governed_memory_and_trace.sql` | Typed memory, FTS, RLS, trace, outbox và indexes |
| Replay trace | `tracing/*` | Hash query/answer, event lifecycle, source/tool/memory/retrieval trace, tenant-scoped lookup |
| Runtime integration | `agents/service.py` | Đọc memory, assemble bounded prompt, collect retrieval trace, cache-versioning, complete/fail trace |
| API governance | `api.py` | Promote/approve/forget memory, validate source run ownership, admin trace lookup |

## 3. Read path

### 3.1 Identity, purpose và query authorization

`IdentityContext` được tạo từ JWT trong production. `PolicyEngine.authorize_query` chạy trước
retrieval và inference. Cache key chứa authorization hash, purpose, answer mode, policy version,
index version và memory version để ngăn reuse answer xuyên quyền hoặc khi knowledge đã đổi.

### 3.2 Query transformation

`GuardedMultiQueryTransformer` là deterministic thay vì nhờ LLM tự rewrite. Thiết kế này:

- giữ exact identifier như `ERR-123`, version và method name;
- giới hạn `MULTI_QUERY_MAX_VARIANTS`;
- không tạo hypothetical document mặc định;
- cho phép trace chính xác query nào đã chạy.

HyDE không bị cấm, nhưng phải là adapter provider-backed riêng, có budget/eval và không được
âm thầm biến suy đoán thành evidence.

### 3.3 Hybrid retrieval

Mỗi query variant chạy hai nhánh:

1. LlamaIndex vector retriever lấy candidate semantic;
2. BM25 local index lấy candidate lexical, có authorization predicate trước ranking.

Các rank được merge bằng Reciprocal Rank Fusion thay vì cộng trực tiếp BM25 score với cosine.
RRF output được normalize và đưa qua `DeterministicReranker`, sau đó `RetrievalQualityEvaluator`
trả tier `high|standard|low|none`.

Nếu candidate rỗng hoặc chất lượng thấp, fallback bị giới hạn sang LIKE/term-overlap. Mọi fallback
được đánh dấu `degraded=true`, không giả vờ fidelity không đổi.

### 3.4 Security boundary của local vector index

Local LlamaIndex vector store vẫn lấy ANN candidate trước rồi Secure Context Broker mới loại dữ
liệu không được phép. Text chưa vào LLM trước authorization, nhưng ANN search chưa có metadata
prefilter vật lý. Đây là giới hạn đã biết.

Production nhiều tenant phải thay vector adapter bằng pgvector/OpenSearch/Pinecone/managed store
có metadata prefilter hoặc partition/index riêng theo security boundary. BM25 local path trong v6
đã filter quyền trước ranking để minh họa đúng contract.

### 3.5 Bounded prompt

Mỗi request ở mode `bounded` dùng workflow `Context` mới. Prompt được dựng lại từ:

1. current query;
2. tối đa N recent turns;
3. exact policy/preference;
4. semantic fact/episode;
5. response budget contract.

Memory prompt có câu lệnh bắt buộc: memory chỉ là hint/continuity, không phải current-turn
evidence cho enterprise factual claim. Citation postcondition vẫn chỉ chấp nhận source ID của
current tool call.

## 4. Write path

### 4.1 Không auto-promote arbitrary knowledge từ answer

Chat response không tự ghi fact, episode, personality hay policy. Client/trusted workflow dùng
`POST /v1/memory/promote` cho candidate có provenance. Riêng request có durable marker rõ ràng
(`from now on`, `từ giờ`, ...) được deterministic extractor nhận trên allow-list format/language/
detail; câu có injection signal bị bỏ toàn bộ. Candidate vẫn đi qua promotion gate và audit.

### 4.2 Source-run ownership

Candidate có `source_run_id` phải trỏ đến trace thuộc cùng tenant và user. API reject source run
không tồn tại hoặc không thuộc caller. Fact còn cần confidence threshold và provenance.

### 4.3 Typed memory

- **Policy:** exact enumeration, tenant-scoped API publication chỉ dành cho `memory-admin` và
  `admin_configured`; global policy chỉ được deploy bằng migration/configuration.
- **Preference:** exact enumeration theo user; chỉ `user_stated` hoặc `admin_configured`.
- **Fact:** ranked discovery; PostgreSQL adapter dùng scope-filtered FTS, còn vector-semantic adapter là production extension; fact vẫn cần source run, confidence và scope checks.
- **Episodic:** chỉ task completed và có source run.
- **Trace:** append-only trace service, không đi qua promotion gate.

### 4.4 Provisional và approval

`model_inferred` fact được ghi `provisional`, không xuất hiện trong read path. `memory-admin` phải
approve qua `POST /v1/memory/{id}/approve` mới thành `active`.

### 4.5 Dedup và SCD2 supersession

Repository dùng content hash cộng memory type/scope/tenant/user để idempotent. Với fact hoặc
preference cùng `(subject, predicate)` nhưng giá trị mới:

- row cũ chuyển `superseded`;
- `effective_until=now()`;
- `superseded_by=<new_id>`;
- row mới active trong cùng transaction;
- outbox phát `memory.promoted`/`memory.superseded`.

### 4.6 Forgetting

User có thể xóa user-scoped memory của chính mình. `memory-admin` có thể xóa tenant memory.
User/tenant record được physical delete trong transaction và phát `memory.erased`; foreign key `superseded_by` dùng `ON DELETE SET NULL`. Global memory không xóa qua API. Cache bị clear sau mutation.

## 5. Replay và observability

Mỗi accepted chat run tạo `run_id` và trace gồm:

- query hash, không lưu raw query trong trace model;
- tenant/user/session/request/purpose;
- prompt/index/memory version;
- source IDs và tool names;
- retrieval strategy, số lượng và hash query variants, mode, quality, fallback;
- memory exact/semantic counts;
- outcome, latency, answer hash và error code.

`GET /v1/traces/{run_id}` cần admin token và identity, đồng thời chỉ đọc trace trong tenant hiện
tại. PostgreSQL RLS tiếp tục enforce tenant boundary.

## 6. Database design

`agent_memory` là canonical truth. `search_vector` là generated projection có thể rebuild.
`agent_outbox` bảo đảm event chỉ tồn tại khi transaction memory commit; reference dispatcher publish at-least-once và consumer deduplicate theo `event_id`. `agent_run_trace` là flight recorder. RLS dùng `app.tenant_id`, `app.user_id`, `app.is_memory_admin`.

Production nên chạy migration bằng role migration riêng, không cho application role DDL hoặc
BYPASSRLS.

## 7. Corrective và agentic budget

Corrective flow không retry vô hạn. Repository giữ các budget hiện có:

- maximum tool calls;
- maximum same-tool calls;
- provider retry attempts/backoff;
- request deadline;
- global concurrency slot;
- session serialization/reject;
- maximum query variants;
- bounded fallback chain;
- bounded sources và answer words.

Agent chỉ quyết tool flow bên trong các deterministic boundary này.

## 8. Production deployment profile

Production bắt buộc qua `Settings` validator:

- `AUTH_MODE=jwt`;
- `ALLOW_DEV_IDENTITY_HEADERS=false`;
- `AUTO_INGEST=false`;
- `MEMORY_BACKEND=postgres`;
- `TRACE_BACKEND=postgres`;
- JWT key/JWKS được cấu hình.

Ngoài code, rollout thật còn cần managed secret/workload identity, managed vector prefilter,
OpenTelemetry/SIEM, DB backup/PITR, load/soak/chaos/red-team, canary/rollback và runbook.

## 9. TA/SA interview narrative

Câu chuyện kiến trúc không phải “thêm vector DB”. v6 cho thấy cách compose các layer orthogonal:

> Query transformation tăng recall; hybrid retrieval cân bằng exact và semantic; rerank phân bổ
> context budget; corrective gate quản lý fidelity; orchestration bị giới hạn bằng budget. RAG là
> read path. Durable memory là governed write path, nơi promotion gate, provenance, SCD2, RLS,
> outbox, replay và forgetting quyết định production trust.


## 10. Pattern không bật mặc định

Hierarchical RAG chỉ nên bật khi document hierarchy là canonical và có fallback nếu coarse branch
sai. Graph RAG chỉ nên bật khi có entity-resolution, relationship provenance và incremental ETL.
Repository hiện chủ động không giả lập hai write path đó trên corpus course/paper. Extension point
nằm ở retrieval tool; baseline đã compose đúng các layer cần thiết cho use case hiện tại.

## 11. Memory consistency semantics

Mỗi promotion là transaction độc lập và idempotent bằng content hash + logical slot lock. Một
request chứa nhiều preference có thể được retry an toàn nếu hạ tầng lỗi giữa batch; record đã ghi
sẽ deduplicate, record còn thiếu được hoàn tất. API trả 503 thay vì tuyên bố continuity đã lưu khi
write path không hoàn thành. Exact policy/preference không bao giờ top-k hoặc silently truncate.
