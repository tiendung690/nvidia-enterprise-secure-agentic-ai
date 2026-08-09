# Fix sai retrieval và latency cao

## Root cause

Một vector index chung chứa cả course lessons và research papers làm các chunk paper có mật độ từ khóa RAG cao chiếm top-k. Agent sau đó lấy taxonomy query levels để suy diễn thay cho định nghĩa Basic RAG/Agentic RAG. `QueryEngineTool` còn tạo thêm một LLM generation bên trong mỗi tool call, khiến latency tăng mạnh.

## Fix trong v2.3

1. Tách `data/course` và `data/papers` thành hai corpus/index độc lập.
2. Tạo hai tool: `agentic_rag_course_tool` và `research_paper_rag_tool`.
3. Chỉ retrieval evidence; không gọi LLM bên trong RAG tool.
4. Course top-k = 8; papers top-k = 5.
5. Prompt cấm ánh xạ query-complexity levels thành Basic/Agentic RAG nếu evidence không nói rõ.
6. Manifest SHA-256 tự phát hiện index stale khi file/chunk/model thay đổi.
7. Giảm reasoning budget mặc định xuống 1024 và max tokens 3072.
8. API deduplicate `tools` và thêm `tool_call_count`.

## Chạy lại sạch

```bash
docker compose down -v
docker compose build --no-cache
docker compose --profile tools run --rm ingest --recreate
docker compose up -d app
docker compose logs -f --tail=200 app
```

Test bằng session mới:

```json
{
  "query": "According to the indexed course documents, compare Basic RAG and Agentic RAG. Explain workflow, components, reasoning, tool usage, strengths, limitations, and suitable use cases.",
  "session_id": "course-basic-agentic-v23-001"
}
```

Kỳ vọng `tools` chỉ chứa `agentic_rag_course_tool`, thường một lần gọi; `research_paper_rag_tool` không được dùng.
