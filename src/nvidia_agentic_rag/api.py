from __future__ import annotations

import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from nvidia_agentic_rag.agents.factory import PROMPT_VERSION
from nvidia_agentic_rag.agents.service import (
    AgentBudgetExceeded,
    AnswerCompletenessError,
    CitationValidationError,
    ProvenanceValidationError,
)
from nvidia_agentic_rag.bootstrap import Container, build_container
from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.identity import AuthenticationError, IdentityContext
from nvidia_agentic_rag.logging_config import configure_logging
from nvidia_agentic_rag.memory import (
    KnownScopeMemoryOverflowError,
    MemoryCandidate,
    MemoryPersistenceError,
    MemoryPromptOverflowError,
    MemoryWriteResult,
)
from nvidia_agentic_rag.metrics import MEMORY_WRITE_DECISIONS
from nvidia_agentic_rag.nvidia.errors import classify_provider_error
from nvidia_agentic_rag.policy import PolicyAudit
from nvidia_agentic_rag.runtime import (
    AgentExecutionTimeoutError,
    CapacityWaitTimeoutError,
    ProviderUnavailableError,
    SessionBusyError,
    SessionWaitTimeoutError,
    TenantBudgetExceededError,
)
from nvidia_agentic_rag.schemas import (
    AnswerCompletenessAudit,
    CitationAudit,
    EvidenceOrigin,
    LatencyBreakdown,
    MemoryAudit,
    ProvenanceAudit,
    ProvenanceDerivation,
    ProviderTrace,
    RequestOutcome,
    RetrievalTrace,
    SafetyAudit,
    SourceReference,
    ToolTrace,
)
from nvidia_agentic_rag.security import DataClassification, OutputPolicyViolation


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    session_id: str | None = Field(default=None, max_length=128)
    purpose: str = Field(default="research", min_length=1, max_length=128)
    answer_mode: str = Field(
        default="enterprise_factual",
        pattern=r"^(enterprise_factual|general_advisory)$",
    )
    force_retrieval: bool = False


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    request_outcome: RequestOutcome = "success"
    tools: list[str]
    tool_call_count: int
    latency_ms: float
    latency_breakdown: LatencyBreakdown = Field(default_factory=LatencyBreakdown)
    safety_signals: list[str]
    safety_audit: SafetyAudit = Field(default_factory=SafetyAudit)
    memory_hit: bool = False
    response_cache_hit: bool = False
    cache_admitted: bool = False
    evidence_origin: EvidenceOrigin = "fresh_generation"
    sources: list[SourceReference] = Field(default_factory=list)
    citation_audit: CitationAudit = Field(default_factory=CitationAudit)
    answer_completeness: AnswerCompletenessAudit = Field(
        default_factory=AnswerCompletenessAudit
    )
    provenance: list[ProvenanceDerivation] = Field(default_factory=list)
    provenance_audit: ProvenanceAudit = Field(default_factory=ProvenanceAudit)
    policy_audit: PolicyAudit = Field(default_factory=PolicyAudit)
    tool_trace: list[ToolTrace] = Field(default_factory=list)
    provider_trace: ProviderTrace = Field(default_factory=ProviderTrace)
    memory_audit: MemoryAudit = Field(default_factory=MemoryAudit)
    retrieval_traces: list[RetrievalTrace] = Field(default_factory=list)
    run_id: str | None = None
    index_version: str = "unknown"
    prompt_version: str = PROMPT_VERSION


class PublicCitation(BaseModel):
    citation_id: str
    title: str | None = None
    source_kind: str
    classification: str | None = None
    data_version: str | None = None
    source_as_of: str | None = None
    tool_retrieved_at: str | None = None
    masked: bool = False


class PublicChatResponse(BaseModel):
    answer: str
    session_id: str
    request_outcome: RequestOutcome = "success"
    latency_ms: float
    response_cache_hit: bool = False
    evidence_origin: EvidenceOrigin = "fresh_generation"
    citations: list[PublicCitation] = Field(default_factory=list)
    run_id: str | None = None


class IngestRequest(BaseModel):
    recreate: bool = False


class MemoryPromotionRequest(BaseModel):
    candidates: list[MemoryCandidate] = Field(min_length=1, max_length=20)


