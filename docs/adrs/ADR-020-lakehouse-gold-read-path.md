# ADR-020 — Lakehouse gold read path via delta-rs

## Status
Accepted (v6.3)

## Context
The agentic service needs curated business aggregates (customer order totals, book sales
totals) that are produced by a separate Spark medallion pipeline
(`dcea_demo_environment_clean`: raw → bronze → silver → gold Delta tables). Three naive
integrations were rejected: embedding PySpark in the API container (a JVM + Spark runtime
inside a latency-sensitive FastAPI service), giving the LLM SQL over the warehouse
(violates ADR-005/ADR-008: no arbitrary query surface), and re-ingesting gold rows into
the vector index (aggregates are exact operational state, not semantic evidence, and would
go stale between pipeline runs).

## Decision
1. **Serving-contract-only reads** (`data/analytics.py`): a read-only
   `DeltaGoldAnalyticsRepository` opens the two `gold_*` Delta tables directly with
   delta-rs (`deltalake`), so the API container needs no Spark/JVM. Bronze and silver
   never cross the AI boundary; `scripts/sync_lakehouse_gold.py` refuses to copy anything
   that is not `gold_*` (data minimization).
2. **Typed capabilities, not SQL** (`tools/secure_analytics.py`): three bounded tools —
   one customer aggregate by exact ID, one book aggregate by exact ID, and a clamped
   top-N — authorized through `PolicyEngine.authorize_capability("analytics.read")` with
   roles `analyst|operations|admin` and purposes `business-analytics|operations-review`.
   The repository additionally declares a single owner tenant
   (`ANALYTICS_TENANT_ID`); other tenants observe `not_found`, never an existence oracle.
3. **Versioned, citable observations**: every observation records the Delta commit
   version it was read from. `source_id` carries the raw version
   (`delta:<table>:<tenant>:<key>:v<version>`), `section` repeats it, and
   `SourceReference.source_version` stores `version + 1` because the schema field is
   1-based while Delta commits start at 0. A short-TTL pinned snapshot
   (`ANALYTICS_SNAPSHOT_TTL_SECONDS`) keeps all reads inside one request consistent with
   a single commit.
4. **DLP before context**: direct-identifier fields (customer first/last name) pass
   through the new explicit `DataMasker.mask_value` path under the configured masking
   mode before entering the model context; business keys and aggregates stay raw.
5. **Fail closed**: an unreachable or unreadable table raises
   `AnalyticsSourceUnavailableError`, which the tools map to a sourced-empty
   `analytics_unavailable` payload — never a guessed number.

## The agent-lane-only decision
The deterministic router gains no analytics route. Gold questions arrive in natural
language ("how much has customer C001 spent?"), which is exactly the ambiguity the
bounded agent lane exists for; a keyword route would either overfire on unrelated
"customer" queries or underfire and add maintenance surface. Deterministic-lane inclusion
can be revisited if telemetry shows a dominant exact-ID query shape.

## Consequences
- The gold layer is treated as a serving contract: small aggregate tables. The reader
  clamps top-N to `ANALYTICS_MAX_ROWS` and materializes only the projected columns; a
  gold table that grows beyond serving size is a pipeline-contract violation, not
  something this reader compensates for.
- The snapshot cache is process-local by contract (like the tenant-budget ledger in
  ADR-019); replicas may briefly pin different commit versions within one TTL window,
  and each response is still internally consistent and version-labelled.
- This reference implementation reads a local filesystem warehouse (read-only Docker
  mount). Object-store deployments switch `DELTA_WAREHOUSE_ROOT` to a URI plus delta-rs
  `storage_options`; credential handling then follows the same secret rules as
  `DATABASE_URL`.
- A lakehouse-gold observation is authoritative for the commit version it cites; the
  operational database remains authoritative for live order state (ADR-008). The system
  prompt instructs the agent to explain, not hide, conflicts between the two.
