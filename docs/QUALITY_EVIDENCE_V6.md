# Quality evidence — v6.0.0

Evidence captured during the offline repository upgrade on 2026-08-07.

## Automated results

| Check | Result |
|---|---|
| Python compilation | Passed for `src`, `scripts`, and `tests` |
| Static repository quality | 107 Python files, 12,352 lines; valid AST; line length <= 100; no trailing whitespace |
| Unit/offline tests | 101 passed |
| Skipped dependency tests | 4 skipped: 2 PostgreSQL integration, 2 NVIDIA live |
| Configured core coverage | 91.21%, threshold 90% |
| Secret/runtime validation | Passed: no packaged `.env`, API-key pattern, or local-inference dependency |
| Corpus integrity | Passed for the required course and paper fixtures |
| Compose YAML parsing | Passed for base and production override files |
| Package version | `6.0.0` in package and `pyproject.toml` |

Commands:

```bash
python -m compileall -q src scripts tests
python scripts/static_quality.py
python scripts/validate_repo.py
python scripts/audit_corpus.py
PYTHONPATH=src pytest -q --disable-warnings --maxfail=10
PYTHONPATH=src pytest --no-cov --disable-warnings -ra
```

## What the tests cover

- Guarded query transformation and identifier preservation.
- BM25 retrieval, RRF, deterministic reranking and quality tiers.
- Security-filtered lexical and bounded fallback paths.
- Typed memory promotion, confidence/provenance rules and scope assignment.
- Exact-memory overflow and prompt-budget fail-closed behavior.
- Prompt-safe memory formatting and injection rejection.
- Deterministic explicit preference capture and no arbitrary fact inference.
- Content-hash deduplication, provisional approval and SCD2 supersession.
- Physical memory erasure behavior in the local repository.
- Bounded conversation projection.
- Hash-only, tenant-scoped trace behavior.
- Production configuration invariants.
- Existing policy, cache, citations, safety, provider resilience and admission controls.

## Gates not executed in this environment

The following were not available and are not claimed as passed:

- Live PostgreSQL migration/RLS/outbox/retention execution.
- Live NVIDIA chat and embedding requests.
- Docker image build, production Compose startup, health checks and shutdown behavior.
- OpenAPI boot test with the complete LlamaIndex runtime dependency set.
- Load, soak, chaos, DR, canary, rollback and red-team exercises.

These are deployment acceptance gates, not optional documentation tasks. See
`docs/PRODUCTION_READINESS_V6_VI.md`.

## Interpretation

The evidence supports a high-quality executable reference architecture and an offline-tested
production baseline. It does not prove that an untested target environment is production-ready.
