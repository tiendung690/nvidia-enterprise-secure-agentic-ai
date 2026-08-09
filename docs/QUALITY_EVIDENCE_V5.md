# Quality Evidence v5

## Offline evidence generated during packaging

| Gate | Result |
|---|---|
| Python compilation | PASS |
| Static AST and line length | PASS |
| Repository secret/local-runtime validation | PASS |
| Unit tests | PASS |
| Live tests | SKIPPED without rotated NVIDIA key |
| Configured core coverage | >= 90% |

## Executable controls covered by tests

- Authorization before agent execution.
- Prompt injection block before tool/model calls.
- Fail-closed when enterprise factual context is absent.
- Tenant/auth/index/prompt scoped cache behavior.
- Output DLP redaction.
- Current-turn source collection.
- Citation unknown-ID and coverage validation.
- Markdown table claim parsing.
- Conservative citation repair.
- Provider transient retry and exhausted retry budget.
- Provider circuit breaker open/half-open recovery.
- Same-session reject and serialize policies.
- Global capacity wait timeout distinct from execution timeout.
- Dynamic answer budget classification.

## Live evidence commands

```bash
python scripts/evaluate_api.py --base-url http://localhost:8000
python scripts/performance_suite.py --base-url http://localhost:8000 --concurrency 2
```

Artifacts are written to:

```text
artifacts/evaluation/
artifacts/performance/
```

## Hard NO-GO conditions

- Any cross-tenant leakage.
- Any raw secret/PII disclosure contrary to policy.
- Any arbitrary SQL/shell/tool escalation.
- Any enterprise factual answer returned while citation audit is invalid in strict mode.
- Cache hit after authorization/index/policy/prompt version changes.
- Retry of a non-idempotent write workflow without idempotency/HITL controls.
