# Security baseline

1. NVIDIA API keys are environment secrets and are excluded from packages, Docker context, logs, and responses.
2. A key disclosed in chat, screenshots, logs, or Git history must be revoked and replaced.
3. Retrieved documents and tool results are untrusted data, not instructions.
4. Direct and indirect prompt-injection detection are risk signals, not authorization boundaries.
5. Only read-oriented tools are registered. Write/destructive tools require policy-as-code, resource authorization, idempotency, explicit confirmation/HITL, and audit.
6. Tool schemas and deterministic runtime budgets bound malformed calls, loops, cost, and latency.
7. Calculator input uses an AST allow-list and numeric magnitude limits; Python `eval()` is never used.
8. Cache keys include user/session, data version, model parameters, agent mode, and prompt version.
9. Cached grounded answers retain source provenance and are stored only when citation validation passes.
10. Development identity headers must be disabled in production and replaced with verified OIDC/JWT claims.
11. Production retrieval must apply tenant/document ACL metadata filters before evidence reaches the model.
12. Logs must redact PII, credentials, confidential tool arguments, and source text where required.
13. Ingestion runs as a separate job and atomically swaps completed indexes; the serving process does not build indexes on startup in production.
14. Multi-replica deployments require shared state/cache and a managed vector store or immutable published index artifact.
