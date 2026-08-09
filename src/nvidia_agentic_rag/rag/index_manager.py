from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.context import SecureContextBroker
from nvidia_agentic_rag.data import DocumentRegistry
from nvidia_agentic_rag.identity import get_request_security_context
from nvidia_agentic_rag.metrics import (
    INDIRECT_INJECTION_SIGNALS,
    POLICY_DECISIONS,
    RETRIEVAL_DENIED_CANDIDATES,
    RETRIEVAL_EXECUTIONS,
    RETRIEVAL_PREFILTERED_DENIED,
    RETRIEVAL_SCORE,
    RETRIEVAL_SOURCES,
)
from nvidia_agentic_rag.query import GuardedMultiQueryTransformer, should_expand_query
from nvidia_agentic_rag.rag.provenance import (
    deterministic_citation_id,
    deterministic_node_id,
    extract_section_title,
    filter_nodes_by_score,
    normalize_whitespace,
)
from nvidia_agentic_rag.retrieval import (
    BM25Index,
    DeterministicReranker,
    RetrievalExecutionTrace,
    RetrievalQualityEvaluator,
    SecureRetrievalCache,
    extract_index_nodes,
    reciprocal_rank_fusion,
    to_node_scores,
)
from nvidia_agentic_rag.retrieval.hybrid import (
    diversify_candidates_by_facets,
    extract_requested_facets,
    facet_match_score,
    node_key,
)
from nvidia_agentic_rag.safety import inspect_untrusted_content
from nvidia_agentic_rag.schemas import SourceReference

logger = logging.getLogger(__name__)

INDEX_SCHEMA_VERSION = "enterprise-secure-agentic-index-v4"
SECTION_PARSER_VERSION = "section-parser-v2"
NODE_ID_VERSION = "deterministic-node-id-v1"
SECURITY_METADATA_VERSION = "document-policy-metadata-v1"

COURSE_TITLES = {
    "00": "From RAG to Agentic RAG",
    "01": "The Anatomy of an Agent",
    "02": "Agentic Reasoning Strategies: From ReAct to Multi-Agent Systems",
    "04": "Basic RAG vs. Agentic RAG Implementation with LlamaIndex",
}


@dataclass(frozen=True)
class CorpusSpec:
    name: str
    source_type: str
    data_dir: Path
    persist_name: str
    top_k: int
    min_score: float
    candidate_multiplier: int
    tool_name: str
    tool_description: str


