# Hướng dẫn build, host và test Docker trên local

## Điều kiện

- Docker Desktop hoặc Docker Engine + Compose plugin.
- Internet outbound tới `integrate.api.nvidia.com`, arXiv và Wikipedia.
- NVIDIA API key mới, chưa bị lộ.
- Không cần Ollama, GPU hoặc CUDA.

## Bước 1 — Tạo `.env`

```bash
cp .env.example .env
```

Sửa tối thiểu:

```dotenv
NVIDIA_API_KEY=nvapi-your-new-key
ADMIN_TOKEN=local-admin-token
AUTO_INGEST=true
ALLOW_DEV_IDENTITY_HEADERS=true
```

## Bước 2 — Build image

```bash
docker compose build --no-cache
```

## Bước 3 — Chạy app

```bash
docker compose up -d app
```

First boot có thể chậm vì app phải gọi NVIDIA embedding API cho toàn bộ chunks.

```bash
docker compose logs -f app
```

Chờ tới khi Uvicorn listen port 8000.

## Bước 4 — Health check

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

Expected:

```json
{
  "status": "ready",
  "llm_model": "nvidia/nemotron-3-ultra-550b-a55b",
  "embedding_model": "nvidia/nv-embedqa-e5-v5",
  "agent_mode": "function"
}
```

## Bước 5 — Chat test

```bash
curl -s http://localhost:8000/v1/chat \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: dung-local' \
  -d '{
    "query":"According to the RAG and Beyond survey, list and explain the four query levels.",
    "session_id":"rag-course-demo"
  }'
```

Hoặc:

```bash
python scripts/docker_host_smoke.py
```

## Bước 6 — Test multi-tool

```bash
curl -s http://localhost:8000/v1/chat \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: dung-local' \
  -d '{
    "query":"Define Self-RAG, then find up to two related arXiv papers and summarize the main difference.",
    "session_id":"multi-tool-demo"
  }'
```

## Bước 7 — Re-ingest

Khi thay data hoặc embedding configuration:

```bash
docker compose --profile tools run --rm ingest
docker compose restart app
```

## Bước 8 — Quan sát metrics

```bash
curl http://localhost:8000/metrics
```

Optional:

```bash
docker compose --profile observability up -d
```

- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

## Bước 9 — Dừng và xóa

Giữ index volume:

```bash
docker compose down
```

Xóa cả index volume:

```bash
docker compose down -v
```

## Troubleshooting

### `400 Bad Request: Input length 1024 exceeds maximum allowed token size 512`

Nguyên nhân: embedding model `nvidia/nv-embedqa-e5-v5` chỉ chấp nhận tối đa 512 model tokens, trong khi bản v2.0 dùng `RAG_CHUNK_SIZE=900`. Do tokenizer của LlamaIndex và NVIDIA khác nhau, chunk có thể bị NVIDIA tính thành khoảng 1024 tokens.

Bản v2.1 tự động cap legacy chunk settings về mức an toàn và mặc định dùng:

```dotenv
NVIDIA_EMBEDDING_MAX_INPUT_TOKENS=512
NVIDIA_EMBEDDING_TOKEN_SAFETY_MARGIN=192
RAG_CHUNK_SIZE=320
RAG_CHUNK_OVERLAP=48
```

Sau khi nâng cấp, xóa index/container cũ rồi build lại:

```bash
docker compose down -v
docker compose build --no-cache
docker compose up app
```

Dùng `docker compose up app` ở foreground trong lần chạy đầu để nhìn lỗi rõ ràng. Khi đã thấy `Application startup complete`, nhấn `Ctrl+C` và chạy nền:

```bash
docker compose up -d app
docker compose logs -f --tail=200 app
```

### Warning `llama-index-readers-file package not found`

Bản v2.1 đã thêm `llama-index-readers-file` vào dependencies. Đây không phải root cause của lỗi 400, nhưng thiếu package này có thể làm một số reader như PDF không khả dụng. Cần rebuild image sau khi nâng cấp.

### 401/403 từ NVIDIA

- Key sai, hết hạn hoặc đã revoke.
- Không có quyền truy cập model.
- Tạo key mới và cập nhật `.env`, sau đó restart.

### 429 rate limit

- Giảm corpus hoặc embedding batch size.
- Chờ quota reset.
- Không chạy nhiều ingestion job đồng thời.

### `/health/ready` trả 503

- Index chưa được tạo.
- Chạy `docker compose --profile tools run --rm ingest`.
- Kiểm tra volume `rag_storage` và log lỗi embedding API.

### Đổi embedding model nhưng kết quả sai

- Xóa/recreate index. Không reuse vectors tạo bởi model cũ.

### Container không ghi được storage

- Đảm bảo Docker volume được mount `/app/storage`.
- Không bind-mount thư mục host có permission không phù hợp.

## Lỗi NVIDIA `ResourceExhausted (33/32)`

Nếu health endpoints đều `ready` nhưng `/v1/chat` trả `Worker local total request limit reached (33/32)`, chạy:

```bash
docker compose exec app python scripts/nvidia_capacity_probe.py
```

Xem hướng dẫn chi tiết tại `docs/TROUBLESHOOTING_NVIDIA_CAPACITY.md`. Bản 2.2 dùng reasoning budget nhỏ hơn, giới hạn một request agent đồng thời và mặc định retrieval-only RAG để giảm số lần gọi hosted Nemotron.
