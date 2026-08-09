from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

RouteKind = Literal["calculator", "definition", "analytics", "direct_rag", "agent"]

_CALCULATOR_PREFIX_RE = re.compile(
    r"^\s*(?:calculate|compute|evaluate|what\s+is|solve)\s+(.+?)[?.!]*\s*$",
    re.IGNORECASE,
)
_ARITHMETIC_RE = re.compile(r"^[\d\s()+\-*/%.]+$")
_DEFINITION_RE = re.compile(
    r"^\s*(?:define|what\s+is)\s+(.+?)(?:\s+in\s+two\s+sentences)?[?.!]*\s*$",
    re.IGNORECASE,
)
_CUSTOMER_ID_RE = re.compile(
    r"\bcustomer\s+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})(['’]s)?\b",
    re.IGNORECASE,
)
_BOOK_ID_RE = re.compile(
    r"\bbook\s+([A-Za-z0-9][A-Za-z0-9._:-]{0,127})(['’]s)?\b",
    re.IGNORECASE,
)
_CUSTOMER_EXPLICIT_ID_RE = re.compile(
    r"\bcustomer\s+(?:id|code)\s*[:#=-]?\s*([A-Za-z0-9][A-Za-z0-9._:-]{0,127})\b",
    re.IGNORECASE,
)
_BOOK_EXPLICIT_ID_RE = re.compile(
    r"\bbook\s+(?:id|code)\s*[:#=-]?\s*([A-Za-z0-9][A-Za-z0-9._:-]{0,127})\b",
    re.IGNORECASE,
)
# The demo/serving contract uses stable typed identifiers (for example C001/B003).  Users often
# omit the words ``customer`` and ``book`` in follow-up proof questions ("did C001 buy B003?").
# These conservative patterns are used only by the relationship-sufficiency guard below; normal
# entity lookup still requires the explicit customer/book syntax handled above.
_BARE_CUSTOMER_ID_RE = re.compile(r"\b(C\d{2,}[A-Za-z0-9._:-]*)\b", re.IGNORECASE)
_BARE_BOOK_ID_RE = re.compile(r"\b(B\d{2,}[A-Za-z0-9._:-]*)\b", re.IGNORECASE)
_ENTITY_DESCRIPTOR_WORDS = frozenset(
    {
        "amount",
        "count",
        "counts",
        "quantity",
        "revenue",
        "sales",
        "spending",
        "order",
        "orders",
        "total",
        "totals",
        "ranking",
        "rank",
        "table",
        "tables",
        "grain",
    }
)
_TOP_BOOK_REVENUE_MARKERS = (
    "highest-revenue book",
    "highest revenue book",
    "highest book revenue",
    "top-revenue book",
    "top revenue book",
    "highest-grossing book",
    "book generated the highest revenue",
    "book generating the highest revenue",
)
_CUSTOMER_SPENDING_MARKERS = (
    "total spending",
    "customer spending",
    "spent in total",
    "total_amount",
    "spending",
)
_COMPARISON_MARKERS = ("compare", "larger", "difference", "percentage")
_RANK_MARKERS = ("rank", "ranking", "list all", "all customers", "all books", "top performers")
_CUSTOMER_DERIVED_MARKERS = (
    "average spending per order",
    "avg spending per order",
    "average spend/order",
    "avg/order",
    "average_spending_per_order",
)
_BOOK_DERIVED_MARKERS = (
    "revenue per unit",
    "revenue/unit",
    "rpu",
    "revenue_per_unit",
)
_RECONCILIATION_MARKERS = ("reconcile", "reconciliation", "reconciliation audit", "cross-gold")
_RECONCILIATION_AUDIT_MARKERS = (
    "audit",
    "consistency",
    "consistent",
    "double-count",
    "double count",
    "double-counting",
    "grain of the tables",
)
_UNSUPPORTED_TIME_MARKERS = (
    "over time",
    "trend",
    "monthly",
    "by month",
    "weekly",
    "by week",
    "last month",
    "previous month",
    "prior month",
    "last week",
    "previous week",
    "last quarter",
    "previous quarter",
    "last year",
    "previous year",
    "month over month",
    "month-over-month",
    "mom",
    "quarter over quarter",
    "quarter-over-quarter",
    "qoq",
    "year over year",
    "year-over-year",
    "yoy",
    "historical",
    "history of",
)
_UNSUPPORTED_CAUSAL_MARKERS = (
    "why did",
    "why does",
    "why has",
    "why is",
    "why was",
    "explain why",
    "what caused",
    "cause of",
    "causal",
    "reason for the increase",
    "reason for the decrease",
)
_UNSUPPORTED_CUSTOMER_BOOK_MARKERS = (
    "which book did",
    "which books did",
    "books did customer",
    "book did customer",
    "customer bought",
    "customer purchased",
    "purchased by customer",
    "customer-book relation",
    "customer book relation",
)
_CUSTOMER_BOOK_RELATION_VERB_RE = re.compile(
    r"\b(?:purchase(?:d)?|bought|buy|acquired)\b",
    re.IGNORECASE,
)
_CUSTOMER_BOOK_DERIVED_RELATION_RE = re.compile(
    r"(?:"
    r"\b(?:percentage|percent|share|proportion|fraction)\b.*"
    r"\b(?:revenue|sales|spending|amount|quantity|units?|orders?)\b.*"
    r"\b(?:from|by|attributable\s+to)\b"
    r"|\b(?:revenue|sales|quantity|units?|orders?)\b.*\b(?:from|by)\b"
    r"|\b(?:spend|spent|spending)\b.*\b(?:on|for)\b"
    r"|\b(?:contribut(?:e|ed|es|ion)|attribut(?:e|ed|ion))\b"
    r")",
    re.IGNORECASE,
)