class CorpusIndexManager:
    """Persisted derived context index for one coherent corpus.

    The document registry remains authoritative for tenant, classification, ACL,
    purpose, lifecycle, and source version. The vector index is rebuildable derived data.
    """

    def __init__(
        self,
        settings: Settings,
        llm: Any,
        embed_model: Any,
        spec: CorpusSpec,
        *,
        document_registry: DocumentRegistry,
        context_broker: SecureContextBroker,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.embed_model = embed_model
        self.spec = spec
        self.document_registry = document_registry
        self.context_broker = context_broker
        self._index: Any | None = None
        self._retrieval_fn: Any | None = None
        self._retrieval_cache = SecureRetrievalCache(
            ttl_seconds=settings.retrieval_cache_ttl_seconds,
            max_entries=settings.retrieval_cache_max_entries,
        )

    @property
    def persist_dir(self) -> Path:
        return self.settings.storage_dir / self.spec.persist_name

    @property
    def manifest_path(self) -> Path:
        return self.persist_dir / "manifest.json"

    def effective_chunking(self) -> tuple[int, int]:
        safe_chunk_size = max(
            64,
            self.settings.nvidia_embedding_max_input_tokens
            - self.settings.nvidia_embedding_token_safety_margin,
        )
        effective_chunk_size = min(self.settings.rag_chunk_size, safe_chunk_size)
        effective_chunk_overlap = min(
            self.settings.rag_chunk_overlap,
            max(0, effective_chunk_size // 6),
        )
        return effective_chunk_size, effective_chunk_overlap

    def _files(self) -> list[Path]:
        if not self.spec.data_dir.exists():
            return []
        return sorted(path for path in self.spec.data_dir.rglob("*") if path.is_file())

    def _fingerprint(self) -> str:
        chunk_size, chunk_overlap = self.effective_chunking()
        digest = hashlib.sha256()
        for version in (
            INDEX_SCHEMA_VERSION,
            SECTION_PARSER_VERSION,
            NODE_ID_VERSION,
            SECURITY_METADATA_VERSION,
        ):
            digest.update(version.encode())
        digest.update(self.spec.name.encode())
        digest.update(self.settings.nvidia_embedding_model.encode())
        digest.update(f"{chunk_size}:{chunk_overlap}".encode())
        digest.update(self.document_registry.fingerprint().encode())
        for path in self._files():
            digest.update(str(path.relative_to(self.spec.data_dir)).encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def _runtime_signature(self) -> str:
        payload = (
            f"{self.spec.top_k}:{self.spec.min_score}:"
            f"{self.spec.candidate_multiplier}:{self.settings.indirect_prompt_guard_mode}:"
            f"{self.settings.enterprise_policy_version}:"
            f"{self.settings.context_masking_mode}"
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def is_ready(self) -> bool:
        if not (self.persist_dir / "docstore.json").exists() or not self.manifest_path.exists():
            return False
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return (
            manifest.get("schema_version") == INDEX_SCHEMA_VERSION
            and manifest.get("fingerprint") == self._fingerprint()
        )

    def _relative_path(self, metadata: dict[str, Any], file_name: str) -> str:
        raw_path = Path(str(metadata.get("file_path", file_name)))
        try:
            return str(raw_path.resolve().relative_to(self.spec.data_dir.resolve())).replace(
                "\\", "/"
            )
        except (OSError, ValueError):
            return raw_path.name

    def _prepare_documents(self, documents: list[Any]) -> None:
        missing_security_records: list[str] = []
        for document in documents:
            metadata = dict(document.metadata or {})
            file_name = str(metadata.get("file_name") or Path(str(document.id_)).name)
            stem = Path(file_name).stem
            relative_path = self._relative_path(metadata, file_name)
            security_record = self.document_registry.get(self.spec.name, relative_path)
            if security_record is None:
                if self.settings.require_document_security_metadata:
                    missing_security_records.append(relative_path)
                    continue
                raise ValueError(
                    "Disabling document security metadata is not supported by the enterprise "
                    "reference runtime"
                )

            source_path = self.spec.data_dir / relative_path
            content_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            if security_record.content_hash and security_record.content_hash != content_hash:
                raise ValueError(
                    f"Content hash mismatch for {self.spec.name}/{relative_path}; "
                    "the registry must be updated before ingestion"
                )

            metadata.update(
                {
                    "corpus": self.spec.name,
                    "source_type": self.spec.source_type,
                    "file_name": file_name,
                    "relative_path": relative_path,
                    **security_record.model_copy(update={"content_hash": content_hash}).metadata(),
                }
            )
            page = metadata.get("page_label") or metadata.get("page_number")
            if page is not None:
                metadata["page"] = page
            if self.spec.source_type == "course":
                metadata["lesson_title"] = COURSE_TITLES.get(stem, stem)
            document.metadata = metadata

        if missing_security_records:
            missing = ", ".join(sorted(missing_security_records))
            raise ValueError(
                f"Security metadata is required before publishing documents: {missing}"
            )

    def _build_nodes(self, documents: list[Any], splitter: Any) -> list[Any]:
        nodes = splitter.get_nodes_from_documents(documents, show_progress=True)
        per_file_index: dict[str, int] = {}
        current_section: dict[str, str] = {}

        for node in nodes:
            metadata = dict(node.metadata or {})
            file_name = str(metadata.get("file_name", "unknown"))
            relative_path = str(metadata.get("relative_path", file_name))
            chunk_index = per_file_index.get(relative_path, 0)
            per_file_index[relative_path] = chunk_index + 1

            text = node.get_content()
            section = extract_section_title(text)
            if section:
                current_section[relative_path] = section
            elif relative_path in current_section:
                section = current_section[relative_path]

            page = metadata.get("page") or metadata.get("page_label") or metadata.get(
                "page_number"
            )
            metadata["chunk_index"] = chunk_index
            if page is not None:
                metadata["page"] = page
            if section:
                metadata["section"] = section

            node.metadata = metadata
            node.id_ = deterministic_node_id(
                corpus=self.spec.name,
                relative_path=relative_path,
                chunk_index=chunk_index,
                text=text,
            )
        return nodes

    def ingest(self, *, recreate: bool = False) -> dict[str, int | str]:
        from llama_index.core import SimpleDirectoryReader, VectorStoreIndex
        from llama_index.core.node_parser import SentenceSplitter

        if not self.spec.data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {self.spec.data_dir}")

        documents = SimpleDirectoryReader(
            input_dir=str(self.spec.data_dir),
            recursive=True,
            filename_as_id=True,
        ).load_data()
        if not documents:
            raise RuntimeError(f"No readable documents found in {self.spec.data_dir}")
        self._prepare_documents(documents)

        effective_chunk_size, effective_chunk_overlap = self.effective_chunking()
        splitter = SentenceSplitter(
            chunk_size=effective_chunk_size,
            chunk_overlap=effective_chunk_overlap,
        )
        nodes = self._build_nodes(documents, splitter)

        temporary_dir = self.persist_dir.with_name(
            f"{self.persist_dir.name}.tmp-{uuid.uuid4().hex[:8]}"
        )
        backup_dir = self.persist_dir.with_name(f"{self.persist_dir.name}.backup")
        shutil.rmtree(temporary_dir, ignore_errors=True)
        temporary_dir.mkdir(parents=True, exist_ok=True)

        try:
            index = VectorStoreIndex(nodes, embed_model=self.embed_model, show_progress=True)
            index.storage_context.persist(persist_dir=str(temporary_dir))
            manifest = {
                "schema_version": INDEX_SCHEMA_VERSION,
                "corpus": self.spec.name,
                "fingerprint": self._fingerprint(),
                "runtime_signature": self._runtime_signature(),
                "embedding_model": self.settings.nvidia_embedding_model,
                "chunk_size": effective_chunk_size,
                "chunk_overlap": effective_chunk_overlap,
                "documents": len(documents),
                "nodes": len(nodes),
                "created_at_epoch": int(time.time()),
                "document_registry_fingerprint": self.document_registry.fingerprint(),
                "policy_version": self.settings.enterprise_policy_version,
                "files": [str(path.relative_to(self.spec.data_dir)) for path in self._files()],
            }
            (temporary_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )

            shutil.rmtree(backup_dir, ignore_errors=True)
            if self.persist_dir.exists():
                self.persist_dir.rename(backup_dir)
            temporary_dir.rename(self.persist_dir)
            shutil.rmtree(backup_dir, ignore_errors=True)
            self._index = index
        except Exception:
            shutil.rmtree(temporary_dir, ignore_errors=True)
            if backup_dir.exists() and not self.persist_dir.exists():
                backup_dir.rename(self.persist_dir)
            raise

        logger.info(
            "corpus_ingested",
            extra={
                "corpus": self.spec.name,
                "documents": len(documents),
                "nodes": len(nodes),
                "storage": str(self.persist_dir),
                "policy_version": self.settings.enterprise_policy_version,
            },
        )
        return {
            "corpus": self.spec.name,
            "documents": len(documents),
            "nodes": len(nodes),
            "storage": str(self.persist_dir),
            "chunk_size": effective_chunk_size,
            "chunk_overlap": effective_chunk_overlap,
            "policy_version": self.settings.enterprise_policy_version,
        }

    def load(self) -> Any:
        if self._index is not None:
            return self._index
        if not self.is_ready():
            raise RuntimeError(
                f"{self.spec.name} index is missing or stale. "
                "Run `agentic-rag ingest --recreate`."
            )
        from llama_index.core import StorageContext, load_index_from_storage

        storage_context = StorageContext.from_defaults(persist_dir=str(self.persist_dir))
        self._index = load_index_from_storage(storage_context, embed_model=self.embed_model)
        return self._index

    def build_retrieval_function(self) -> Any:
        if self._retrieval_fn is not None:
            return self._retrieval_fn

        candidate_k = max(self.spec.top_k, self.spec.top_k * self.spec.candidate_multiplier)
        index = self.load()
        retriever = index.as_retriever(similarity_top_k=candidate_k)
        lexical_index = BM25Index(extract_index_nodes(index))
        transformer = GuardedMultiQueryTransformer(
            enabled=True,
            max_variants=self.settings.multi_query_max_variants,
        )
        reranker = DeterministicReranker()
        evaluator = RetrievalQualityEvaluator(
            high_score=self.settings.retrieval_quality_high_score,
            standard_score=self.settings.retrieval_quality_standard_score,
            minimum_coverage=self.settings.retrieval_quality_minimum_coverage,
        )

        def retrieve_evidence(query: str) -> str:
            """Retrieve authorized, fused, reranked evidence from one enterprise corpus."""
            query = query.strip()
            if not query:
                raise ValueError("query must not be empty")
            if len(query) > 8000:
                raise ValueError("query is too long for retrieval")

            request_context = get_request_security_context()
            cache_key = (
                request_context.identity.tenant_id,
                request_context.identity.user_id,
                request_context.identity.authorization_hash(),
                request_context.purpose.casefold(),
                request_context.answer_mode,
                " ".join(query.casefold().split()),
                self.version(),
                self.settings.enterprise_policy_version,
            )
            cached_payload = self._retrieval_cache.get(cache_key)
            if cached_payload is not None:
                return cached_payload

            adaptive_multi_query = (
                self.settings.multi_query_enabled and should_expand_query(query)
            )
            plan = (
                transformer.transform(query)
                if adaptive_multi_query
                else GuardedMultiQueryTransformer(enabled=False).transform(query)
            )
            requested_facets = extract_requested_facets(query)

            def finish(payload: dict[str, Any]) -> str:
                text = json.dumps(payload, ensure_ascii=False)
                self._retrieval_cache.put(cache_key, text)
                return text

            rankings: list[tuple[str, list[Any]]] = []
            vector_count = 0
            lexical_count = 0

            def candidate_allowed(node: Any) -> bool:
                decision = self.context_broker.policy_engine.authorize_document(
                    identity=request_context.identity,
                    purpose=request_context.purpose,
                    metadata=dict(getattr(node, "metadata", {}) or {}),
                )
                return decision.allowed

            prefiltered_denied = 0
            for position, variant in enumerate(plan.variants):
                vector_items = filter_nodes_by_score(
                    retriever.retrieve(variant),
                    min_score=self.spec.min_score,
                    limit=candidate_k,
                )
                admitted_items = [
                    item for item in vector_items if candidate_allowed(item.node)
                ]
                prefiltered_denied += len(vector_items) - len(admitted_items)
                vector_ranking = to_node_scores(admitted_items, source="vector")
                vector_count += len(vector_ranking)
                if vector_ranking:
                    rankings.append((f"vector:{position}", vector_ranking))

                if self.settings.hybrid_retrieval_enabled and len(lexical_index):
                    lexical_ranking = lexical_index.search(
                        variant, limit=candidate_k, allowed=candidate_allowed
                    )
                    lexical_count += len(lexical_ranking)
                    if lexical_ranking:
                        rankings.append((f"lexical:{position}", lexical_ranking))

            fused = reciprocal_rank_fusion(
                rankings, rrf_k=self.settings.hybrid_rrf_k, limit=candidate_k
            )
            fallback_chain: list[str] = []
            if self.settings.retrieval_rerank_enabled:
                try:
                    fused = reranker.rerank(query, fused, limit=candidate_k)
                except Exception:  # pragma: no cover - defensive rerank isolation
                    fallback_chain.append("rerank_error_rrf_order")

            source_limit = self.spec.top_k
            if request_context.max_sources_per_corpus is not None:
                source_limit = min(source_limit, request_context.max_sources_per_corpus)
            assessment = evaluator.evaluate(fused, query=query, facets=requested_facets)
            mode = (
                "hybrid"
                if vector_count and lexical_count
                else "vector"
                if vector_count
                else "lexical"
            )
            degraded = mode != "hybrid"

            if (
                (not fused or assessment.relevance == "low")
                and self.settings.retrieval_fallback_enabled
            ):
                fallback_chain.append(mode)
                fallback = lexical_index.like_search(
                    query, limit=candidate_k, allowed=candidate_allowed
                )
                if fallback:
                    fused = reranker.rerank(query, fallback, limit=candidate_k)
                    assessment = evaluator.evaluate(
                        fused, query=query, facets=requested_facets
                    )
                    mode = "like"
                    degraded = True
                    fallback_chain.append("like")

            # Explicit multi-part questions need one more bounded retrieval pass for missing
            # facets. Rescue candidates are injected directly into the candidate pool rather
            # than relying on RRF to keep them in the global top-K. This prevents a dominant
            # topic from crowding out exact evidence for named requirements such as
            # self-correction, multi-agent reasoning, or LangGraph.
            missing_facets = assessment.uncovered_facets
            if requested_facets and missing_facets:
                rescue_candidates: list[Any] = []
                rescue_limit = max(4, source_limit * 2)
                for facet in missing_facets:
                    lexical_rescue = lexical_index.search(
                        facet, limit=rescue_limit, allowed=candidate_allowed
                    )
                    lexical_count += len(lexical_rescue)
                    lexical_supported = [
                        item
                        for item in lexical_rescue
                        if facet_match_score(facet, item) >= 0.5
                    ]
                    rescue_candidates.extend(lexical_supported[:2])

                    # A non-empty lexical result may only share a generic token (for example
                    # "reasoning"). Only skip vector rescue when lexical evidence actually
                    # covers the requested facet.
                    if lexical_supported:
                        continue

                    vector_items = filter_nodes_by_score(
                        retriever.retrieve(facet),
                        min_score=self.spec.min_score,
                        limit=rescue_limit,
                    )
                    admitted_items = [
                        item for item in vector_items if candidate_allowed(item.node)
                    ]
                    prefiltered_denied += len(vector_items) - len(admitted_items)
                    vector_rescue = to_node_scores(admitted_items, source="facet-vector")
                    vector_count += len(vector_rescue)
                    vector_supported = [
                        item
                        for item in vector_rescue
                        if facet_match_score(facet, item) >= 0.5
                    ]
                    rescue_candidates.extend(vector_supported[:2])

                if rescue_candidates:
                    # Merge without truncating rescued evidence first. Rerank the expanded
                    # pool, then reserve facet slots before reducing to candidate_k.
                    merged: dict[str, Any] = {}
                    for item in [*fused, *rescue_candidates]:
                        key = node_key(item.node)
                        previous = merged.get(key)
                        if previous is None or item.score > previous.score:
                            merged[key] = item
                    expanded = list(merged.values())
                    if self.settings.retrieval_rerank_enabled:
                        expanded = reranker.rerank(
                            query, expanded, limit=max(candidate_k, len(expanded))
                        )
                    fused = diversify_candidates_by_facets(
                        expanded, requested_facets, limit=candidate_k
                    )
                    assessment = evaluator.evaluate(
                        fused, query=query, facets=requested_facets
                    )
                    fallback_chain.append("facet_recovery")

            # Reorder the candidate pool so explicit facets receive evidence slots before
            # score-only filling. Authorization still runs afterwards on the normal broker.
            fused = diversify_candidates_by_facets(
                fused, requested_facets, limit=len(fused) or candidate_k
            )
            broker_result = self.context_broker.authorize_candidates(
                candidates=fused, request_context=request_context, limit=source_limit
            )
            authorized_scores = [
                item.node_with_score for item in broker_result.authorized
            ]
            authorized_assessment = evaluator.evaluate(
                authorized_scores, query=query, facets=requested_facets
            )
            trace = RetrievalExecutionTrace(
                strategy=plan.strategy,
                query_variants=plan.variants,
                mode=mode,
                degraded=degraded,
                vector_candidate_count=vector_count,
                lexical_candidate_count=lexical_count,
                fused_candidate_count=len(fused),
                authorized_candidate_count=len(broker_result.authorized),
                denied_candidate_count=broker_result.denied_candidate_count,
                relevance=authorized_assessment.relevance,
                top_score=authorized_assessment.top_score,
                query_coverage=authorized_assessment.query_coverage,
                fallback_chain=tuple(fallback_chain),
                prefiltered_denied_count=prefiltered_denied,
                requested_facet_count=authorized_assessment.requested_facet_count,
                covered_facet_count=authorized_assessment.covered_facet_count,
                facet_coverage=authorized_assessment.facet_coverage,
                uncovered_facet_hashes=tuple(
                    hashlib.sha256(item.casefold().encode("utf-8")).hexdigest()
                    for item in authorized_assessment.uncovered_facets
                ),
            )
            if prefiltered_denied:
                RETRIEVAL_PREFILTERED_DENIED.labels(corpus=self.spec.name).inc(
                    prefiltered_denied
                )
            RETRIEVAL_EXECUTIONS.labels(
                corpus=self.spec.name,
                mode=trace.mode,
                relevance=trace.relevance,
                degraded=str(trace.degraded).lower(),
            ).inc()
            RETRIEVAL_DENIED_CANDIDATES.labels(corpus=self.spec.name).observe(
                broker_result.denied_candidate_count
            )
            POLICY_DECISIONS.labels(
                action="document.read",
                result="allowed" if broker_result.authorized else "insufficient",
            ).inc()

            if (
                request_context.answer_mode == "enterprise_factual"
                and self.settings.retrieval_quality_fail_closed
                and authorized_assessment.relevance in {"low", "none"}
            ):
                return finish(
                    {
                        "status": "insufficient_relevant_context",
                        "query": query,
                        "corpus": self.spec.name,
                        "evidence": (
                            "Authorized candidates were retrieved, but the evidence set did not "
                            "cover enough of the requested factual facets for a grounded answer."
                        ),
                        "sources": [],
                        "safety_signals": [],
                        "retrieval_trace": trace.as_dict(),
                        "policy_audit": {
                            "status": "insufficient_context",
                            "policy_version": broker_result.policy_version,
                            "purpose": request_context.purpose,
                            "tenant_id": request_context.identity.tenant_id,
                            "authorized_source_count": 0,
                            "retrieved_authorized_candidate_count": len(
                                broker_result.authorized
                            ),
                            "denied_candidate_count": (
                                broker_result.denied_candidate_count
                            ),
                            "reason": (
                                "Retrieved authorized evidence did not satisfy the grounded "
                                "retrieval quality/facet coverage requirement."
                            ),
                        },
                    }
                )

            if not broker_result.authorized:
                return finish(
                    {
                        "status": "insufficient_authorized_context",
                        "query": query,
                        "corpus": self.spec.name,
                        "evidence": (
                            "No relevant evidence was both retrievable and authorized for the "
                            "current identity, tenant, clearance, role, department, and purpose."
                        ),
                        "sources": [],
                        "safety_signals": [],
                        "retrieval_trace": trace.as_dict(),
                        "policy_audit": {
                            "status": "insufficient_context",
                            "policy_version": broker_result.policy_version,
                            "purpose": request_context.purpose,
                            "tenant_id": request_context.identity.tenant_id,
                            "authorized_source_count": 0,
                            "retrieved_authorized_candidate_count": 0,
                            "denied_candidate_count": broker_result.denied_candidate_count,
                            "reason": (
                                "No relevant evidence was both retrievable and authorized for "
                                "the current request scope."
                            ),
                        },
                    }
                )

            evidence_rows: list[str] = []
            sources: list[SourceReference] = []
            safety_signals: set[str] = set()
            classifications: set[str] = set()

            for candidate in broker_result.authorized:
                node_with_score = candidate.node_with_score
                node = node_with_score.node
                metadata = dict(node.metadata or {})
                text = normalize_whitespace(candidate.masked_text)
                indirect_guard = inspect_untrusted_content(text)
                for signal in indirect_guard.signals:
                    safety_signals.add(signal)
                    INDIRECT_INJECTION_SIGNALS.labels(
                        corpus=self.spec.name, signal=signal
                    ).inc()
                if indirect_guard.signals and self.settings.indirect_prompt_guard_mode == "block":
                    continue

                source_id = str(node.node_id)
                citation_id = deterministic_citation_id(source_id)
                file_name = str(
                    metadata.get("file_name")
                    or metadata.get("file_path")
                    or source_id
                )
                title = str(
                    metadata.get("lesson_title") or metadata.get("document_title")
                    or metadata.get("title") or file_name
                )
                page = (
                    metadata.get("page")
                    or metadata.get("page_label")
                    or metadata.get("page_number")
                )
                section = metadata.get("section") or metadata.get("section_title")
                chunk_index = metadata.get("chunk_index")
                score_value = round(float(node_with_score.score), 4)
                classification = str(metadata.get("classification", "unknown"))
                classifications.add(classification)
                RETRIEVAL_SCORE.labels(corpus=self.spec.name).observe(score_value)

                source = SourceReference(
                    citation_id=citation_id, source_id=source_id, source_kind="document",
                    corpus=self.spec.name, file_name=file_name, title=title, page=page,
                    section=section, chunk_index=chunk_index, score=score_value, excerpt=text[:500],
                    indirect_injection_signals=list(indirect_guard.signals),
                    tenant_id=str(metadata.get("tenant_id")),
                    document_id=str(metadata.get("document_id")),
                    classification=classification,
                    source_version=int(metadata.get("source_version", 1)),
                    policy_version=str(metadata.get("policy_version")),
                    authorization_decision_id=candidate.decision_id, masked=candidate.masked,
                    retrieved_at=datetime.now(UTC).isoformat(),
                )
                sources.append(source)
                location_parts: list[str] = []
                if page is not None:
                    location_parts.append(f"page {page}")
                if section:
                    location_parts.append(f"section {section}")
                location = f" ({', '.join(location_parts)})" if location_parts else ""
                evidence_rows.append(
                    f"[{citation_id}] Authorized enterprise data; Corpus: {self.spec.name}; "
                    f"Source: {file_name}; Title: {title}{location}; "
                    f"Classification: {classification}; Source version: "
                    f"{metadata.get('source_version')}; Fused relevance: {score_value}\n{text}"
                )

            RETRIEVAL_SOURCES.labels(corpus=self.spec.name).observe(len(sources))
            status = "success" if sources else "blocked_evidence"
            return finish(
                {
                    "status": status,
                    "query": query,
                    "corpus": self.spec.name,
                    "index_version": self.version(),
                    "evidence": "\n\n".join(evidence_rows) if sources else (
                        "Authorized evidence was blocked by content safety policy."
                    ),
                    "sources": [source.model_dump(mode="json") for source in sources],
                    "safety_signals": sorted(safety_signals),
                    "retrieval_trace": trace.as_dict(),
                    "policy_audit": {
                        "status": "allowed" if sources else "insufficient_context",
                        "policy_version": broker_result.policy_version,
                        "purpose": request_context.purpose,
                        "tenant_id": request_context.identity.tenant_id,
                        "authorized_source_count": len(sources),
                        "denied_candidate_count": broker_result.denied_candidate_count,
                        "classifications": sorted(classifications),
                    },
                }
            )

        self._retrieval_fn = retrieve_evidence
        return self._retrieval_fn

    def build_retrieval_tool(self) -> Any:
        from llama_index.core.tools import FunctionTool

        return FunctionTool.from_defaults(
            fn=self.build_retrieval_function(),
            name=self.spec.tool_name,
            description=self.spec.tool_description,
        )

    def version(self) -> str:
        if not self.manifest_path.exists():
            return "missing"
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            fingerprint = str(manifest.get("fingerprint", "unknown"))
        except (OSError, ValueError):
            return "invalid"
        payload = f"{fingerprint}:{self._runtime_signature()}"
        return hashlib.sha256(payload.encode()).hexdigest()


class MultiCorpusIndexManager:
    def __init__(self, managers: list[CorpusIndexManager]) -> None:
        self.managers = managers

    def is_ready(self) -> bool:
        return all(manager.is_ready() for manager in self.managers)

    def ingest(self, *, recreate: bool = False) -> dict[str, Any]:
        return {"corpora": [manager.ingest(recreate=recreate) for manager in self.managers]}

    def build_tools(self) -> list[Any]:
        return [manager.build_retrieval_tool() for manager in self.managers]

    def build_direct_retrieval_functions(self) -> dict[str, Any]:
        return {
            manager.spec.tool_name: manager.build_retrieval_function()
            for manager in self.managers
        }

    def version(self) -> str:
        versions = [f"{manager.spec.name}:{manager.version()}" for manager in self.managers]
        return hashlib.sha256("|".join(sorted(versions)).encode()).hexdigest()
