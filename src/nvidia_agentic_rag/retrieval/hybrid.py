from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal

_TOKEN_RE = re.compile(r"[\w.-]+", re.UNICODE)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "with",
    "their",
    "using",
    "only",
    "indexed",
    "course",
    "documents",
    "document",
    "evidence",
    "factual",
    "section",
    "sections",
    "cite",
    "và",
    "của",
    "là",
    "như",
    "thế",
    "nào",
    "cho",
    "trong",
    "với",
}

RetrievalMode = Literal["hybrid", "vector", "lexical", "like"]
RelevanceTier = Literal["high", "standard", "low", "none"]


_FACET_LIST_ANCHOR_RE = re.compile(
    r"\b(?:cover|include|compare|provide|determine|explain|describe|roles\s+do)\b"
    r"(?P<body>[^.;?]+)",
    re.IGNORECASE,
)
_FACET_SPLIT_RE = re.compile(r"\s*,\s*|\s+(?:and|or)\s+", re.IGNORECASE)
_FACET_CONTROL_RE = re.compile(
    r"\b(?:cite|citation|outside knowledge|do not|only state|supported by|indexed course|"
    r"factual section|factual paragraph)\b",
    re.IGNORECASE,
)
_FACET_TRAILING_RE = re.compile(
    r"\b(?:play|plays|used to|during|based on|supported by|is intended|are intended|"
    r"from user query|before final answer)\b.*$",
    re.IGNORECASE,
)
_FACET_LEADING_RE = re.compile(
    r"^(?:and|or|their|the|a|an|its|each|all|four|three|two|requested|exact|full)\s+",
    re.IGNORECASE,
)


def _clean_facet(value: str) -> str:
    value = value.strip(" \t\n?:;.-")
    value = re.sub(r"^[^:]{0,100}:\s*", "", value) if ":" in value else value
    value = _FACET_TRAILING_RE.sub("", value).strip(" \t\n?:;.-")
    for _ in range(3):
        updated = _FACET_LEADING_RE.sub("", value).strip()
        if updated == value:
            break
        value = updated
    value = re.sub(r"\s+", " ", value)
    if not value or len(value) > 96 or _FACET_CONTROL_RE.search(value):
        return ""
    terms = tokenize(value)
    if not terms or len(terms) > 8:
        return ""
    return value


def extract_requested_facets(query: str, *, max_facets: int = 10) -> tuple[str, ...]:
    """Extract explicit multi-part requirements without asking an LLM.

    The extractor intentionally targets enumerated/named facets only. It is used for
    evidence coverage and completeness telemetry, not semantic interpretation, so it
    prefers precision over recall and ignores control instructions such as citation rules.
    """
    normalized = " ".join(query.strip().split())
    if not normalized or max_facets <= 0:
        return ()

    candidates: list[str] = []
    # Colon lists such as "components: brain, tools, planner, and memory".
    for colon_body in re.findall(r":\s*([^.;?]+)", normalized):
        if "," in colon_body:
            candidates.extend(_FACET_SPLIT_RE.split(colon_body))

    # Explicit instruction lists such as "cover A, B, and C" or "compare A and B".
    for match in _FACET_LIST_ANCHOR_RE.finditer(normalized):
        body = match.group("body").strip()
        if "," in body or re.search(r"\s+(?:and|or)\s+", body, re.IGNORECASE):
            candidates.extend(_FACET_SPLIT_RE.split(body))

    # Named framework/strategy lists are particularly important for retrieval recovery.
    named_terms = re.findall(
        r"\b(?:[A-Z][A-Za-z0-9]+(?:[A-Z][A-Za-z0-9]+)+|ReAct|"
        r"self-correction|plan-and-execute|multi-agent(?:\s+\w+)?)\b",
        normalized,
    )
    if len(named_terms) >= 2:
        candidates.extend(named_terms)

    cleaned: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        facet = _clean_facet(candidate)
        key = facet.casefold()
        if not facet or key in seen:
            continue
        # Avoid treating the two sides of a generic prose clause as facets unless the
        # resulting phrase is short enough to behave like a named requirement.
        if len(tokenize(facet)) > 6:
            continue
        cleaned.append(facet)
        seen.add(key)
        if len(cleaned) >= max_facets:
            break
    return tuple(cleaned)