_COURSE_MARKERS = (
    "agentic rag course",
    "indexed course",
    "course documents",
    "indexed agentic rag",
)
_PAPER_MARKERS = (
    "research papers",
    "indexed papers",
    "indexed research",
    "research paper",
)

_ENTERPRISE_KNOWLEDGE_SCOPE_MARKERS = (
    "our",
    "company",
    "internal",
    "enterprise",
    "organization",
    "organisation",
)
_ENTERPRISE_KNOWLEDGE_TOPIC_MARKERS = (
    "strategy",
    "architecture",
    "design",
    "approach",
    "roadmap",
    "policy",
    "runbook",
    "guideline",
    "documentation",
    "bottleneck",
    "training",
)

_BOILERPLATE_PATTERNS = (
    r"\busing\s+only\s+the\s+authorized\s+indexed\s+agentic\s+rag\s+course\b",
    r"\busing\s+only\s+the\s+indexed\s+agentic\s+rag\s+course\b",
    r"\baccording\s+to\s+the\s+indexed\s+agentic\s+rag\s+course\b",
    r"\baccording\s+to\s+the\s+indexed\s+course\s+documents\b",
    r"\busing\s+only\s+the\s+indexed\s+research\s+papers\b",
    r"\baccording\s+to\s+the\s+indexed\s+research\s+papers\b",
    r"\busing\s+the\s+authorized\s+indexed\s+course\s+documents\b",
)


@dataclass(frozen=True)
class RouteDecision:
    kind: RouteKind
    tool_names: tuple[str, ...] = ()
    tool_input: str | None = None
    reason: str = ""
    requires_enterprise_evidence: bool = False


def _strip_terminal_punctuation(value: str) -> str:
    return value.strip().rstrip("?.! ")


def _extract_arithmetic_expression(query: str) -> str | None:
    stripped = _strip_terminal_punctuation(query)
    candidate = stripped
    match = _CALCULATOR_PREFIX_RE.match(stripped)
    if match:
        candidate = match.group(1).strip()
    if not _ARITHMETIC_RE.fullmatch(candidate):
        return None
    if not any(operator in candidate for operator in ("+", "-", "*", "/", "%")):
        return None
    return candidate


def _plan(**kwargs: object) -> str:
    return json.dumps(kwargs, separators=(",", ":"), ensure_ascii=False)


