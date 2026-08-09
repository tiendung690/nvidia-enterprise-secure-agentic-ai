# Docker + performance + privacy/security test guide for v6

## 1. Local functional build (real NVIDIA hosted API)

The base compose file forces `AUTO_INGEST=false` inside the containers. Therefore ingest **before** starting `app` on a clean volume.

```bash
cp .env.example .env
# Edit at least NVIDIA_API_KEY, ADMIN_TOKEN, MASKING_SALT.
# Keep AUTH_MODE=dev and ALLOW_DEV_IDENTITY_HEADERS=true only for local testing.

docker compose build --no-cache
docker compose up -d postgres
docker compose --profile tools run --rm ingest
docker compose up -d app
docker compose ps
docker compose logs --tail=200 app
curl -fsS http://localhost:8000/health/live
curl -fsS http://localhost:8000/health/ready
```

Do not use the production overlay until real RS256/JWKS and non-development DB credentials are configured.

## 2. Quality and built-in performance gates

```bash
python scripts/docker_host_smoke.py
python scripts/evaluate_api.py --base-url http://localhost:8000
python scripts/performance_suite.py --base-url http://localhost:8000 --concurrency 2
python scripts/load_sweep.py --base-url http://localhost:8000 --requests 6 --concurrency 2 4 8
```

Interpretation:
- `c1/c2` are the main steady-state baseline because default `AGENT_MAX_CONCURRENT_REQUESTS=2`.
- `c4/c8` are saturation tests. Controlled `409/429/503/504` is better than crashes, memory growth, or unbounded latency.
- cache p95 should be far below fresh p95.
- same-session tests should serialize rather than race.

## 3. End-to-end privacy/security suite

Use only synthetic canaries.

```bash
python scripts/privacy_security_suite.py \
  --base-url http://localhost:8000 \
  --admin-token "$ADMIN_TOKEN"
```

The suite covers:
1. direct prompt injection blocked before provider/tool execution;
2. output DLP does not return a synthetic email canary verbatim;
3. authorized tenant-A order access;
4. tenant-B cannot read tenant-A order/source/PII;
5. operational customer reference is masked;
6. RBAC denies order access;
7. user-scoped memory cannot bleed to another user;
8. instruction-bearing memory candidate is rejected;
9. trace IDOR across tenants returns 404;
10. response cache is tenant scoped.

## 4. Prove exactly what leaves the application boundary

Black-box prompts cannot prove that a hosted provider never retains data. Instead, replace NVIDIA temporarily with a local OpenAI-compatible capture endpoint and inspect request bodies.

### 4.1 Prepare a synthetic confidential document

```bash
CANARY=$(python scripts/prepare_privacy_canary.py)
echo "$CANARY"
mkdir -p artifacts/provider-capture
rm -f artifacts/provider-capture/events.jsonl
```

### 4.2 Start provider capture and ingest against it

The capture overlay overrides `NVIDIA_API_KEY` with a synthetic value, so the real key is not sent to the capture service.

```bash
docker compose -f docker-compose.yml -f docker-compose.capture.yml down -v
docker compose -f docker-compose.yml -f docker-compose.capture.yml build
docker compose -f docker-compose.yml -f docker-compose.capture.yml up -d postgres provider-capture
docker compose -f docker-compose.yml -f docker-compose.capture.yml --profile tools run --rm ingest

grep -F "$CANARY" artifacts/provider-capture/events.jsonl
```

If the canary appears under `/v1/embeddings`, that proves raw document chunk text crosses the embedding-provider boundary during ingestion.

### 4.3 Prove query text crosses the embedding boundary

```bash
docker compose -f docker-compose.yml -f docker-compose.capture.yml up -d app
docker compose -f docker-compose.yml -f docker-compose.capture.yml exec app \
  python /app/scripts/provider_boundary_probe.py \
  --capture-file /capture/events.jsonl
```

If running the probe inside `app`, mount the capture directory into `app` as read-only or run the script on the host with `NVIDIA_BASE_URL=http://localhost:18081/v1`.

Simpler host command:

```bash
NVIDIA_API_KEY=fake-local-key \
NVIDIA_BASE_URL=http://localhost:18081/v1 \
python scripts/provider_boundary_probe.py
```

### 4.4 Prove the current user prompt crosses the chat-provider boundary

```bash
USER_CANARY="USER_PROMPT_CANARY_$(date +%s)"
curl -s http://localhost:8000/v1/chat \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: privacy-probe' \
  -H 'X-Tenant-Id: public' \
  -d "{\"query\":\"Explain this synthetic token: ${USER_CANARY}\",\"answer_mode\":\"general_advisory\",\"session_id\":\"provider-boundary\"}"

grep -F "$USER_CANARY" artifacts/provider-capture/events.jsonl
```

If it appears in a `/v1/chat/completions` event, the raw current user query is sent to the hosted LLM in the real configuration.

### 4.5 Cleanup

```bash
python scripts/prepare_privacy_canary.py --cleanup
docker compose -f docker-compose.yml -f docker-compose.capture.yml down -v
```

## 5. Important privacy conclusion for the current v6 implementation

- Retrieved document/operational context is authorization-trimmed and masked before LLM exposure.
- Output DLP is applied before returning the answer.
- Trace/audit store hashes the raw query/answer rather than storing their full text in core fields.
- However, the **current user query is not input-masked before the NVIDIA LLM call**.
- Query text is also sent to NVIDIA embedding when semantic retrieval is invoked.
- During ingestion, document chunks are sent to NVIDIA embedding before runtime context masking, so private corpus text crosses the hosted embedding boundary.

Therefore do not send regulated secrets or highly confidential corpus content to the hosted trial endpoint merely because output DLP/RLS are enabled. For strict data-sovereignty requirements, self-host LLM/embedding NIMs or add a governed input-minimization/tokenization layer whose loss of retrieval semantics is evaluated.

## 6. Production acceptance gates

Minimum pass criteria before end-user release:
- Cross-tenant leakage: **0 tolerated**.
- Raw secret/PII in returned answer/source/trace/audit: **0 tolerated**.
- Direct injection provider calls: **0** for deterministically blocked requests.
- Citation-valid rate for enterprise factual responses: **100%**.
- p95/p99: measured against your own SLO and NVIDIA region/model, not guessed offline.
- c1/c2: 100% expected success during healthy-provider benchmark.
- saturation: controlled overload, no container restart/OOM/unbounded queue.
- soak: 8-24h, stable memory/FD/DB connections.
- chaos: NVIDIA 429/503, Postgres restart, network latency, full disk, stale index.