def _candidate_searchable_text(candidate: NodeScore) -> str:
    node = candidate.node
    text = node.get_content() if hasattr(node, "get_content") else str(node)
    metadata = dict(getattr(node, "metadata", {}) or {})
    return " ".join(
        [
            str(metadata.get("title", "")),
            str(metadata.get("lesson_title", "")),
            str(metadata.get("section", "")),
            str(metadata.get("file_name", "")),
            text,
        ]
    )


def _facet_terms(text: str) -> set[str]:
    """Normalize explicit facet labels for robust PDF/text matching.

    Course PDFs often contain soft/non-ASCII hyphens or line-break artifacts such as
    ``multi- agent`` while user queries contain ``multi-agent``.  Facet matching must
    not depend on those presentation differences.  Keep the normal retrieval tokenizer
    unchanged and use this narrower normalization only for facet coverage/recovery.
    """
    normalized = re.sub(r"[\u00ad\u2010-\u2015]\s*", "-", text.casefold())
    normalized = re.sub(r"[-_.]+", " ", normalized)
    aliases = {
        "reasoning": "reason",
        "reasons": "reason",
        "actions": "act",
        "action": "act",
        "acting": "act",
        "observations": "observation",
        "observed": "observation",
        "observe": "observation",
        "agents": "agent",
        "systems": "system",
        "strategies": "strategy",
    }
    terms: set[str] = set()
    for token in tokenize(normalized):
        canonical = aliases.get(token, token)
        if canonical.endswith("s") and len(canonical) > 4:
            canonical = canonical[:-1]
        terms.add(canonical)
    return terms


def facet_match_score(facet: str, candidate: NodeScore) -> float:
    facet_terms = _facet_terms(facet)
    if not facet_terms:
        return 0.0
    evidence_terms = _facet_terms(_candidate_searchable_text(candidate))
    return len(facet_terms.intersection(evidence_terms)) / len(facet_terms)


def facet_coverage(
    facets: Sequence[str], candidates: Sequence[NodeScore], *, threshold: float = 0.5
) -> tuple[int, float, tuple[str, ...]]:
    if not facets:
        return 0, 0.0, ()
    covered = 0
    missing: list[str] = []
    for facet in facets:
        best = max((facet_match_score(facet, item) for item in candidates), default=0.0)
        if best >= threshold:
            covered += 1
        else:
            missing.append(facet)
    return covered, covered / len(facets), tuple(missing)


def diversify_candidates_by_facets(
    candidates: Sequence[NodeScore], facets: Sequence[str], *, limit: int
) -> list[NodeScore]:
    """Reserve evidence slots for explicit requested facets, then fill by score."""
    if limit <= 0:
        return []
    if not facets:
        return list(candidates[:limit])

    selected: list[NodeScore] = []
    selected_keys: set[str] = set()
    for facet in facets:
        ranked = sorted(
            candidates,
            key=lambda item: (facet_match_score(facet, item), item.score),
            reverse=True,
        )
        if not ranked or facet_match_score(facet, ranked[0]) < 0.5:
            continue
        key = node_key(ranked[0].node)
        if key not in selected_keys:
            selected.append(ranked[0])
            selected_keys.add(key)
        if len(selected) >= limit:
            return selected[:limit]

    for candidate in candidates:
        key = node_key(candidate.node)
        if key in selected_keys:
            continue
        selected.append(candidate)
        selected_keys.add(key)
        if len(selected) >= limit:
            break
    return selected


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(
        token.casefold()
        for token in _TOKEN_RE.findall(text)
        if token.casefold() not in _STOPWORDS and len(token) > 1
    )


def node_key(node: Any) -> str:
    for attribute in ("node_id", "id_"):
        value = getattr(node, attribute, None)
        if value:
            return str(value)
    metadata = dict(getattr(node, "metadata", {}) or {})
    content = node.get_content() if hasattr(node, "get_content") else str(node)
    payload = f"{metadata.get('document_id')}:{metadata.get('chunk_index')}:{content}"
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class NodeScore:
    node: Any
    score: float
    retrieval_sources: tuple[str, ...] = field(default_factory=tuple)
    ranks: dict[str, int] = field(default_factory=dict)
    query_coverage: float = 0.0