def _extract_entity_id(
    query: str,
    *,
    generic_pattern: re.Pattern[str],
    explicit_pattern: re.Pattern[str],
) -> str | None:
    """Extract an entity ID without mistaking business nouns for identifiers.

    Natural-language analytics contains phrases such as ``customer spending`` and
    ``book revenue``. The old permissive regex interpreted those nouns as IDs, which could
    route a cross-Gold audit into a lookup for customer ``spending``. Explicit ``id/code``
    syntax is always accepted. Shorthand IDs are accepted when they look identifier-like
    (digits/punctuation/uppercase) or are possessive, for example ``customer C001's``.
    """

    explicit = explicit_pattern.search(query)
    if explicit:
        return explicit.group(1)

    match = generic_pattern.search(query)
    if not match:
        return None
    candidate = match.group(1)
    possessive = bool(match.group(2))
    if candidate.casefold() in _ENTITY_DESCRIPTOR_WORDS:
        return None
    identifier_like = (
        possessive
        or any(char.isdigit() for char in candidate)
        or any(char in "._:-" for char in candidate)
        or (len(candidate) > 1 and candidate.isupper())
    )
    return candidate if identifier_like else None


def _extract_analytics_plan(query: str) -> tuple[str, str] | None:
    lowered = query.casefold()
    customer_id = _extract_entity_id(
        query,
        generic_pattern=_CUSTOMER_ID_RE,
        explicit_pattern=_CUSTOMER_EXPLICIT_ID_RE,
    )
    book_id = _extract_entity_id(
        query,
        generic_pattern=_BOOK_ID_RE,
        explicit_pattern=_BOOK_EXPLICIT_ID_RE,
    )
    # Relationship-proof prompts commonly use only canonical IDs.  Do not broaden these bare-ID
    # fallbacks into the normal lookup router: they exist solely to fail closed when the curated
    # Gold summaries cannot prove a customer-to-book edge.
    relation_customer_id = customer_id
    relation_book_id = book_id
    if relation_customer_id is None:
        match = _BARE_CUSTOMER_ID_RE.search(query)
        relation_customer_id = match.group(1) if match else None
    if relation_book_id is None:
        match = _BARE_BOOK_ID_RE.search(query)
        relation_book_id = match.group(1) if match else None

    # Resolve evidence requirements before model routing. The curated Gold serving layer has no
    # governed time series, causal mechanism, or customer-to-book/order-item grain. Known missing
    # capabilities therefore fail closed deterministically instead of consuming a hosted LLM turn.
    if any(marker in lowered for marker in _UNSUPPORTED_TIME_MARKERS):
        return (
            _plan(
                dataset="cross_gold",
                operation="unsupported",
                unsupported_reason="time_dimension_not_available",
            ),
            "structured analytics time dimension is unavailable",
        )

    explicit_customer_book_relation = any(
        marker in lowered for marker in _UNSUPPORTED_CUSTOMER_BOOK_MARKERS
    )
    bare_id_relationship_proof = (
        relation_customer_id is not None
        and relation_book_id is not None
        and _CUSTOMER_BOOK_RELATION_VERB_RE.search(query) is not None
    )
    customer_book_derived_metric = (
        relation_customer_id is not None
        and relation_book_id is not None
        and _CUSTOMER_BOOK_DERIVED_RELATION_RE.search(query) is not None
    )
    if (customer_id and explicit_customer_book_relation) or bare_id_relationship_proof:
        return (
            _plan(
                dataset="cross_gold",
                operation="unsupported",
                unsupported_reason="customer_book_relation_not_available",
            ),
            "customer-to-book relationship grain is unavailable",
        )
    if customer_book_derived_metric:
        return (
            _plan(
                dataset="cross_gold",
                operation="unsupported",
                unsupported_reason="customer_book_metric_not_available",
            ),
            "customer-to-book metric grain is unavailable",
        )

    has_top_book_revenue = (
        any(marker in lowered for marker in _TOP_BOOK_REVENUE_MARKERS)
        or ("book" in lowered and "highest revenue" in lowered)
        or (relation_book_id is not None and "highest revenue" in lowered)
    )
    causal_request = any(marker in lowered for marker in _UNSUPPORTED_CAUSAL_MARKERS)
    if causal_request and has_top_book_revenue:
        return (
            _plan(
                dataset="gold_book_sales_summary",
                operation="top_book_causal_guard",
                entity_id=relation_book_id,
            ),
            "governed top-book facts with deterministic causal abstention",
        )
    if causal_request:
        return (
            _plan(
                dataset="cross_gold",
                operation="unsupported",
                unsupported_reason="causality_not_available",
            ),
            "structured analytics causality evidence is unavailable",
        )

    has_customer_spending = any(marker in lowered for marker in _CUSTOMER_SPENDING_MARKERS)
    comparison_customer_id = customer_id or relation_customer_id
    if comparison_customer_id and has_top_book_revenue and has_customer_spending:
        if any(marker in lowered for marker in _COMPARISON_MARKERS):
            return (
                _plan(
                    dataset="cross_gold",
                    operation="compare_customer_top_book",
                    entity_id=comparison_customer_id,
                ),
                "governed deterministic customer-to-top-book comparison",
            )
        return (
            _plan(
                dataset="cross_gold",
                operation="customer_and_top_book",
                entity_id=comparison_customer_id,
            ),
            "governed deterministic customer and top-book facts",
        )

    has_customer_and_book = "customer" in lowered and "book" in lowered
    explicit_reconciliation = any(marker in lowered for marker in _RECONCILIATION_MARKERS)
    multi_gold_table_audit = (
        "gold" in lowered
        and "table" in lowered
        and any(marker in lowered for marker in ("both", "two", "across"))
    )
    audit_reconciliation = (
        (has_customer_and_book or multi_gold_table_audit)
        and ("gold" in lowered or "table" in lowered)
        and any(marker in lowered for marker in _RECONCILIATION_AUDIT_MARKERS)
    )
    if (
        explicit_reconciliation
        and ("gold" in lowered or has_customer_and_book)
    ) or audit_reconciliation:
        return (
            _plan(dataset="cross_gold", operation="reconcile"),
            "governed deterministic cross-Gold reconciliation",
        )

    customer_rank = "customer" in lowered and any(marker in lowered for marker in _RANK_MARKERS)
    if customer_rank and any(
        marker in lowered for marker in ("total_amount", "total amount", "spending", "amount")
    ):
        derived = (
            ["average_spending_per_order"]
            if any(marker in lowered for marker in _CUSTOMER_DERIVED_MARKERS)
            else []
        )
        return (
            _plan(
                dataset="gold_customer_order_summary",
                operation="rank",
                sort_metric="total_amount",
                direction="DESC",
                limit=10,
                derived_metrics=derived,
            ),
            "governed deterministic customer ranking",
        )

    book_rank = "book" in lowered and any(marker in lowered for marker in _RANK_MARKERS)
    if book_rank and any(
        marker in lowered for marker in ("total_revenue", "total revenue", "revenue")
    ):
        derived = (
            ["revenue_per_unit"]
            if any(marker in lowered for marker in _BOOK_DERIVED_MARKERS)
            else []
        )
        return (
            _plan(
                dataset="gold_book_sales_summary",
                operation="rank",
                sort_metric="total_revenue",
                direction="DESC",
                limit=10,
                derived_metrics=derived,
            ),
            "governed deterministic book ranking",
        )

    if customer_id and any(marker in lowered for marker in _CUSTOMER_SPENDING_MARKERS):
        return (
            _plan(
                dataset="gold_customer_order_summary",
                operation="lookup",
                entity_id=customer_id,
            ),
            "governed deterministic customer Gold lookup",
        )

    if book_id and any(
        marker in lowered for marker in ("revenue", "sales", "total quantity", "total orders")
    ):
        return (
            _plan(
                dataset="gold_book_sales_summary",
                operation="lookup",
                entity_id=book_id,
            ),
            "governed deterministic book Gold lookup",
        )

    if any(marker in lowered for marker in _TOP_BOOK_REVENUE_MARKERS) or (
        "book" in lowered and "highest revenue" in lowered
    ):
        return (
            _plan(
                dataset="gold_book_sales_summary",
                operation="rank",
                sort_metric="total_revenue",
                direction="DESC",
                limit=1,
                derived_metrics=[],
            ),
            "governed deterministic highest-revenue book lookup",
        )
    return None


