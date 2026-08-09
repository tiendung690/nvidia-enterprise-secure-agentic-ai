from __future__ import annotations

import re

from nvidia_agentic_rag.memory.models import (
    MemoryCandidate,
    MemoryScope,
    MemoryType,
    ProvenanceKind,
)
from nvidia_agentic_rag.safety import inspect_prompt, inspect_untrusted_content

_DURABLE_MARKER = re.compile(
    r"\b(from now on|going forward|always|i prefer|my preference is|"
    r"từ giờ|từ nay|luôn luôn|hãy luôn|tôi thích|ưu tiên)\b",
    re.IGNORECASE,
)

_PREFERENCE_RULES: tuple[tuple[str, str, str, re.Pattern[str]], ...] = (
    (
        "response format",
        "response_format",
        "json",
        re.compile(r"\bjson\b", re.IGNORECASE),
    ),
    (
        "response format",
        "response_format",
        "markdown",
        re.compile(r"\bmarkdown\b", re.IGNORECASE),
    ),
    (
        "response format",
        "response_format",
        "table",
        re.compile(r"\b(table|tabular|bảng)\b", re.IGNORECASE),
    ),
    (
        "response format",
        "response_format",
        "bullet_list",
        re.compile(r"\b(bullet|bulleted|gạch đầu dòng)\b", re.IGNORECASE),
    ),
    (
        "response language",
        "response_language",
        "vi",
        re.compile(r"\b(vietnamese|tiếng việt)\b", re.IGNORECASE),
    ),
    (
        "response language",
        "response_language",
        "en",
        re.compile(r"\b(english|tiếng anh)\b", re.IGNORECASE),
    ),
    (
        "response language",
        "response_language",
        "ko",
        re.compile(r"\b(korean|tiếng hàn)\b", re.IGNORECASE),
    ),
    (
        "response language",
        "response_language",
        "ja",
        re.compile(r"\b(japanese|tiếng nhật)\b", re.IGNORECASE),
    ),
    (
        "response detail",
        "response_detail",
        "concise",
        re.compile(r"\b(concise|brief|short|ngắn gọn|súc tích)\b", re.IGNORECASE),
    ),
    (
        "response detail",
        "response_detail",
        "detailed",
        re.compile(r"\b(detailed|in depth|deep|chi tiết|phân tích sâu)\b", re.IGNORECASE),
    ),
)


class ExplicitPreferenceExtractor:
    """Fail-closed deterministic extraction for a small allow-list of durable preferences.

    It intentionally does not infer arbitrary facts, personality, policy, or sensitive attributes.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    def extract(self, text: str, *, source_run_id: str | None = None) -> list[MemoryCandidate]:
        normalized = " ".join(text.split())
        if not self.enabled or not _DURABLE_MARKER.search(normalized):
            return []
        signals = set(inspect_prompt(normalized).signals)
        signals.update(inspect_untrusted_content(normalized).signals)
        if signals:
            return []

        candidates: list[MemoryCandidate] = []
        seen_predicates: set[str] = set()
        for subject, predicate, value, pattern in _PREFERENCE_RULES:
            if predicate in seen_predicates or not pattern.search(normalized):
                continue
            seen_predicates.add(predicate)
            candidates.append(
                MemoryCandidate(
                    memory_type=MemoryType.PREFERENCE,
                    subject=subject,
                    predicate=predicate,
                    value=value,
                    content=f"Preferred {predicate.replace('_', ' ')}: {value}",
                    requested_scope=MemoryScope.USER,
                    confidence=1.0,
                    provenance=ProvenanceKind.USER_STATED,
                    source_run_id=source_run_id,
                    metadata={"extraction": "deterministic_allow_list"},
                )
            )
        return candidates
