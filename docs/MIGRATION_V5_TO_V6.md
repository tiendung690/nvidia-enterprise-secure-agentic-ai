# Migration v5 -> v6

## Breaking operational changes

1. Version tăng lên `6.0.0`.
2. Production config bắt buộc `MEMORY_BACKEND=postgres` và `TRACE_BACKEND=postgres`.
3. Chạy lần lượt SQL migration `004_governed_memory_and_trace.sql` và `005_v6_security_hardening.sql` trước app rollout.
4. Chat response thêm `run_id`, `memory_audit`, `retrieval_traces` và hai latency stages.
5. Cache key thêm memory version; deploy sẽ làm cold cache theo thiết kế.
6. `CONVERSATION_CONTEXT_MODE=bounded` dùng workflow context mới mỗi request.
7. Production bắt buộc PostgreSQL cho audit, document registry và operational data.
8. Preference auto-capture chỉ nhận durable marker + allow-list; có thể tắt bằng `MEMORY_AUTO_CAPTURE_PREFERENCES=false`.

## Rollout sequence

1. Backup database và xác nhận PITR.
2. Apply migration 004 rồi 005 bằng migration role.
3. Deploy app v6 ở canary với read traffic nhỏ.
4. Ingest/rebuild indexes ngoài request path.
5. Verify readiness capability fields và PostgreSQL audit/memory/trace ping.
6. Test cross-tenant negative cases, memory ownership và trace lookup.
7. So sánh retrieval quality/latency với v5 bằng fixed eval set.
8. Tăng traffic, theo dõi fallback, citation failure, provider retry và DB saturation.
9. Rollback app nếu cần; giữ bảng v6 vì additive.

## Compatibility

Các field response v5 vẫn được giữ. Endpoint chat và ingest không đổi. Memory endpoints là mới.
Local/test có thể dùng in-memory memory và JSONL trace; không được dùng profile này cho multi-
replica production.


## Workers

- Chạy retention bằng credential riêng có `BYPASSRLS`; app role không đủ quyền.
- Chạy outbox dispatcher dưới supervisor/Kubernetes Job hoặc thay JSONL sink bằng broker adapter.
- Consumer phải idempotent theo `event_id` vì delivery là at-least-once.

## Production Compose

```bash
export POSTGRES_ADMIN_PASSWORD='<secret-manager-injected>'
docker compose -f docker-compose.yml -f docker-compose.production.yml config
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d app
```

Production validation cố ý reject example API keys, admin tokens, masking salts, database
passwords, HS256 và development identity headers.