@dataclass(frozen=True)
class RetrievalAssessment:
    relevance: RelevanceTier
    top_score: float
    candidate_count: int
    query_coverage: float
    reason: str
    requested_facet_count: int = 0
    covered_facet_count: int = 0
    facet_coverage: float = 0.0
    uncovered_facets: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalExecutionTrace:
    strategy: str
    query_variants: tuple[str, ...]
    mode: RetrievalMode
    degraded: bool
    vector_candidate_count: int
    lexical_candidate_count: int
    fused_candidate_count: int
    authorized_candidate_count: int
    denied_candidate_count: int
    relevance: RelevanceTier
    top_score: float
    query_coverage: float
    fallback_chain: tuple[str, ...] = ()
    prefiltered_denied_count: int = 0
    requested_facet_count: int = 0
    covered_facet_count: int = 0
    facet_coverage: float = 0.0
    uncovered_facet_hashes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "query_variant_count": len(self.query_variants),
            "query_variant_hashes": [
                sha256(item.encode("utf-8")).hexdigest() for item in self.query_variants
            ],
            "mode": self.mode,
            "degraded": self.degraded,
            "vector_candidate_count": self.vector_candidate_count,
            "lexical_candidate_count": self.lexical_candidate_count,
            "fused_candidate_count": self.fused_candidate_count,
            "authorized_candidate_count": self.authorized_candidate_count,
            "denied_candidate_count": self.denied_candidate_count,
            "relevance": self.relevance,
            "top_score": self.top_score,
            "query_coverage": self.query_coverage,
            "fallback_chain": list(self.fallback_chain),
            "prefiltered_denied_count": self.prefiltered_denied_count,
            "requested_facet_count": self.requested_facet_count,
            "covered_facet_count": self.covered_facet_count,
            "facet_coverage": self.facet_coverage,
            "uncovered_facet_hashes": list(self.uncovered_facet_hashes),
        }


