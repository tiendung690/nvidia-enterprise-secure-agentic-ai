# Quality evidence and gates

## Evidence tiers

### Tier 1 — deterministic offline evidence

- unit tests for cache isolation/expiry, citation validation, deterministic IDs, section extraction, tool budgets, prompt guards, source preservation, and index-version invalidation;
- branch-aware coverage gate for testable core logic;
- repository secret/local-model validation;
- corpus audit for known source facts.

### Tier 2 — integration evidence

- mocked embedding and agent event streams;
- persisted-index reload;
- FastAPI error mapping, admin authorization, and typed schema tests.

### Tier 3 — live NVIDIA evidence

- chat and embedding smoke tests;
- full Docker ingest/ready/chat flow;
- golden dataset for routing, answer concepts, citations, sources, cache, and latency.

## Current offline evidence

The enhanced repository was executed in the artifact build environment on
2026-08-05. The recorded report is `artifacts/OFFLINE_QUALITY_REPORT.md`.

Measured results:

- 43 offline tests passed; 2 live NVIDIA tests were intentionally deselected;
- measured core-logic coverage: 93.57%;
- 47 Python files / 3,551 lines passed AST, line-length, and trailing-whitespace checks;
- compileall passed;
- repository secret/local-inference validation passed;
- five corpus checks passed, including all four Agentic RAG course PDFs and the eRAG paper.

Run:

```bash
python scripts/validate_repo.py
python scripts/audit_corpus.py
pytest -m 'not live'
```

Expected gates:

- all offline tests pass;
- core-logic coverage >= 90%;
- no packaged `.env` or API-key pattern;
- no Ollama/local embedding runtime dependency;
- course corpus contains the explicit Basic/Agentic RAG, agent anatomy, ReAct, and
  QueryEngineTool concepts;
- paper corpus contains the eRAG definition and reported computational figures.

## Live quality gate

```bash
python scripts/evaluate_api.py --base-url http://localhost:8000
```

Default pass conditions:

- routing accuracy: 100%;
- required-term coverage: >= 90%;
- citation-valid rate: 100%;
- cache-hit rate: 100%;
- cache p95: < 500 ms;
- fresh request p95: < 60 s.

The generated reports are stored under `artifacts/evaluation/`.

## What this evidence does not prove

- semantic entailment of every claim;
- production SLOs under concurrent load;
- tenant ACL correctness without an identity provider;
- disaster recovery or multi-region behavior;
- NVIDIA capacity guarantees for a specific subscription.

Those require target-environment load tests, security reviews, calibrated human evaluation, and operational exercises.

Ruff and mypy are configured as mandatory CI gates. They could not be installed in the
offline artifact-build environment, so they are not claimed as locally executed evidence.
