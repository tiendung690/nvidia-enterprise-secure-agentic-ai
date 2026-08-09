from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from nvidia_agentic_rag.security.masking import DataMasker

OutputDLPMode = Literal["off", "audit", "redact", "block"]


class OutputPolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class OutputPolicyResult:
    answer: str
    signals: tuple[str, ...]
    modified: bool


class OutputPolicy:
    def __init__(self, *, mode: OutputDLPMode, masker: DataMasker) -> None:
        self.mode = mode
        self.masker = masker

    def validate(self, answer: str) -> OutputPolicyResult:
        if self.mode == "off":
            return OutputPolicyResult(answer=answer, signals=(), modified=False)
        result = self.masker.apply(answer)
        if result.signals and self.mode == "block":
            raise OutputPolicyViolation(
                f"Generated answer contains protected data patterns: {sorted(result.signals)}"
            )
        if result.signals and self.mode == "redact":
            return OutputPolicyResult(
                answer=result.text,
                signals=result.signals,
                modified=result.masked,
            )
        return OutputPolicyResult(answer=answer, signals=result.signals, modified=False)
