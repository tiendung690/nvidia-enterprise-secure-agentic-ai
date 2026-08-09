from __future__ import annotations

import hashlib
import re
from typing import Any

_SECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?m)^#{1,6}\s+([^\n]{3,160})$"),
    re.compile(r"(?m)^\*\*([^*\n]{3,160})\*\*\s*$"),
    re.compile(r"(?m)^\s*\d+(?:\.\d+)*\s+([A-Z][^\n]{3,150})$"),
    re.compile(r"(?m)^([A-Z][A-Z0-9 /&\-:]{5,120})$"),
)


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def extract_section_title(text: str) -> str | None:
    sample = text[:2000]
    for pattern in _SECTION_PATTERNS:
        match = pattern.search(sample)
        if match:
            title = normalize_whitespace(match.group(1)).strip("#* :-")
            if 3 <= len(title) <= 160:
                return title
    return None


def deterministic_node_id(
    *, corpus: str, relative_path: str, chunk_index: int, text: str
) -> str:
    content_hash = hashlib.sha256(normalize_whitespace(text).encode("utf-8")).hexdigest()[:16]
    safe_path = relative_path.replace("\\", "/").replace("/", "_")
    return f"{corpus}:{safe_path}:chunk-{chunk_index}:{content_hash}"


def deterministic_citation_id(source_id: str, prefix: str = "S") -> str:
    normalized_prefix = prefix.upper()
    if normalized_prefix not in {"S", "D"}:
        raise ValueError("citation prefix must be S or D")
    return normalized_prefix + hashlib.sha256(source_id.encode()).hexdigest()[:6].upper()


def filter_nodes_by_score(nodes: list[Any], *, min_score: float, limit: int) -> list[Any]:
    filtered = [
        item
        for item in nodes
        if item.score is not None and float(item.score) >= min_score
    ]
    return filtered[:limit]
