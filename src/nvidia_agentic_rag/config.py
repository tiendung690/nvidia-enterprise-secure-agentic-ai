from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "nvidia-enterprise-secure-agentic-ai"
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"

    nvidia_api_key: SecretStr | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_llm_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    nvidia_embedding_model: str = "nvidia/nv-embedqa-e5-v5"
    nvidia_temperature: float = 0.2
    nvidia_top_p: float = 0.9
    nvidia_max_tokens: int = 2048
    nvidia_reasoning_budget: int = 768
    nvidia_enable_thinking: bool = True
    nvidia_force_nonempty_content: bool = True
    nvidia_medium_effort: bool = False
    nvidia_timeout_seconds: float = 60.0
    # SDK-level retries remain low; the agent runtime owns bounded retry/circuit semantics.
    # Chat SDK retries are disabled; the runtime is the single retry owner.
    nvidia_max_retries: int = 0
    nvidia_embedding_max_retries: int = 1
    provider_retry_max_attempts: int = 2
    provider_retry_base_seconds: float = 1.5
    provider_retry_max_seconds: float = 20.0
    provider_retry_jitter: bool = True
    # Total wall-clock budget for deterministic direct-RAG synthesis.
    direct_rag_provider_deadline_seconds: float = 15.0
    # End-to-end hosted-model budget for the agent lane across retries/tool orchestration.
    # The 550B hosted reasoning model can legitimately take >30 s across an agent turn on shared
    # capacity.  Keep the provider lane bounded well below the 120 s request budget, but avoid the
    # observed ~30 s false timeout cliff.  Deterministic/evidence-sufficiency routes should bypass
    # this budget entirely.
    agent_provider_deadline_seconds: float = 45.0
    provider_circuit_breaker_enabled: bool = True
    provider_circuit_breaker_failures: int = 5
    provider_circuit_breaker_reset_seconds: float = 60.0
    # NVIDIA managed endpoint for Nemotron-3-Ultra currently rejects requests above a
    # 258,048-token total context. Earlier releases advertised 1,000,000 here, which let
    # LlamaIndex assemble prompts the provider could never accept. Keep the configured hard
    # ceiling provider-realistic and reserve additional headroom below it.
    nvidia_context_window: int = 258_048
    nvidia_context_safety_tokens: int = 8_192
    nvidia_embedding_batch_size: int = 16
    nvidia_embedding_max_input_tokens: int = 512
    nvidia_embedding_token_safety_margin: int = 192
    nvidia_embedding_truncate: Literal["NONE", "START", "END"] = "END"

    # Tiered model gateway (v6.2.1, ADR-018). Routing is enabled by default. If no alternate
    # fast model is configured, direct-RAG uses the primary model with thinking disabled and a
    # smaller output cap; a distinct fast model can additionally isolate provider capacity.
    model_tier_routing_enabled: bool = True
    nvidia_fast_llm_model: str | None = None
    nvidia_fast_max_tokens: int = 1024
    # Optional override when a distinct fast model has a smaller context window. When unset,
    # the primary provider context ceiling is used and still capped by known model limits.
    nvidia_fast_context_window: int | None = None
    gateway_degrade_to_fast: bool = True

    # Cross-lane escalation (v6.2, ADR-019): a direct-RAG route that yields no authorized
    # evidence escalates once to the bounded agent lane before the evidence gate fails closed.
    cross_lane_escalation_enabled: bool = False

    # Per-tenant daily budgets (v6.2, ADR-019). Zero disables enforcement.
    tenant_daily_request_budget: int = 0
    tenant_daily_token_budget: int = 0

    agent_mode: Literal["function", "react"] = "function"
    agent_request_timeout_seconds: float = 120.0
    agent_max_concurrent_requests: int = 2
    agent_queue_timeout_seconds: float = 3.0
    session_concurrency_policy: Literal["serialize", "reject"] = "reject"
    session_lock_wait_timeout_seconds: float = 5.0
    # Global guardrail stays small, while trusted deterministic capabilities may have
    # narrower per-tool reuse limits. This prevents a global same-tool limit of 1 from
    # breaking legitimate multi-step analytics/calculation queries.
    agent_max_tool_calls: int = 6
    agent_max_same_tool_calls: int = 1
    agent_max_calculator_calls: int = 3
    agent_max_analytics_same_tool_calls: int = 3
    enterprise_factual_fail_closed: bool = True
    deterministic_router_enabled: bool = True
    direct_rag_enabled: bool = True

    data_dir: Path = Path("data")
    course_data_dir: Path = Path("data/course")
    papers_data_dir: Path = Path("data/papers")
    storage_dir: Path = Path("storage")
    course_rag_top_k: int = 6
    papers_rag_top_k: int = 5
    retrieval_candidate_multiplier: int = 4
    course_rag_min_score: float = 0.30
    papers_rag_min_score: float = 0.30
    rag_chunk_size: int = 256
    rag_chunk_overlap: int = 32
    auto_ingest: bool = False

    # Layered retrieval: query transformation -> hybrid search -> fusion -> rerank -> quality gate.
    multi_query_enabled: bool = True
    multi_query_max_variants: int = 3
    hybrid_retrieval_enabled: bool = True
    hybrid_rrf_k: int = 60
    retrieval_rerank_enabled: bool = True
    retrieval_fallback_enabled: bool = True
    retrieval_quality_high_score: float = 0.72
    retrieval_quality_standard_score: float = 0.45
    retrieval_quality_minimum_coverage: float = 0.25
    retrieval_quality_fail_closed: bool = True
    retrieval_cache_ttl_seconds: int = 300
    retrieval_cache_max_entries: int = 500

    # Governed durable memory. Policy/preference use exact enumeration; fact/episode use search.
    memory_backend: Literal["disabled", "memory", "postgres"] = "memory"
    memory_database_url: str | None = None
    memory_exact_limit: int = 50
    memory_semantic_limit: int = 6
    memory_prompt_max_chars: int = 8000
    memory_auto_capture_preferences: bool = True

    # Bounded conversation state prevents prompt growth and limits session blast radius.
    conversation_recent_turns: int = 4
    conversation_max_chars: int = 12000
    conversation_context_mode: Literal["bounded", "legacy"] = "bounded"

    # Replayable run trace. Postgres is required in production when tracing is enabled.
    trace_backend: Literal["memory", "jsonl", "postgres"] = "jsonl"
    trace_log_path: Path = Path("storage/traces/agent-runs.jsonl")
    trace_retention_days: int = 30

    # Source-of-truth and derived-context configuration.
    document_registry_backend: Literal["json", "postgres"] = "json"
    document_security_manifest: Path = Path("data/security-manifest.json")
    require_document_security_metadata: bool = True
    operational_data_backend: Literal["json", "postgres"] = "json"
    operational_orders_file: Path = Path("data/operational/orders.json")
    database_url: str = "postgresql://agentic_app:agentic_app@postgres:5432/agentic_ai"
    document_registry_database_url: str | None = None

    # Lakehouse gold analytics read path (v6.3, ADR-020). The medallion pipeline owns
    # bronze/silver; this service reads only the curated gold serving tables via delta-rs
    # (no Spark in the API container). Disabled by default.
    analytics_backend: Literal["disabled", "delta"] = "disabled"
    delta_warehouse_root: Path = Path("data/lakehouse/dcea_medallion.db")
    delta_gold_customer_summary_table: str = "gold_customer_order_summary"
    delta_gold_book_sales_table: str = "gold_book_sales_summary"
    analytics_tenant_id: str = "tenant-a"
    analytics_max_rows: int = 10
    analytics_snapshot_ttl_seconds: int = 60

    # Authentication and authorization.
    auth_mode: Literal["dev", "jwt"] = "dev"
    allow_dev_identity_headers: bool = True
    jwt_issuer: str = ""
    jwt_audience: str = ""
    jwt_jwks_url: str = ""
    jwt_hs256_secret: SecretStr | None = None
    jwt_algorithms: tuple[str, ...] = ("RS256", "HS256")
    jwt_clock_skew_seconds: int = 30
    jwt_tenant_claim: str = "tenant_id"
    jwt_roles_claim: str = "roles"
    jwt_departments_claim: str = "departments"
    jwt_clearance_claim: str = "clearance"
    jwt_authorization_version_claim: str = "authz_version"
    default_clearance: str = "public"
    enterprise_policy_version: str = "enterprise-policy-v1"
    allowed_purposes: tuple[str, ...] = (
        "learning",
        "research",
        "architecture-review",
        "security-audit",
        "customer-support",
        "operations-review",
        "business-analytics",
    )

    # DLP and context minimization.
    context_masking_mode: Literal["off", "redact", "pseudonymize"] = "pseudonymize"
    masking_salt: SecretStr = SecretStr("change-this-local-salt")
    output_dlp_mode: Literal["off", "audit", "redact", "block"] = "redact"

    prompt_guard_mode: Literal["off", "audit", "block"] = "block"
    indirect_prompt_guard_mode: Literal["off", "audit", "block"] = "audit"
    citation_validation_mode: Literal["off", "audit", "strict"] = "strict"
    citation_minimum_coverage: float = 0.90
    citation_repair_mode: Literal["off", "conservative"] = "conservative"
    citation_repair_max_attempts: int = 1

    # End-user response budgets reduce token cost, queue occupancy, and timeout probability.
    answer_budget_simple_words: int = 300
    answer_budget_comparison_words: int = 700
    answer_budget_long_words: int = 1200
    answer_budget_simple_sources: int = 5
    answer_budget_comparison_sources: int = 8
    answer_budget_long_sources: int = 10

    response_cache_ttl_seconds: int = 1800
    response_cache_max_entries: int = 1000
    session_ttl_seconds: int = 3600
    session_max_entries: int = 5000

    audit_backend: Literal["memory", "jsonl", "postgres"] = "jsonl"
    audit_log_path: Path = Path("storage/audit/security-audit.jsonl")
    admin_token: SecretStr | None = None
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8000"]
    )

    @field_validator(
        "data_dir",
        "course_data_dir",
        "papers_data_dir",
        "storage_dir",
        "document_security_manifest",
        "operational_orders_file",
        "delta_warehouse_root",
        "audit_log_path",
        "trace_log_path",
        mode="before",
    )
    @classmethod
    def expand_path(cls, value: str | Path) -> Path:
        return Path(value).expanduser().resolve()

    @field_validator("jwt_algorithms", "allowed_purposes", mode="before")
    @classmethod
    def tuple_from_csv_or_json(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                import json

                return tuple(json.loads(stripped))
            return tuple(item.strip() for item in stripped.split(",") if item.strip())
        return value

    @model_validator(mode="after")
    def validate_runtime(self) -> Settings:
        if not self.nvidia_api_key and self.environment != "test":
            raise ValueError("NVIDIA_API_KEY is required")
        if self.tenant_daily_request_budget < 0 or self.tenant_daily_token_budget < 0:
            raise ValueError("Tenant daily budgets must be zero or positive")
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("RAG_CHUNK_OVERLAP must be smaller than RAG_CHUNK_SIZE")
        if self.nvidia_embedding_token_safety_margin >= self.nvidia_embedding_max_input_tokens:
            raise ValueError(
                "NVIDIA_EMBEDDING_TOKEN_SAFETY_MARGIN must be smaller than "
                "NVIDIA_EMBEDDING_MAX_INPUT_TOKENS"
            )
        if self.nvidia_reasoning_budget > self.nvidia_max_tokens:
            raise ValueError("NVIDIA_REASONING_BUDGET must not exceed NVIDIA_MAX_TOKENS")
        if self.nvidia_context_safety_tokens <= 0:
            raise ValueError("NVIDIA_CONTEXT_SAFETY_TOKENS must be positive")
        if self.nvidia_context_window <= self.nvidia_context_safety_tokens + self.nvidia_max_tokens:
            raise ValueError(
                "NVIDIA_CONTEXT_WINDOW must exceed NVIDIA_CONTEXT_SAFETY_TOKENS + "
                "NVIDIA_MAX_TOKENS"
            )
        if self.nvidia_fast_context_window is not None and (
            self.nvidia_fast_context_window
            <= self.nvidia_context_safety_tokens + self.nvidia_fast_max_tokens
        ):
            raise ValueError(
                "NVIDIA_FAST_CONTEXT_WINDOW must exceed NVIDIA_CONTEXT_SAFETY_TOKENS + "
                "NVIDIA_FAST_MAX_TOKENS"
            )
        if self.environment == "production" and self.allow_dev_identity_headers:
            raise ValueError("ALLOW_DEV_IDENTITY_HEADERS must be false in production")
        if self.environment == "production" and self.auth_mode != "jwt":
            raise ValueError("AUTH_MODE must be jwt in production")
        if self.environment == "production" and self.auto_ingest:
            raise ValueError("AUTO_INGEST must be false in production; run ingestion as a job")
        if self.auth_mode == "jwt" and not (self.jwt_jwks_url or self.jwt_hs256_secret):
            raise ValueError("JWT_JWKS_URL or JWT_HS256_SECRET is required in jwt mode")
        if self.document_registry_backend == "postgres" and not (
            self.document_registry_database_url or self.database_url
        ):
            raise ValueError(
                "DOCUMENT_REGISTRY_DATABASE_URL or DATABASE_URL is required for the "
                "Postgres document registry"
            )
        if self.operational_data_backend == "postgres" and not self.database_url:
            raise ValueError("DATABASE_URL is required for Postgres operational data")
        if self.analytics_backend == "delta" and not self.analytics_tenant_id.strip():
            raise ValueError("ANALYTICS_TENANT_ID is required for the Delta analytics backend")
        if self.memory_backend == "postgres" and not (
            self.memory_database_url or self.database_url
        ):
            raise ValueError("MEMORY_DATABASE_URL or DATABASE_URL is required for memory")
        if self.trace_backend == "postgres" and not self.database_url:
            raise ValueError("DATABASE_URL is required for Postgres trace storage")
        if self.environment == "production" and self.memory_backend != "postgres":
            raise ValueError("MEMORY_BACKEND must be postgres in production")
        if self.environment == "production" and self.trace_backend != "postgres":
            raise ValueError("TRACE_BACKEND must be postgres in production")
        if self.environment == "production" and self.audit_backend != "postgres":
            raise ValueError("AUDIT_BACKEND must be postgres in production")
        if self.environment == "production" and self.document_registry_backend != "postgres":
            raise ValueError("DOCUMENT_REGISTRY_BACKEND must be postgres in production")
        if self.environment == "production" and self.operational_data_backend != "postgres":
            raise ValueError("OPERATIONAL_DATA_BACKEND must be postgres in production")
        if self.conversation_context_mode != "bounded":
            raise ValueError(
                "CONVERSATION_CONTEXT_MODE=legacy is no longer supported. Use bounded mode so "
                "provider workflow state cannot accumulate unbounded tool/message history."
            )
        if self.environment == "production" and self.citation_validation_mode != "strict":
            raise ValueError("CITATION_VALIDATION_MODE must be strict in production")
        if self.environment == "production" and self.prompt_guard_mode != "block":
            raise ValueError("PROMPT_GUARD_MODE must be block in production")
        if self.environment == "production" and self.output_dlp_mode not in {"redact", "block"}:
            raise ValueError("OUTPUT_DLP_MODE must be redact or block in production")
        if self.environment == "production" and not self.require_document_security_metadata:
            raise ValueError("REQUIRE_DOCUMENT_SECURITY_METADATA must be true in production")
        if self.environment == "production" and not self.jwt_jwks_url:
            raise ValueError("JWT_JWKS_URL is required in production")
        if self.environment == "production" and "HS256" in self.jwt_algorithms:
            raise ValueError("HS256 must not be enabled in production")
        if self.environment == "production":
            api_key = self.api_key_value()
            admin_token = (
                self.admin_token.get_secret_value() if self.admin_token is not None else ""
            )
            masking_salt = self.masking_salt_value()
            secret_values = {
                "NVIDIA_API_KEY": api_key,
                "ADMIN_TOKEN": admin_token,
                "MASKING_SALT": masking_salt,
            }
            for name, value in secret_values.items():
                lowered = value.casefold()
                if len(value) < 32 or any(
                    marker in lowered for marker in ("replace", "change-this", "example")
                ):
                    raise ValueError(f"{name} must be a non-placeholder secret of 32+ characters")
            database_urls = {
                "DATABASE_URL": self.database_url,
                "MEMORY_DATABASE_URL": self.memory_database_url or self.database_url,
                "DOCUMENT_REGISTRY_DATABASE_URL": (
                    self.document_registry_database_url or self.database_url
                ),
            }
            for name, url in database_urls.items():
                if "agentic_app:agentic_app" in url or "agentic_admin:agentic_admin" in url:
                    raise ValueError(f"{name} must not use the packaged development password")

        positive_timeouts = {
            "NVIDIA_TIMEOUT_SECONDS": self.nvidia_timeout_seconds,
            "AGENT_REQUEST_TIMEOUT_SECONDS": self.agent_request_timeout_seconds,
            "AGENT_QUEUE_TIMEOUT_SECONDS": self.agent_queue_timeout_seconds,
            "SESSION_LOCK_WAIT_TIMEOUT_SECONDS": self.session_lock_wait_timeout_seconds,
            "PROVIDER_RETRY_BASE_SECONDS": self.provider_retry_base_seconds,
            "DIRECT_RAG_PROVIDER_DEADLINE_SECONDS": self.direct_rag_provider_deadline_seconds,
            "AGENT_PROVIDER_DEADLINE_SECONDS": self.agent_provider_deadline_seconds,
            "PROVIDER_RETRY_MAX_SECONDS": self.provider_retry_max_seconds,
            "PROVIDER_CIRCUIT_BREAKER_RESET_SECONDS": (
                self.provider_circuit_breaker_reset_seconds
            ),
        }
        for name, value in positive_timeouts.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.provider_retry_base_seconds > self.provider_retry_max_seconds:
            raise ValueError(
                "PROVIDER_RETRY_BASE_SECONDS must not exceed PROVIDER_RETRY_MAX_SECONDS"
            )
        if self.direct_rag_provider_deadline_seconds >= self.agent_request_timeout_seconds:
            raise ValueError(
                "DIRECT_RAG_PROVIDER_DEADLINE_SECONDS must be lower than "
                "AGENT_REQUEST_TIMEOUT_SECONDS"
            )
        if self.agent_provider_deadline_seconds >= self.agent_request_timeout_seconds:
            raise ValueError(
                "AGENT_PROVIDER_DEADLINE_SECONDS must be lower than AGENT_REQUEST_TIMEOUT_SECONDS"
            )

        bounded_scores = {
            "COURSE_RAG_MIN_SCORE": self.course_rag_min_score,
            "PAPERS_RAG_MIN_SCORE": self.papers_rag_min_score,
            "CITATION_MINIMUM_COVERAGE": self.citation_minimum_coverage,
            "RETRIEVAL_QUALITY_HIGH_SCORE": self.retrieval_quality_high_score,
            "RETRIEVAL_QUALITY_STANDARD_SCORE": self.retrieval_quality_standard_score,
            "RETRIEVAL_QUALITY_MINIMUM_COVERAGE": self.retrieval_quality_minimum_coverage,
        }
        for name, value in bounded_scores.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")

        positive_values = {
            "AGENT_MAX_TOOL_CALLS": self.agent_max_tool_calls,
            "AGENT_MAX_CONCURRENT_REQUESTS": self.agent_max_concurrent_requests,
            "PROVIDER_RETRY_MAX_ATTEMPTS": self.provider_retry_max_attempts,
            "NVIDIA_FAST_MAX_TOKENS": self.nvidia_fast_max_tokens,
            "NVIDIA_CONTEXT_SAFETY_TOKENS": self.nvidia_context_safety_tokens,
            "PROVIDER_CIRCUIT_BREAKER_FAILURES": self.provider_circuit_breaker_failures,
            "CITATION_REPAIR_MAX_ATTEMPTS": self.citation_repair_max_attempts,
            "ANSWER_BUDGET_SIMPLE_WORDS": self.answer_budget_simple_words,
            "ANSWER_BUDGET_COMPARISON_WORDS": self.answer_budget_comparison_words,
            "ANSWER_BUDGET_LONG_WORDS": self.answer_budget_long_words,
            "ANSWER_BUDGET_SIMPLE_SOURCES": self.answer_budget_simple_sources,
            "ANSWER_BUDGET_COMPARISON_SOURCES": self.answer_budget_comparison_sources,
            "ANSWER_BUDGET_LONG_SOURCES": self.answer_budget_long_sources,
            "AGENT_MAX_SAME_TOOL_CALLS": self.agent_max_same_tool_calls,
            "AGENT_MAX_CALCULATOR_CALLS": self.agent_max_calculator_calls,
            "AGENT_MAX_ANALYTICS_SAME_TOOL_CALLS": (
                self.agent_max_analytics_same_tool_calls
            ),
            "RETRIEVAL_CANDIDATE_MULTIPLIER": self.retrieval_candidate_multiplier,
            "RESPONSE_CACHE_TTL_SECONDS": self.response_cache_ttl_seconds,
            "RESPONSE_CACHE_MAX_ENTRIES": self.response_cache_max_entries,
            "RETRIEVAL_CACHE_TTL_SECONDS": self.retrieval_cache_ttl_seconds,
            "RETRIEVAL_CACHE_MAX_ENTRIES": self.retrieval_cache_max_entries,
            "SESSION_TTL_SECONDS": self.session_ttl_seconds,
            "SESSION_MAX_ENTRIES": self.session_max_entries,
            "MULTI_QUERY_MAX_VARIANTS": self.multi_query_max_variants,
            "HYBRID_RRF_K": self.hybrid_rrf_k,
            "MEMORY_EXACT_LIMIT": self.memory_exact_limit,
            "MEMORY_SEMANTIC_LIMIT": self.memory_semantic_limit,
            "MEMORY_PROMPT_MAX_CHARS": self.memory_prompt_max_chars,
            "CONVERSATION_RECENT_TURNS": self.conversation_recent_turns,
            "CONVERSATION_MAX_CHARS": self.conversation_max_chars,
            "TRACE_RETENTION_DAYS": self.trace_retention_days,
            "ANALYTICS_MAX_ROWS": self.analytics_max_rows,
            "ANALYTICS_SNAPSHOT_TTL_SECONDS": self.analytics_snapshot_ttl_seconds,
        }
        for name, value in positive_values.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        same_tool_limits = {
            "AGENT_MAX_SAME_TOOL_CALLS": self.agent_max_same_tool_calls,
            "AGENT_MAX_CALCULATOR_CALLS": self.agent_max_calculator_calls,
            "AGENT_MAX_ANALYTICS_SAME_TOOL_CALLS": self.agent_max_analytics_same_tool_calls,
        }
        for name, value in same_tool_limits.items():
            if value > self.agent_max_tool_calls:
                raise ValueError(f"{name} must not exceed AGENT_MAX_TOOL_CALLS")
        if self.retrieval_quality_high_score < self.retrieval_quality_standard_score:
            raise ValueError(
                "RETRIEVAL_QUALITY_HIGH_SCORE must be >= RETRIEVAL_QUALITY_STANDARD_SCORE"
            )
        return self

    def provider_context_limit(self, model: str, *, configured: int | None = None) -> int:
        """Return the provider-realistic total context ceiling for a hosted model.

        The configured value is treated as an upper bound, not an assertion that the endpoint
        supports that many tokens. This protects upgrades that reuse an old .env containing a
        stale 1,000,000-token value.
        """
        requested = int(configured or self.nvidia_context_window)
        known_limits = {
            "nvidia/nemotron-3-ultra-550b-a55b": 258_048,
        }
        known = known_limits.get(model.casefold())
        return min(requested, known) if known is not None else requested

    def effective_llm_context_window(
        self,
        *,
        model: str,
        max_tokens: int,
        configured: int | None = None,
    ) -> int:
        """Context window exposed to LlamaIndex after provider and safety headroom.

        LlamaIndex uses this metadata to compact workflow chat/tool history before the provider
        request. ``max_tokens`` is still passed separately to the SDK; the additional safety
        reserve covers chat templates, tool schemas, and provider-side tokenization variance.
        """
        hard_limit = self.provider_context_limit(model, configured=configured)
        usable = hard_limit - self.nvidia_context_safety_tokens
        minimum = max_tokens + 4_096
        if usable < minimum:
            raise ValueError(
                f"Effective context window {usable} is too small for max_tokens={max_tokens}"
            )
        return usable

    def api_key_value(self) -> str:
        if not self.nvidia_api_key:
            raise RuntimeError("NVIDIA_API_KEY is not configured")
        return self.nvidia_api_key.get_secret_value()

    def jwt_hs256_secret_value(self) -> str | None:
        return self.jwt_hs256_secret.get_secret_value() if self.jwt_hs256_secret else None

    def masking_salt_value(self) -> str:
        return self.masking_salt.get_secret_value()
