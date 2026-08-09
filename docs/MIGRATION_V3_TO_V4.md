# Migration v3 -> v4

## Breaking API changes

`POST /v1/chat` thêm:

```json
{
  "purpose": "research",
  "answer_mode": "enterprise_factual"
}
```

Response thêm `policy_audit`; `SourceReference` thêm source kind, tenant, classification, version,
policy decision và masking fields.

## Identity

Local/test dùng development headers. Production bắt buộc `AUTH_MODE=jwt` và Bearer token.

## Ingestion

Mọi file phải có record trong `data/security-manifest.json` hoặc PostgreSQL `document_registry`.
Sau upgrade phải rebuild index vì schema version v4 chứa security metadata.

```bash
docker compose down -v
docker compose build --no-cache
docker compose --profile tools run --rm ingest
docker compose up -d app
```

## Cache

Cache v4 không tương thích v3 vì key thêm authorization hash, purpose, policy version và answer mode.
In-process cache tự mất sau restart; distributed cache phải namespace theo v4 schema.
