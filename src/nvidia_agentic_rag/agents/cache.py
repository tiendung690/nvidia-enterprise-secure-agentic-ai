from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TypeAlias

from nvidia_agentic_rag.policy.models import PolicyAudit
from nvidia_agentic_rag.schemas import (
    AnswerCompletenessAudit,
    CitationAudit,
    EvidenceOrigin,
    ProvenanceAudit,
    ProvenanceDerivation,
    SourceReference,
)

CacheKey: TypeAlias = tuple[str, ...]


@dataclass(frozen=True)
class CachedResponse:
    answer: str
    sources: tuple[SourceReference, ...] = field(default_factory=tuple)
    citation_audit: CitationAudit = field(default_factory=CitationAudit)
    policy_audit: PolicyAudit = field(default_factory=PolicyAudit)
    answer_completeness: AnswerCompletenessAudit = field(default_factory=AnswerCompletenessAudit)
    provenance: tuple[ProvenanceDerivation, ...] = field(default_factory=tuple)
    provenance_audit: ProvenanceAudit = field(default_factory=ProvenanceAudit)
    evidence_origin: EvidenceOrigin = "cached_retrieval_answer"
    safety_signals: tuple[str, ...] = field(default_factory=tuple)
    created_at: float = field(default_factory=lambda: time.monotonic())


class TTLResponseCache:
    """Bounded in-process LRU cache with monotonic TTL expiry.

    Security is enforced by AgentService's key: tenant, user authorization hash,
    purpose, answer mode, policy/index/prompt versions, and model settings.
    """

    def __init__(self, *, ttl_seconds: float, max_entries: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[CacheKey, CachedResponse] = OrderedDict()

    def __len__(self) -> int:
        self._evict_expired()
        return len(self._entries)

    def get(self, key: CacheKey) -> CachedResponse | None:
        self._evict_expired()
        value = self._entries.get(key)
        if value is None:
            return None
        self._entries.move_to_end(key)
        return value

    def put(self, key: CacheKey, value: CachedResponse) -> None:
        self._evict_expired()
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, value in self._entries.items()
            if now - value.created_at >= self.ttl_seconds
        ]
        for key in expired:
            self._entries.pop(key, None)
