from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nvidia_agentic_rag.agents import AgentService, build_agent
from nvidia_agentic_rag.audit import (
    InMemoryAuditService,
    JsonlAuditService,
    PostgresAuditService,
)
from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.context import SecureContextBroker
from nvidia_agentic_rag.conversation import BoundedConversationStore
from nvidia_agentic_rag.data import (
    build_analytics_repository,
    build_document_registry,
    build_order_repository,
)
from nvidia_agentic_rag.gateway import ModelGateway
from nvidia_agentic_rag.identity import JWTAuthenticator
from nvidia_agentic_rag.memory import build_memory_service
from nvidia_agentic_rag.nvidia import NvidiaNIMEmbedding, build_nvidia_fast_llm, build_nvidia_llm
from nvidia_agentic_rag.policy import PolicyEngine
from nvidia_agentic_rag.rag import CorpusIndexManager, CorpusSpec, MultiCorpusIndexManager
from nvidia_agentic_rag.security import DataMasker, OutputPolicy
from nvidia_agentic_rag.tools import (
    SecureAnalyticsTools,
    SecureOperationalTools,
    build_tools,
    define_term,
    safe_calculate,
)
from nvidia_agentic_rag.tracing import build_trace_service


@dataclass
class Container:
    settings: Settings
    llm: Any
    embedding: Any
    index_manager: MultiCorpusIndexManager
    agent_service: AgentService
    authenticator: JWTAuthenticator
    policy_engine: PolicyEngine
    context_broker: SecureContextBroker
    audit_service: Any
    memory_service: Any
    trace_service: Any


def _build_enterprise_components(settings: Settings) -> tuple[Any, ...]:
    document_registry = build_document_registry(settings)
    order_repository = build_order_repository(settings)
    policy_engine = PolicyEngine(
        policy_version=settings.enterprise_policy_version,
        allowed_purposes=settings.allowed_purposes,
    )
    masker = DataMasker(
        mode=settings.context_masking_mode,
        salt=settings.masking_salt_value(),
    )
    context_broker = SecureContextBroker(policy_engine=policy_engine, masker=masker)
    output_policy = OutputPolicy(mode=settings.output_dlp_mode, masker=masker)
    if settings.audit_backend == "memory":
        audit_service = InMemoryAuditService()
    elif settings.audit_backend == "jsonl":
        audit_service = JsonlAuditService(settings.audit_log_path)
    else:
        audit_service = PostgresAuditService(settings.database_url)
    operational_tools = SecureOperationalTools(
        order_repository=order_repository,
        policy_engine=policy_engine,
        masker=masker,
    )
    analytics_repository = build_analytics_repository(settings)
    analytics_tools = (
        SecureAnalyticsTools(
            analytics_repository=analytics_repository,
            policy_engine=policy_engine,
            masker=masker,
            customer_table=settings.delta_gold_customer_summary_table,
            book_table=settings.delta_gold_book_sales_table,
            max_rows=settings.analytics_max_rows,
        )
        if analytics_repository is not None
        else None
    )
    return (
        document_registry,
        policy_engine,
        context_broker,
        output_policy,
        audit_service,
        operational_tools,
        analytics_tools,
    )


def _build_index_manager(
    settings: Settings,
    llm: Any,
    embedding: Any,
    *,
    document_registry: Any,
    context_broker: SecureContextBroker,
) -> MultiCorpusIndexManager:
    common = {
        "document_registry": document_registry,
        "context_broker": context_broker,
    }
    course = CorpusIndexManager(
        settings,
        llm,
        embedding,
        CorpusSpec(
            name="agentic-rag-course",
            source_type="course",
            data_dir=settings.course_data_dir,
            persist_name="course_index",
            top_k=settings.course_rag_top_k,
            min_score=settings.course_rag_min_score,
            candidate_multiplier=settings.retrieval_candidate_multiplier,
            tool_name="agentic_rag_course_tool",
            tool_description=(
                "Retrieves only security-authorized evidence from the Agentic RAG course. Use for "
                "Basic RAG versus Agentic RAG, brain/tools/planner/memory, ReAct, self-correction, "
                "and LlamaIndex implementation patterns."
            ),
        ),
        **common,
    )
    papers = CorpusIndexManager(
        settings,
        llm,
        embedding,
        CorpusSpec(
            name="research-papers",
            source_type="paper",
            data_dir=settings.papers_data_dir,
            persist_name="papers_index",
            top_k=settings.papers_rag_top_k,
            min_score=settings.papers_rag_min_score,
            candidate_multiplier=settings.retrieval_candidate_multiplier,
            tool_name="research_paper_rag_tool",
            tool_description=(
                "Retrieves only security-authorized evidence from indexed research papers about "
                "eRAG, retrieval evaluation, query-complexity levels, Self-RAG, IRCoT, and related "
                "published findings."
            ),
        ),
        **common,
    )
    return MultiCorpusIndexManager([course, papers])


