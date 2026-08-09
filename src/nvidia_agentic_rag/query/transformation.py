from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r"[\w.-]+", re.UNICODE)
_IDENTIFIER_RE = re.compile(
    r"(?:[A-Z]{2,}[A-Z0-9_-]*|[a-zA-Z_][\w.]*\([^)]*\)|\b\d+(?:\.\d+){1,3}\b)"
)
_FILLER_PREFIXES = (
    "please ",
    "could you ",
    "can you ",
    "would you ",
    "hãy ",
    "vui lòng ",
    "giúp tôi ",
    "giúp mình ",
)
_QUESTION_PREFIXES = (
    "what is ",
    "what are ",
    "how does ",
    "how do ",
    "why does ",
    "explain ",
    "compare ",
    "là gì ",
    "như thế nào ",
    "tại sao ",
    "so sánh ",
)


@dataclass(frozen=True)
class QueryTransformationPlan:
    original: str
    variants: tuple[str, ...]
    strategy: str
    ambiguous: bool
    identifiers: tuple[str, ...]


class GuardedMultiQueryTransformer:
    """Deterministic query expansion that preserves identifiers and avoids LLM drift.

    It intentionally generates only small, auditable variants. HyDE remains an optional
    provider-backed extension because speculative documents should not be produced silently.
    """

    def __init__(self, *, enabled: bool = True, max_variants: int = 3) -> None:
        if max_variants < 1:
            raise ValueError("max_variants must be positive")
        self.enabled = enabled
        self.max_variants = max_variants

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.strip().split())

    @staticmethod
    def _tokens(value: str) -> list[str]:
        return [token.casefold() for token in _TOKEN_RE.findall(value)]

    @staticmethod
    def _strip_prefixes(value: str, prefixes: tuple[str, ...]) -> str:
        lowered = value.casefold()
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return value[len(prefix) :].strip(" ?.:;,-")
        return value

    def transform(self, query: str) -> QueryTransformationPlan:
        original = self._normalize(query)
        if not original:
            raise ValueError("query must not be empty")

        identifiers = tuple(dict.fromkeys(_IDENTIFIER_RE.findall(original)))
        tokens = self._tokens(original)
        ambiguous = len(tokens) <= 8 or any(
            marker in original.casefold()
            for marker in ("this", "that", "it", "này", "đó", "cái này", "vấn đề này")
        )
        if not self.enabled or self.max_variants == 1:
            return QueryTransformationPlan(
                original=original,
                variants=(original,),
                strategy="identity",
                ambiguous=ambiguous,
                identifiers=identifiers,
            )

        candidates = [original]
        concise = self._strip_prefixes(original, _FILLER_PREFIXES)
        concise = self._strip_prefixes(concise, _QUESTION_PREFIXES)
        if concise and concise.casefold() != original.casefold():
            candidates.append(concise)

        if identifiers:
            candidates.append(
                self._normalize(
                    f"troubleshooting root cause production impact {concise or original}"
                )
            )
        elif ambiguous:
            candidates.append(f"technical explanation and production implications of {concise}")
        else:
            candidates.append(f"architecture trade-offs failure modes {concise}")

        unique: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = self._normalize(candidate)
            key = normalized.casefold()
            if normalized and key not in seen:
                unique.append(normalized)
                seen.add(key)
            if len(unique) >= self.max_variants:
                break

        return QueryTransformationPlan(
            original=original,
            variants=tuple(unique),
            strategy="guarded_multi_query" if len(unique) > 1 else "identity",
            ambiguous=ambiguous,
            identifiers=identifiers,
        )


def should_expand_query(query: str) -> bool:
    """Enable Multi-Query only when ambiguity or breadth can justify extra retrieval work."""
    normalized = " ".join(query.casefold().split())
    tokens = [token for token in _TOKEN_RE.findall(normalized) if len(token) > 1]
    broad_signals = (
        "compare",
        "trade-off",
        "tradeoff",
        "architecture",
        "failure mode",
        "limitations",
        "strengths",
        "across",
        "multi-step",
        "end-to-end",
    )
    ambiguous_signals = (
        "this",
        "that",
        "it",
        "these",
        "those",
        "này",
        "đó",
        "cái này",
    )
    return (
        len(tokens) >= 18
        or any(signal in normalized for signal in broad_signals)
        or any(signal in normalized for signal in ambiguous_signals)
    )
