# Fix: NVIDIA embedding input exceeds 512 tokens

## Symptom

```text
openai.BadRequestError: Error code: 400
Input length 1024 exceeds maximum allowed token size 512
```

## Root cause

The application used `RAG_CHUNK_SIZE=900`. LlamaIndex and NVIDIA do not necessarily count tokens with the same tokenizer, so a chunk considered below 900 by one tokenizer can exceed the NVIDIA embedding model's 512-token maximum. The application failed during FastAPI lifespan startup because auto-ingestion was executed before the server became ready. Docker then restarted the failed container repeatedly.

The warning about `llama-index-readers-file` is separate and was not the cause of the HTTP 400.

## Fix in v2.1

- Default `RAG_CHUNK_SIZE=320`.
- Default `RAG_CHUNK_OVERLAP=48`.
- Reserve a 192-token safety margin below the provider's 512-token maximum.
- Cap legacy configuration automatically during ingestion.
- Validate input length locally before calling NVIDIA.
- Install `llama-index-readers-file`.
- Stop infinite local restart loops after three failures.

## Clean rebuild

```bash
docker compose down -v
docker compose build --no-cache
docker compose up app
```

Successful startup should end with:

```text
Application startup complete.
Uvicorn running on http://0.0.0.0:8000
```

Then test:

```bash
curl http://localhost:8000/health/ready
python scripts/docker_host_smoke.py
```