def _build_nvidia_clients(settings: Settings) -> tuple[Any, Any]:
    llm = build_nvidia_llm(settings)
    embedding = NvidiaNIMEmbedding(
        model_name=settings.nvidia_embedding_model,
        api_base=settings.nvidia_base_url,
        api_key=settings.api_key_value(),
        timeout_seconds=settings.nvidia_timeout_seconds,
        max_retries=settings.nvidia_embedding_max_retries,
        embed_batch_size=settings.nvidia_embedding_batch_size,
        max_input_tokens=settings.nvidia_embedding_max_input_tokens,
        token_safety_margin=settings.nvidia_embedding_token_safety_margin,
        truncate=settings.nvidia_embedding_truncate,
    )
    return llm, embedding


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    llm, embedding = _build_nvidia_clients(settings)
    (
        document_registry,
        policy_engine,
        context_broker,
        output_policy,
        audit_service,
        operational_tools,
        analytics_tools,
    ) = _build_enterprise_components(settings)
    index_manager = _build_index_manager(
        settings,
        llm,
        embedding,
        document_registry=document_registry,
        context_broker=context_broker,
    )
    if settings.auto_ingest and not index_manager.is_ready():
        index_manager.ingest(recreate=True)
    rag_tools = index_manager.build_tools()
    direct_tools = index_manager.build_direct_retrieval_functions()
    direct_tools.update(
        {
            "safe_calculator_tool": safe_calculate,
            "definition_tool": define_term,
        }
    )
    if analytics_tools is not None:
        direct_tools.update(
            {
                "analytics_query_tool": analytics_tools.analytics_query,
                "compare_customer_spending_to_top_book_tool": (
                    analytics_tools.compare_customer_spending_to_top_book
                ),
            }
        )
    tools = build_tools(
        llm,
        rag_tools,
        secure_operational_tools=operational_tools,
        secure_analytics_tools=analytics_tools,
    )
    agent = build_agent(settings, llm, tools)
    fast_llm = build_nvidia_fast_llm(settings)
    model_gateway = ModelGateway(
        complex_llm=llm,
        fast_llm=fast_llm,
        routing_enabled=settings.model_tier_routing_enabled,
        degrade_to_fast=settings.gateway_degrade_to_fast,
        fast_is_distinct_backend=bool(
            settings.nvidia_fast_llm_model
            and settings.nvidia_fast_llm_model != settings.nvidia_llm_model
        ),
    )
    memory_service = build_memory_service(settings)
    trace_service = build_trace_service(settings)
    conversation_store = BoundedConversationStore(
        recent_turns=settings.conversation_recent_turns,
        max_chars=settings.conversation_max_chars,
    )
    return Container(
        settings=settings,
        llm=llm,
        embedding=embedding,
        index_manager=index_manager,
        agent_service=AgentService(
            settings,
            agent,
            index_version_provider=index_manager.version,
            llm=llm,
            direct_tools=direct_tools,
            policy_engine=policy_engine,
            output_policy=output_policy,
            audit_service=audit_service,
            memory_service=memory_service,
            trace_service=trace_service,
            conversation_store=conversation_store,
            model_gateway=model_gateway,
            analytics_version_provider=(
                lambda tenant_id: analytics_tools.analytics_repository.version_fingerprint(
                    tenant_id=tenant_id
                )
                if analytics_tools is not None
                else None
            ),
        ),
        authenticator=JWTAuthenticator(settings),
        policy_engine=policy_engine,
        context_broker=context_broker,
        audit_service=audit_service,
        memory_service=memory_service,
        trace_service=trace_service,
    )


def build_index_manager_for_ingest(settings: Settings) -> MultiCorpusIndexManager:
    llm, embedding = _build_nvidia_clients(settings)
    document_registry, _, context_broker, _, _, _, _ = _build_enterprise_components(settings)
    return _build_index_manager(
        settings,
        llm,
        embedding,
        document_registry=document_registry,
        context_broker=context_broker,
    )