def _error_response(
    *,
    request: Request,
    status_code: int,
    error_code: str,
    detail: str,
    retry_after_seconds: int | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {
        "error_code": error_code,
        "detail": detail,
        "request_id": request.state.request_id,
    }
    if retry_after_seconds is not None:
        content["retry_after_seconds"] = retry_after_seconds
    if extra:
        content.update(extra)
    headers = {"X-Agent-Outcome": "error"}
    if retry_after_seconds is not None:
        headers["Retry-After"] = str(retry_after_seconds)
    return JSONResponse(status_code=status_code, headers=headers, content=content)


def _debug_trace_allowed(
    *, identity: IdentityContext, requested: bool, settings: Settings
) -> bool:
    # Local/test environments remain developer-friendly. Production exposes detailed policy,
    # source, provider, and tool traces only when explicitly requested by privileged roles.
    if settings.environment != "production":
        return True
    privileged = {"ai_platform_admin", "data_engineer"}
    return requested and bool(privileged.intersection(identity.roles))


def _public_chat_response(result: Any) -> PublicChatResponse:
    citations = [
        PublicCitation(
            citation_id=source.citation_id,
            title=source.title,
            source_kind=source.source_kind,
            classification=source.classification,
            data_version=source.data_version,
            source_as_of=source.source_as_of,
            tool_retrieved_at=source.tool_retrieved_at,
            masked=source.masked,
        )
        for source in result.sources
    ]
    return PublicChatResponse(
        answer=result.answer,
        session_id=result.session_id,
        request_outcome=result.request_outcome,
        latency_ms=result.latency_ms,
        response_cache_hit=result.response_cache_hit,
        evidence_origin=result.evidence_origin,
        citations=citations,
        run_id=result.run_id,
    )


def require_any_role(identity: IdentityContext, allowed_roles: set[str]) -> None:
    if not set(identity.roles).intersection(allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"One of these roles is required: {', '.join(sorted(allowed_roles))}",
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    configure_logging(resolved.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = build_container(resolved)
        yield

    app = FastAPI(
        title="Enterprise Secure Agentic AI with NVIDIA and LlamaIndex",
        version="6.4.4",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Admin-Token",
            "X-User-Id",
            "X-Tenant-Id",
            "X-Roles",
            "X-Departments",
            "X-Clearance",
            "X-Authorization-Version",
            "X-Request-ID",
            "X-Debug-Trace",
        ],
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def container(request: Request) -> Container:
        return request.app.state.container

    def resolve_identity(
        request: Request,
        authorization: Annotated[str | None, Header(alias="Authorization")] = None,
        x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
        x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
        x_roles: Annotated[str | None, Header(alias="X-Roles")] = None,
        x_departments: Annotated[str | None, Header(alias="X-Departments")] = None,
        x_clearance: Annotated[str | None, Header(alias="X-Clearance")] = None,
        x_authz_version: Annotated[
            str | None, Header(alias="X-Authorization-Version")
        ] = None,
        c: Container = Depends(container),
    ) -> IdentityContext:
        if resolved.auth_mode == "jwt":
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="A Bearer token is required",
                )
            try:
                return c.authenticator.authenticate(authorization.removeprefix("Bearer ").strip())
            except AuthenticationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=str(exc),
                ) from exc

        if not resolved.allow_dev_identity_headers:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Development identity headers are disabled",
            )
        try:
            clearance = DataClassification.parse(x_clearance or resolved.default_clearance)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid X-Clearance value") from exc
        return IdentityContext(
            user_id=(x_user_id or "local-user")[:256],
            tenant_id=(x_tenant_id or "public")[:128],
            roles=x_roles or "",
            departments=x_departments or "",
            clearance=clearance,
            authorization_version=(x_authz_version or "1")[:128],
            claims={"request_id": request.state.request_id, "authentication_mode": "dev"},
        )

    def verify_admin_token(
        x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
    ) -> None:
        expected = resolved.admin_token.get_secret_value() if resolved.admin_token else None
        if not expected or not x_admin_token or not secrets.compare_digest(expected, x_admin_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid admin token",
            )

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    async def ready(c: Container = Depends(container)) -> dict[str, Any]:
        failures: list[str] = []
        if not c.index_manager.is_ready():
            failures.append("rag_index")
        if not c.memory_service.ping():
            failures.append("memory_store")
        if not c.trace_service.ping():
            failures.append("trace_store")
        if not c.audit_service.ping():
            failures.append("audit_store")
        if failures:
            raise HTTPException(
                status_code=503,
                detail={"status": "not_ready", "failed_dependencies": failures},
            )
        return {
            "status": "ready",
            "llm_model": c.settings.nvidia_llm_model,
            "llm_provider_context_limit_tokens": c.settings.provider_context_limit(
                c.settings.nvidia_llm_model
            ),
            "llm_effective_context_window_tokens": c.settings.effective_llm_context_window(
                model=c.settings.nvidia_llm_model,
                max_tokens=c.settings.nvidia_max_tokens,
            ),
            "llm_context_safety_tokens": c.settings.nvidia_context_safety_tokens,
            "llm_max_output_tokens": c.settings.nvidia_max_tokens,
            "embedding_model": c.settings.nvidia_embedding_model,
            "agent_mode": c.settings.agent_mode,
            "auth_mode": c.settings.auth_mode,
            "policy_version": c.policy_engine.policy_version,
            "document_registry_backend": c.settings.document_registry_backend,
            "operational_data_backend": c.settings.operational_data_backend,
            "index_version": c.index_manager.version(),
            "prompt_version": PROMPT_VERSION,
            "session_concurrency_policy": c.settings.session_concurrency_policy,
            "max_concurrent_requests": c.settings.agent_max_concurrent_requests,
            "citation_mode": c.settings.citation_validation_mode,
            "retrieval_architecture": (
                "deterministic-router-adaptive-multi-query-hybrid-rrf-"
                "rerank-evidence-gate"
            ),
            "memory_backend": c.settings.memory_backend,
            "trace_backend": c.settings.trace_backend,
            "audit_backend": c.settings.audit_backend,
            "conversation_context_mode": c.settings.conversation_context_mode,
        }

    @app.post("/v1/chat", response_model=ChatResponse | PublicChatResponse)
    async def chat(
        payload: ChatRequest,
        request: Request,
        response: Response,
        identity: IdentityContext = Depends(resolve_identity),
        x_debug_trace: Annotated[str | None, Header(alias="X-Debug-Trace")] = None,
        c: Container = Depends(container),
    ) -> ChatResponse | PublicChatResponse | JSONResponse:
        session_id = payload.session_id or str(uuid.uuid4())
        try:
            result = await c.agent_service.chat(
                payload.query,
                session_id,
                identity=identity,
                purpose=payload.purpose,
                answer_mode=payload.answer_mode,  # type: ignore[arg-type]
                request_id=request.state.request_id,
                force_retrieval=payload.force_retrieval,
            )
        except TenantBudgetExceededError as exc:
            return _error_response(
                request=request,
                status_code=429,
                error_code="TENANT_BUDGET_EXCEEDED",
                detail=str(exc),
                retry_after_seconds=exc.retry_after_seconds,
                extra={"tenant_id": exc.tenant_id, "reason": exc.reason},
            )
        except CapacityWaitTimeoutError as exc:
            return _error_response(
                request=request,
                status_code=429,
                error_code="CAPACITY_WAIT_TIMEOUT",
                detail=str(exc),
                retry_after_seconds=exc.retry_after_seconds,
                extra={"latency_breakdown": {"capacity_wait_ms": exc.waited_ms}},
            )
        except SessionBusyError as exc:
            return _error_response(
                request=request,
                status_code=409,
                error_code="SESSION_BUSY",
                detail=str(exc),
                retry_after_seconds=exc.retry_after_seconds,
                extra={"session_id": exc.session_id},
            )
        except SessionWaitTimeoutError as exc:
            return _error_response(
                request=request,
                status_code=409,
                error_code="SESSION_WAIT_TIMEOUT",
                detail=str(exc),
                retry_after_seconds=exc.retry_after_seconds,
                extra={
                    "session_id": exc.session_id,
                    "latency_breakdown": {"session_wait_ms": exc.waited_ms},
                },
            )
        except AgentExecutionTimeoutError as exc:
            return _error_response(
                request=request,
                status_code=504,
                error_code="AGENT_EXECUTION_TIMEOUT",
                detail=str(exc),
                extra={
                    "timeout_seconds": exc.timeout_seconds,
                    "latency_breakdown": exc.latency_breakdown.model_dump(mode="json"),
                },
            )
        except ProviderUnavailableError as exc:
            return _error_response(
                request=request,
                status_code=503,
                error_code=exc.error_code,
                detail=exc.public_message,
                retry_after_seconds=exc.retry_after_seconds,
                extra={"provider_trace": exc.provider_trace.model_dump(mode="json")},
            )
        except (KnownScopeMemoryOverflowError, MemoryPromptOverflowError) as exc:
            return _error_response(
                request=request,
                status_code=503,
                error_code="MEMORY_GOVERNANCE_CAPACITY_EXCEEDED",
                detail=str(exc),
            )
        except MemoryPersistenceError as exc:
            return _error_response(
                request=request,
                status_code=503,
                error_code="MEMORY_PERSISTENCE_UNAVAILABLE",
                detail=str(exc),
            )
        except AgentBudgetExceeded as exc:
            return _error_response(
                request=request,
                status_code=503,
                error_code="AGENT_EXECUTION_BUDGET_EXCEEDED",
                detail=str(exc),
                extra={
                    "retryable": False,
                    "stage": "tool_orchestration",
                    "tool": exc.tool,
                    "allowed_calls": exc.allowed_calls,
                    "attempted_calls": exc.attempted_calls,
                    "budget_scope": exc.budget_scope,
                },
            )
        except ProvenanceValidationError as exc:
            return _error_response(
                request=request,
                status_code=502,
                error_code="PROVENANCE_VALIDATION_FAILED",
                detail=(
                    "The analytical answer was rejected because a derived metric did not pass "
                    "application-owned provenance validation."
                ),
                extra={"provenance_audit": exc.audit.model_dump(mode="json")},
            )
        except AnswerCompletenessError as exc:
            return _error_response(
                request=request,
                status_code=502,
                error_code="ANSWER_VALIDATION_FAILED",
                detail=(
                    "The analytical answer was rejected because required business content "
                    "was missing after validation."
                ),
                extra={"answer_completeness": exc.audit.model_dump(mode="json")},
            )
        except CitationValidationError as exc:
            return _error_response(
                request=request,
                status_code=422,
                error_code="CITATION_VALIDATION_FAILED",
                detail=(
                    "The answer could not be returned because its citations were not "
                    "verifiable."
                ),
                extra={"citation_audit": exc.audit.model_dump(mode="json")},
            )
        except OutputPolicyViolation as exc:
            return _error_response(
                request=request,
                status_code=422,
                error_code="OUTPUT_POLICY_BLOCKED",
                detail=str(exc),
            )
        except Exception as exc:
            provider_error = classify_provider_error(exc)
            if provider_error.error_code == "NVIDIA_CONTEXT_LENGTH_EXCEEDED":
                return _error_response(
                    request=request,
                    status_code=503,
                    error_code=provider_error.error_code,
                    detail=provider_error.public_message,
                    extra={
                        "retryable": False,
                        "stage": "provider_context_assembly",
                    },
                )
            if provider_error.transient:
                return _error_response(
                    request=request,
                    status_code=503,
                    error_code=provider_error.error_code,
                    detail=provider_error.public_message,
                    retry_after_seconds=provider_error.retry_after_seconds,
                )
            return _error_response(
                request=request,
                status_code=502,
                error_code=provider_error.error_code,
                detail=provider_error.public_message,
            )

        response.headers["X-Agent-Outcome"] = result.request_outcome
        debug_requested = str(x_debug_trace or "").strip().casefold() in {"1", "true", "yes"}
        if not _debug_trace_allowed(
            identity=identity, requested=debug_requested, settings=c.settings
        ):
            return _public_chat_response(result)
        return ChatResponse(
            answer=result.answer,
            session_id=result.session_id,
            request_outcome=result.request_outcome,
            tools=result.tools,
            tool_call_count=result.tool_call_count,
            latency_ms=result.latency_ms,
            latency_breakdown=result.latency_breakdown,
            safety_signals=result.safety_signals,
            safety_audit=result.safety_audit,
            memory_hit=result.memory_hit,
            response_cache_hit=result.response_cache_hit,
            cache_admitted=result.cache_admitted,
            evidence_origin=result.evidence_origin,
            sources=result.sources,
            citation_audit=result.citation_audit,
            answer_completeness=result.answer_completeness,
            provenance=result.provenance,
            provenance_audit=result.provenance_audit,
            policy_audit=result.policy_audit,
            tool_trace=result.tool_trace,
            provider_trace=result.provider_trace,
            memory_audit=result.memory_audit,
            retrieval_traces=result.retrieval_traces,
            run_id=result.run_id,
            index_version=result.index_version,
            prompt_version=result.prompt_version,
        )


    @app.post("/v1/memory/promote", response_model=MemoryWriteResult)
    async def promote_memory(
        payload: MemoryPromotionRequest,
        identity: IdentityContext = Depends(resolve_identity),
        c: Container = Depends(container),
    ) -> MemoryWriteResult:
        for candidate in payload.candidates:
            if not candidate.source_run_id:
                continue
            source_trace = c.trace_service.get(candidate.source_run_id, identity=identity)
            if source_trace is None or source_trace.user_id != identity.user_id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "source_run_id must identify a trace owned by the current "
                        "user and tenant"
                    ),
                )
        try:
            result = c.memory_service.promote(payload.candidates, identity=identity)
        except MemoryPersistenceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        for candidate, decision in zip(payload.candidates, result.decisions, strict=True):
            MEMORY_WRITE_DECISIONS.labels(
                memory_type=candidate.memory_type.value,
                accepted=str(decision.accepted).lower(),
                status=decision.status.value,
            ).inc()
        await c.agent_service.clear_cache()
        return result

    @app.post("/v1/memory/{memory_id}/approve")
    async def approve_memory(
        memory_id: str,
        _: None = Depends(verify_admin_token),
        identity: IdentityContext = Depends(resolve_identity),
        c: Container = Depends(container),
    ) -> dict[str, bool]:
        require_any_role(identity, {"memory-admin"})
        try:
            approved = c.memory_service.approve(memory_id, identity=identity)
        except MemoryPersistenceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if approved:
            await c.agent_service.clear_cache()
        return {"approved": approved}

    @app.delete("/v1/memory/{memory_id}")
    async def forget_memory(
        memory_id: str,
        identity: IdentityContext = Depends(resolve_identity),
        c: Container = Depends(container),
    ) -> dict[str, bool]:
        try:
            deleted = c.memory_service.forget(memory_id, identity=identity)
        except MemoryPersistenceError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if deleted:
            await c.agent_service.clear_cache()
        return {"deleted": deleted}

    @app.get("/v1/traces/{run_id}")
    async def get_trace(
        run_id: str,
        _: None = Depends(verify_admin_token),
        identity: IdentityContext = Depends(resolve_identity),
        c: Container = Depends(container),
    ) -> dict[str, Any]:
        require_any_role(identity, {"platform-admin", "security-admin", "trace-admin"})
        trace = c.trace_service.get(run_id, identity=identity)
        if trace is None:
            raise HTTPException(status_code=404, detail="Run trace not found")
        return trace.model_dump(mode="json")

    @app.post("/v1/ingest")
    async def ingest(
        payload: IngestRequest,
        _: None = Depends(verify_admin_token),
        identity: IdentityContext = Depends(resolve_identity),
        c: Container = Depends(container),
    ) -> dict[str, Any]:
        require_any_role(identity, {"ingest-admin", "platform-admin"})
        result = c.index_manager.ingest(recreate=payload.recreate)
        await c.agent_service.clear_cache()
        result["restart_required"] = True
        result["message"] = (
            "Indexes were rebuilt from authoritative document policy metadata and cached answers "
            "were cleared. Restart the application so agent tools bind to the new retrievers."
        )
        return result

    @app.post("/v1/cache/clear")
    async def clear_cache(
        _: None = Depends(verify_admin_token),
        identity: IdentityContext = Depends(resolve_identity),
        c: Container = Depends(container),
    ) -> dict[str, str]:
        require_any_role(identity, {"platform-admin"})
        await c.agent_service.clear_cache()
        return {"status": "cleared"}

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
