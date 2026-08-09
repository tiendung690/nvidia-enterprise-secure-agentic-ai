# Technical Note — NVIDIA Agentic RAG dùng LlamaIndex và Hosted API

## 1. Mục tiêu

Repo chuyển toàn bộ phần inference ra NVIDIA-hosted API:

- Nemotron thực hiện planning, tool calling và synthesis.
- NVIDIA embedding API tạo vector khi ingest và khi query.
- Không dùng Ollama, không cần cài model local, không cần GPU local.
- LlamaIndex vẫn chịu trách nhiệm document loading, chunking, indexing, retrieval, query engine và agent/tool abstraction như khóa học.

## 2. Mapping từ code khóa học

| Khóa học | Repo mới |
|---|---|
| `Groq(...)` | LlamaIndex `OpenAILike(...)` trỏ tới NVIDIA API |
| `OllamaEmbedding(...)` | `NvidiaNIMEmbedding`, gọi `/v1/embeddings` |
| `VectorStoreIndex.from_documents` | Giữ nguyên, truyền embedding adapter NVIDIA |
| `QueryEngineTool` | Giữ nguyên |
| `FunctionTool` | Giữ nguyên, bổ sung schema/docstring và xử lý lỗi |
| `ReActAgent` | Có thể bật bằng `AGENT_MODE=react` |
| Không persistence | `StorageContext.persist` và `load_index_from_storage` |
| `eval()` trong assessment | AST allow-list calculator |
| `verbose=True`/thought logs | Chỉ log event tool có cấu trúc |

## 3. NVIDIA LLM adapter

`OpenAILike` được dùng vì NVIDIA cung cấp OpenAI-compatible endpoint nhưng model name không thuộc model registry của OpenAI. Cấu hình quan trọng:

```python
OpenAILike(
    model="nvidia/nemotron-3-ultra-550b-a55b",
    api_base="https://integrate.api.nvidia.com/v1",
    api_key=api_key,
    is_chat_model=True,
    is_function_calling_model=True,
    additional_kwargs={
        "extra_body": {
            "chat_template_kwargs": {
                "enable_thinking": True,
                "force_nonempty_content": True,
            },
            "reasoning_budget": 16384,
        }
    },
)
```

`force_nonempty_content` được giữ khi dùng tools để NVIDIA runtime có thể parse reasoning và tool calls ổn định.

## 4. NVIDIA embedding adapter

LlamaIndex cần hai hành vi embedding khác nhau:

- Query: `input_type="query"`
- Document chunk: `input_type="passage"`

`NvidiaNIMEmbedding` kế thừa `BaseEmbedding` và sử dụng OpenAI client:

```python
client.embeddings.create(
    model="nvidia/nv-embedqa-e5-v5",
    input=texts,
    extra_body={"input_type": "passage"},
)
```

Không được đổi embedding model sau khi đã ingest mà không rebuild index. Vector của document và query phải nằm trong cùng embedding space.

## 5. LlamaIndex persisted RAG

Ingestion:

```text
Data directory
  -> SimpleDirectoryReader
  -> SentenceSplitter
  -> NVIDIA embedding API
  -> VectorStoreIndex
  -> StorageContext.persist
```

Online query:

```text
User query
  -> NVIDIA query embedding
  -> similarity retrieval
  -> top-k chunks
  -> QueryEngine synthesis bằng Nemotron
  -> observation trả về Agent
```

Cấu hình này bám sát khóa học nên có hai lớp generation khi agent gọi RAG tool:

1. QueryEngine tổng hợp answer từ chunks.
2. Agent tổng hợp final answer từ observation.

Đây là trade-off có chủ đích để dễ học và tương thích course. Khi tối ưu chi phí/latency, có thể thay QueryEngineTool bằng retrieval-only FunctionTool.

## 6. FunctionAgent và ReActAgent

### FunctionAgent — default

- Dùng native structured tool calls.
- Input tool được kiểm tra theo function schema.
- Phù hợp với Nemotron vì model hỗ trợ tool calling.
- Giảm lỗi parse chuỗi `Thought/Action/Action Input`.

### ReActAgent — course mode

- Mô phỏng đúng reasoning loop của khóa học.
- Hữu ích để học và quan sát agentic flow.
- Có rủi ro parse, loop và token overhead cao hơn.

## 7. Security

- Không hard-code API key.
- Key bị paste vào chat/source phải rotate ngay.
- Không trả hoặc log hidden reasoning.
- Tool output và retrieved text được coi là untrusted data.
- Prompt guard chỉ là lớp tín hiệu, không phải security boundary.
- Chưa đăng ký write/destructive tools.
- Safe calculator không dùng `eval()`.
- Ingestion API cần admin token.
- Production phải thay dev identity bằng OIDC/JWT.

## 8. Reliability và cost

- Persist index để không gọi embedding API ở mọi startup.
- `AUTO_INGEST=true` chỉ phù hợp local/demo; production nên chạy ingestion job riêng.
- Request có overall timeout.
- NVIDIA client có timeout và bounded retries.
- Metrics gồm request status, latency và tool calls.
- `NVIDIA_MAX_TOKENS=16384` và reasoning budget 16384 là cấu hình lớn; cần giảm theo SLO và cost evaluation khi chạy thật.

## 9. Docker topology

```text
Host :8000
   |
Docker app (FastAPI + LlamaIndex)
   |-- HTTPS --> NVIDIA chat completions
   |-- HTTPS --> NVIDIA embeddings
   |-- HTTPS --> arXiv / Wikipedia when tools are selected
   `-- volume --> persisted LlamaIndex storage
```

Container không cần NVIDIA runtime và không mount Ollama socket.

## 10. Nâng lên TA/SA Plus

Các extension tiếp theo:

1. Durable workflow/state thay vì in-memory Context.
2. Managed vector DB cho multi-replica và large corpus.
3. OIDC/JWT + tenant ACL filter trước retrieval.
4. Policy engine cho tool authorization và HITL.
5. OpenTelemetry spans cho router, tool, retrieval, reranking và generation.
6. Golden dataset đo routing, tool arguments, faithfulness, goal completion, latency và cost.
7. Prompt/tool versioning, canary release và rollback.
