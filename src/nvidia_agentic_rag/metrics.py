from prometheus_client import Counter, Gauge, Histogram

REQUESTS = Counter(
    "agentic_rag_requests_total",
    "Total chat requests",
    ["status"],
)
REQUEST_LATENCY = Histogram(
    "agentic_rag_request_latency_seconds",
    "End-to-end request latency",
)
LATENCY_STAGE = Histogram(
    "agentic_ai_latency_stage_seconds",
    "Latency by deterministic runtime stage",
    ["stage"],
)
ADMISSION_EVENTS = Counter(
    "agentic_ai_admission_events_total",
    "Admission-control outcomes",
    ["scope", "result"],
)
INFLIGHT_REQUESTS = Gauge(
    "agentic_ai_inflight_requests",
    "Currently executing fresh agent requests",
)
TOOL_CALLS = Counter(
    "agentic_rag_tool_calls_total",
    "Agent tool calls",
    ["tool", "status"],
)
TOOL_LATENCY = Histogram(
    "agentic_rag_tool_latency_seconds",
    "Observed tool-call latency",
    ["tool"],
)
CACHE_EVENTS = Counter(
    "agentic_rag_cache_events_total",
    "Response cache events",
    ["result"],
)
RETRIEVAL_SOURCES = Histogram(
    "agentic_rag_retrieval_sources",
    "Number of evidence sources returned by retrieval",
    ["corpus"],
)
RETRIEVAL_SCORE = Histogram(
    "agentic_rag_retrieval_similarity_score",
    "Retrieved-node similarity score",
    ["corpus"],
)
CITATION_VALIDATION = Counter(
    "agentic_rag_citation_validation_total",
    "Citation validation outcomes",
    ["result"],
)
CITATION_REPAIR = Counter(
    "agentic_ai_citation_repair_total",
    "Citation repair outcomes",
    ["result"],
)
INDIRECT_INJECTION_SIGNALS = Counter(
    "agentic_rag_indirect_injection_signals_total",
    "Indirect prompt-injection signals found in retrieved evidence",
    ["corpus", "signal"],
)
POLICY_DECISIONS = Counter(
    "agentic_ai_policy_decisions_total",
    "Deterministic authorization decisions",
    ["action", "result"],
)
RETRIEVAL_DENIED_CANDIDATES = Histogram(
    "agentic_ai_retrieval_denied_candidates",
    "Retrieved candidates removed by enterprise authorization",
    ["corpus"],
)
OUTPUT_DLP_EVENTS = Counter(
    "agentic_ai_output_dlp_events_total",
    "Output DLP outcomes",
    ["result"],
)
AUDIT_EVENTS = Counter(
    "agentic_ai_audit_events_total",
    "Security audit events",
    ["outcome"],
)
PROVIDER_ATTEMPTS = Counter(
    "agentic_ai_provider_attempts_total",
    "Hosted model attempts",
    ["provider", "result"],
)
PROVIDER_BACKOFF = Histogram(
    "agentic_ai_provider_backoff_seconds",
    "Backoff applied before provider retries",
    ["provider"],
)
PROVIDER_CIRCUIT = Gauge(
    "agentic_ai_provider_circuit_state",
    "Provider circuit state: 0 closed/disabled, 1 half-open, 2 open",
    ["provider"],
)

PROVIDER_TIER_ATTEMPTS = Counter(
    "agentic_ai_provider_tier_attempts_total",
    "Hosted model attempts by model tier",
    ["provider", "tier", "result"],
)
PROVIDER_TIER_CIRCUIT = Gauge(
    "agentic_ai_provider_tier_circuit_state",
    "Provider circuit state by model tier: 0 closed/disabled, 1 half-open, 2 open",
    ["provider", "tier"],
)

RETRIEVAL_EXECUTIONS = Counter(
    "agentic_ai_retrieval_executions_total",
    "Layered retrieval executions by mode, quality, and degraded state",
    ["corpus", "mode", "relevance", "degraded"],
)
MEMORY_READ_RECORDS = Histogram(
    "agentic_ai_memory_read_records",
    "Number of governed memory records loaded by retrieval path",
    ["path"],
)
MEMORY_WRITE_DECISIONS = Counter(
    "agentic_ai_memory_write_decisions_total",
    "Memory promotion decisions",
    ["memory_type", "accepted", "status"],
)
TRACE_EVENTS = Counter(
    "agentic_ai_trace_events_total",
    "Run trace lifecycle events",
    ["event"],
)

MODEL_TIER_SELECTIONS = Counter(
    "agentic_ai_model_tier_selections_total",
    "Model gateway tier decisions for provider synthesis",
    ["tier", "reason"],
)
GATEWAY_TIER_DEGRADES = Counter(
    "agentic_ai_gateway_tier_degrades_total",
    "One-shot complex-to-fast downgrades taken by the provider resilience path",
    ["trigger"],
)
ROUTE_DECISIONS = Counter(
    "agentic_ai_route_decisions_total",
    "Deterministic router lane decisions",
    ["kind"],
)
ROUTE_ESCALATIONS = Counter(
    "agentic_ai_route_escalations_total",
    "Cross-lane escalations taken after a lane produced no usable evidence",
    ["source", "target"],
)
TENANT_BUDGET_EVENTS = Counter(
    "agentic_ai_tenant_budget_events_total",
    "Per-tenant daily budget admissions and rejections",
    ["result"],
)
RETRIEVAL_PREFILTERED_DENIED = Counter(
    "agentic_ai_retrieval_prefiltered_denied_total",
    "Vector candidates removed by the pre-fusion authorization filter",
    ["corpus"],
)