class BM25Index:
    """Small in-process lexical index used beside the local LlamaIndex vector store.

    Production deployments can replace it with PostgreSQL FTS/OpenSearch while preserving the
    same result contract and reciprocal-rank-fusion behavior.
    """

    def __init__(self, nodes: Iterable[Any]) -> None:
        self._nodes: dict[str, Any] = {}
        self._terms: dict[str, Counter[str]] = {}
        self._lengths: dict[str, int] = {}
        document_frequency: Counter[str] = Counter()

        for node in nodes:
            key = node_key(node)
            text = node.get_content() if hasattr(node, "get_content") else str(node)
            terms = Counter(tokenize(text))
            if not terms:
                continue
            self._nodes[key] = node
            self._terms[key] = terms
            self._lengths[key] = sum(terms.values())
            document_frequency.update(terms.keys())

        self._document_frequency = document_frequency
        self._average_length = (
            sum(self._lengths.values()) / len(self._lengths) if self._lengths else 1.0
        )

    def __len__(self) -> int:
        return len(self._nodes)

    def search(
        self,
        query: str,
        *,
        limit: int,
        allowed: Callable[[Any], bool] | None = None,
    ) -> list[NodeScore]:
        query_terms = Counter(tokenize(query))
        if not query_terms or limit <= 0:
            return []

        total_docs = max(1, len(self._nodes))
        k1 = 1.5
        b = 0.75
        scored: list[NodeScore] = []
        for key, node in self._nodes.items():
            if allowed is not None and not allowed(node):
                continue
            frequencies = self._terms[key]
            document_length = self._lengths[key]
            score = 0.0
            matched = 0
            for term, query_frequency in query_terms.items():
                term_frequency = frequencies.get(term, 0)
                if term_frequency <= 0:
                    continue
                matched += 1
                doc_frequency = self._document_frequency.get(term, 0)
                inverse_document_frequency = math.log(
                    1.0 + (total_docs - doc_frequency + 0.5) / (doc_frequency + 0.5)
                )
                denominator = term_frequency + k1 * (
                    1.0 - b + b * document_length / self._average_length
                )
                score += (
                    inverse_document_frequency
                    * (term_frequency * (k1 + 1.0) / denominator)
                    * query_frequency
                )
            if score <= 0:
                continue
            coverage = matched / max(1, len(query_terms))
            scored.append(
                NodeScore(
                    node=node,
                    score=score,
                    retrieval_sources=("lexical",),
                    query_coverage=coverage,
                )
            )

        scored.sort(key=lambda item: (item.score, item.query_coverage), reverse=True)
        if not scored:
            return []
        top_score = max(item.score for item in scored) or 1.0
        return [
            NodeScore(
                node=item.node,
                score=min(1.0, item.score / top_score),
                retrieval_sources=item.retrieval_sources,
                query_coverage=item.query_coverage,
            )
            for item in scored[:limit]
        ]

    def like_search(
        self,
        query: str,
        *,
        limit: int,
        allowed: Callable[[Any], bool] | None = None,
    ) -> list[NodeScore]:
        normalized = " ".join(tokenize(query))
        if not normalized:
            return []
        query_terms = set(normalized.split())
        results: list[NodeScore] = []
        for node in self._nodes.values():
            if allowed is not None and not allowed(node):
                continue
            text = node.get_content() if hasattr(node, "get_content") else str(node)
            text_terms = set(tokenize(text))
            overlap = len(query_terms.intersection(text_terms))
            if overlap == 0:
                continue
            coverage = overlap / len(query_terms)
            results.append(
                NodeScore(
                    node=node,
                    score=coverage,
                    retrieval_sources=("like",),
                    query_coverage=coverage,
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]


def to_node_scores(items: Sequence[Any], *, source: str) -> list[NodeScore]:
    result: list[NodeScore] = []
    for item in items:
        node = getattr(item, "node", item)
        raw_score = getattr(item, "score", 0.0)
        score = float(raw_score if raw_score is not None else 0.0)
        result.append(
            NodeScore(
                node=node,
                score=max(-1.0, min(1.0, score)),
                retrieval_sources=(source,),
            )
        )
    return result


def reciprocal_rank_fusion(
    rankings: Sequence[tuple[str, Sequence[NodeScore]]],
    *,
    rrf_k: int = 60,
    limit: int,
) -> list[NodeScore]:
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    fused_scores: defaultdict[str, float] = defaultdict(float)
    nodes: dict[str, Any] = {}
    sources: defaultdict[str, set[str]] = defaultdict(set)
    ranks: defaultdict[str, dict[str, int]] = defaultdict(dict)
    coverage: defaultdict[str, float] = defaultdict(float)

    for ranking_name, ranking in rankings:
        seen: set[str] = set()
        for rank, candidate in enumerate(ranking, start=1):
            key = node_key(candidate.node)
            if key in seen:
                continue
            seen.add(key)
            nodes[key] = candidate.node
            fused_scores[key] += 1.0 / (rrf_k + rank)
            sources[key].update(candidate.retrieval_sources or (ranking_name,))
            ranks[key][ranking_name] = rank
            coverage[key] = max(coverage[key], candidate.query_coverage)

    ordered = sorted(fused_scores, key=fused_scores.get, reverse=True)
    if not ordered:
        return []
    max_score = fused_scores[ordered[0]] or 1.0
    result = [
        NodeScore(
            node=nodes[key],
            score=min(1.0, fused_scores[key] / max_score),
            retrieval_sources=tuple(sorted(sources[key])),
            ranks=ranks[key],
            query_coverage=coverage[key],
        )
        for key in ordered[:limit]
    ]
    return result


class DeterministicReranker:
    """Auditable local reranker; cross-encoder adapters can replace it in production."""

    def rerank(self, query: str, candidates: Sequence[NodeScore], *, limit: int) -> list[NodeScore]:
        query_terms = set(tokenize(query))
        reranked: list[NodeScore] = []
        for candidate in candidates:
            text = (
                candidate.node.get_content()
                if hasattr(candidate.node, "get_content")
                else str(candidate.node)
            )
            document_terms = set(tokenize(text))
            coverage = (
                len(query_terms.intersection(document_terms)) / len(query_terms)
                if query_terms
                else 0.0
            )
            metadata = dict(getattr(candidate.node, "metadata", {}) or {})
            title_text = " ".join(
                str(metadata.get(key, ""))
                for key in ("title", "lesson_title", "section", "file_name")
            )
            title_terms = set(tokenize(title_text))
            title_coverage = (
                len(query_terms.intersection(title_terms)) / len(query_terms)
                if query_terms
                else 0.0
            )
            score = min(
                1.0,
                0.45 * max(0.0, candidate.score)
                + 0.40 * coverage
                + 0.15 * title_coverage,
            )
            reranked.append(
                NodeScore(
                    node=candidate.node,
                    score=score,
                    retrieval_sources=candidate.retrieval_sources,
                    ranks=candidate.ranks,
                    query_coverage=max(candidate.query_coverage, coverage),
                )
            )
        reranked.sort(key=lambda item: (item.score, item.query_coverage), reverse=True)
        return reranked[:limit]


class RetrievalQualityEvaluator:
    def __init__(
        self,
        *,
        high_score: float = 0.72,
        standard_score: float = 0.45,
        minimum_coverage: float = 0.20,
    ) -> None:
        self.high_score = high_score
        self.standard_score = standard_score
        self.minimum_coverage = minimum_coverage

    @staticmethod
    def _aggregate_query_coverage(
        query: str, candidates: Sequence[NodeScore], *, limit: int = 6
    ) -> float:
        """Coverage across the evidence set, not only the best individual chunk.

        Comparative and multi-facet RAG questions are commonly answered by several
        chunks. Requiring one chunk to cover the whole query incorrectly rejects
        valid evidence such as Basic-RAG-vs-Agentic-RAG comparisons.
        """
        query_terms = set(tokenize(query))
        if not query_terms:
            return 0.0
        matched: set[str] = set()
        for candidate in candidates[: max(1, limit)]:
            node = candidate.node
            text = node.get_content() if hasattr(node, "get_content") else str(node)
            metadata = dict(getattr(node, "metadata", {}) or {})
            searchable = f"{metadata.get('title', '')} {metadata.get('section', '')} {text}"
            matched.update(query_terms.intersection(tokenize(searchable)))
        return len(matched) / len(query_terms)

    def evaluate(
        self,
        candidates: Sequence[NodeScore],
        *,
        query: str | None = None,
        facets: Sequence[str] = (),
    ) -> RetrievalAssessment:
        requested_facet_count = len(facets)
        if not candidates:
            return RetrievalAssessment(
                relevance="none",
                top_score=0.0,
                candidate_count=0,
                query_coverage=0.0,
                reason="no candidates survived retrieval and authorization",
                requested_facet_count=requested_facet_count,
                uncovered_facets=tuple(facets),
            )
        # Candidate order may be facet-diversified before authorization, so the first
        # item is not necessarily the highest-scoring item.  Quality must use the true
        # maximum score across the authorized evidence set.
        top_score = round(
            max(0.0, min(1.0, max(item.score for item in candidates))), 4
        )
        per_chunk_coverage = max(item.query_coverage for item in candidates)
        aggregate_coverage = (
            self._aggregate_query_coverage(query, candidates) if query else 0.0
        )
        coverage = round(max(per_chunk_coverage, aggregate_coverage), 4)
        covered_facets, facet_ratio, missing_facets = facet_coverage(facets, candidates)
        facet_ratio = round(facet_ratio, 4)

        # Explicit requested facets are a stronger signal than generic query-token coverage.
        # A query can contain many control words ("cite", "only use the course", etc.) that
        # depress token coverage even when every requested subject is present. Conversely,
        # zero facet coverage must fail closed even if generic words happen to overlap.
        if requested_facet_count and covered_facets == 0:
            relevance: RelevanceTier = "low"
            reason = "explicit requested facets are not supported by the evidence set"
        elif top_score >= self.high_score and (
            coverage >= self.minimum_coverage or facet_ratio >= 0.5
        ):
            relevance = "high"
            reason = "strong fused score with query or explicit-facet evidence coverage"
        elif top_score >= self.standard_score and (
            coverage >= self.minimum_coverage or facet_ratio >= 0.5
        ):
            relevance = "standard"
            reason = "usable evidence with query or explicit-facet evidence coverage"
        else:
            relevance = "low"
            reason = "weak score and limited evidence-set coverage"
        return RetrievalAssessment(
            relevance=relevance,
            top_score=top_score,
            candidate_count=len(candidates),
            query_coverage=coverage,
            reason=reason,
            requested_facet_count=requested_facet_count,
            covered_facet_count=covered_facets,
            facet_coverage=facet_ratio,
            uncovered_facets=missing_facets,
        )



def extract_index_nodes(index: Any) -> list[Any]:
    storage_context = getattr(index, "storage_context", None)
    docstore = getattr(storage_context, "docstore", None)
    docs = getattr(docstore, "docs", None)
    if isinstance(docs, dict):
        return [node for node in docs.values() if hasattr(node, "get_content")]
    index_struct = getattr(index, "index_struct", None)
    nodes_dict = getattr(index_struct, "nodes_dict", None)
    if isinstance(nodes_dict, dict) and docstore is not None:
        nodes: list[Any] = []
        for node_id in nodes_dict:
            try:
                node = docstore.get_node(node_id)
            except Exception:
                continue
            if hasattr(node, "get_content"):
                nodes.append(node)
        return nodes
    return []