def _extract_definition_term(query: str) -> str | None:
    match = _DEFINITION_RE.match(query)
    if not match:
        return None
    term = _strip_terminal_punctuation(match.group(1))
    lowered = term.casefold()
    if any(marker in lowered for marker in (*_COURSE_MARKERS, *_PAPER_MARKERS)):
        return None
    if len(term) < 2 or len(term) > 160:
        return None
    return term


def _normalize_retrieval_query(query: str) -> str:
    value = query
    for pattern in _BOILERPLATE_PATTERNS:
        value = re.sub(pattern, "", value, flags=re.IGNORECASE)
    value = re.sub(
        r"\bcite\s+every\s+factual\s+(?:sentence|claim)\b", "", value, flags=re.IGNORECASE
    )
    value = re.sub(
        r"\bcite\s+course\s+and\s+paper\s+claims\s+separately\b",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s+", " ", value).strip(" ,;:.-")
    return value or query.strip()


_ANALYTICS_PURPOSES = frozenset({"business-analytics", "operations-review"})


def classify_route(query: str, purpose: str | None = None) -> RouteDecision:
    expression = _extract_arithmetic_expression(query)
    if expression is not None:
        return RouteDecision(
            kind="calculator",
            tool_names=("safe_calculator_tool",),
            tool_input=expression,
            reason="deterministic arithmetic expression",
        )

    # Explicit corpus scope is a hard routing constraint. It must be evaluated before
    # analytics heuristics because course/paper questions can legitimately contain words
    # such as "why", "historical", "percentage", or "trend" that also appear in the
    # governed-analytics evidence-sufficiency guards.
    lowered = query.casefold()
    has_course = any(marker in lowered for marker in _COURSE_MARKERS)
    has_papers = any(marker in lowered for marker in _PAPER_MARKERS)
    if has_course and has_papers:
        return RouteDecision(
            kind="direct_rag",
            tool_names=("agentic_rag_course_tool", "research_paper_rag_tool"),
            tool_input=_normalize_retrieval_query(query),
            reason="explicit multi-corpus retrieval request",
            requires_enterprise_evidence=True,
        )
    if has_course and not has_papers:
        return RouteDecision(
            kind="direct_rag",
            tool_names=("agentic_rag_course_tool",),
            tool_input=_normalize_retrieval_query(query),
            reason="explicit single-corpus course request",
            requires_enterprise_evidence=True,
        )
    if has_papers and not has_course:
        return RouteDecision(
            kind="direct_rag",
            tool_names=("research_paper_rag_tool",),
            tool_input=_normalize_retrieval_query(query),
            reason="explicit single-corpus research request",
            requires_enterprise_evidence=True,
        )

    # Purpose is a second routing boundary. In normal service execution the request purpose
    # is always supplied, so a research request cannot be hijacked by analytics keyword
    # heuristics. ``None`` keeps direct unit-level/backward-compatible calls working.
    analytics_allowed = purpose is None or purpose.casefold() in _ANALYTICS_PURPOSES
    if analytics_allowed:
        analytics = _extract_analytics_plan(query)
        if analytics is not None:
            plan_json, reason = analytics
            return RouteDecision(
                kind="analytics",
                tool_names=("analytics_query_tool",),
                tool_input=plan_json,
                reason=reason,
                requires_enterprise_evidence=True,
            )

    # Ordinary enterprise knowledge questions should not enter an expensive agent-planning
    # loop just because the user omitted an internal corpus name. Search the bounded local
    # knowledge corpora first and fail closed when no relevant authorized evidence exists.
    # This keeps company-specific summaries grounded and avoids ballooning provider context.
    if (
        any(marker in lowered.split() for marker in _ENTERPRISE_KNOWLEDGE_SCOPE_MARKERS)
        and any(marker in lowered for marker in _ENTERPRISE_KNOWLEDGE_TOPIC_MARKERS)
    ):
        return RouteDecision(
            kind="direct_rag",
            tool_names=("agentic_rag_course_tool", "research_paper_rag_tool"),
            tool_input=_normalize_retrieval_query(query),
            reason="implicit enterprise knowledge retrieval request",
            requires_enterprise_evidence=True,
        )

    term = _extract_definition_term(query)
    if term is not None:
        return RouteDecision(
            kind="definition",
            tool_names=("definition_tool",),
            tool_input=term,
            reason="deterministic public-definition request",
        )

    return RouteDecision(kind="agent", reason="complex or ambiguous request")
