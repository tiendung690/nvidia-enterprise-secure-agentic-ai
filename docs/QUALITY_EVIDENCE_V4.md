# Quality Evidence v4.0

## Offline evidence

```text
69 tests passed
91.52% measured core-logic coverage
78 Python files
6,137 lines
Valid AST
Maximum line length <= 100
No trailing whitespace
```

## Security test evidence

- Query purpose allow/deny.
- Cross-tenant document denial.
- Classification/clearance denial.
- Role and department denial.
- Shared-tenant allow.
- JWT signature and claim mapping.
- Context masking before model exposure.
- Output audit/redact/block.
- Tenant-scoped operational lookup.
- Database citation prefix `[D...]`.
- Enterprise factual abstention without sources.
- Authorization-version cache invalidation.
- Document registry fail closed and duplicate detection.
- Audit sink avoids raw query fields.

## Reproducible commands

```bash
python scripts/validate_repo.py
python scripts/audit_corpus.py
python -m compileall -q src scripts tests
python scripts/static_quality.py
pytest -m 'not live'
```

## Quality interpretation

Repo đạt mức strong production-oriented reference cho portfolio/phỏng vấn, không được mô tả là
certified enterprise production. Điểm còn thiếu để tiến gần 10/10: integration test PostgreSQL/RLS,
managed vector metadata pre-filter, distributed cache/session, external policy engine, OpenTelemetry,
load/soak/chaos tests, security red-team và private inference deployment evidence.
