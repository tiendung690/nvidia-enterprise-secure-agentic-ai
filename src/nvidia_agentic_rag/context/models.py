from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SecureCandidate:
    node_with_score: Any
    decision_id: str
    classification: str
    masked_text: str
    masked: bool
    dlp_signals: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ContextBrokerResult:
    authorized: tuple[SecureCandidate, ...]
    denied_candidate_count: int
    policy_version: str
