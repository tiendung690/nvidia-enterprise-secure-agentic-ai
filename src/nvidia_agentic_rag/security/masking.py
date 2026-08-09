from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

MaskingMode = Literal["off", "redact", "pseudonymize"]

_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_CARD = re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")
_API_KEY = re.compile(r"\b(?:nvapi-|sk-)[A-Za-z0-9_\-]{12,}\b")


@dataclass(frozen=True)
class MaskingResult:
    text: str
    signals: tuple[str, ...]
    masked: bool


class DataMasker:
    def __init__(self, *, mode: MaskingMode, salt: str) -> None:
        self.mode = mode
        self.salt = salt

    def _token(self, kind: str, value: str) -> str:
        digest = hashlib.sha256(f"{self.salt}:{kind}:{value.casefold()}".encode()).hexdigest()[:10]
        return f"[{kind}_{digest.upper()}]"

    def mask_value(self, kind: str, value: str) -> MaskingResult:
        """Mask one value that the caller already knows is sensitive (e.g. a person name).

        Pattern-based `apply` cannot recognize arbitrary personal names, so typed tools use
        this explicit path when the schema itself marks a field as direct-identifier PII.
        """
        normalized_kind = "".join(kind.split()).upper() or "VALUE"
        if self.mode == "off" or not value:
            return MaskingResult(text=value, signals=(), masked=False)
        if self.mode == "pseudonymize":
            masked_value = self._token(normalized_kind, value)
        else:
            masked_value = f"[{normalized_kind}_REDACTED]"
        return MaskingResult(
            text=masked_value,
            signals=(normalized_kind.casefold(),),
            masked=True,
        )

    def apply(self, text: str) -> MaskingResult:
        if self.mode == "off":
            return MaskingResult(text=text, signals=(), masked=False)

        signals: set[str] = set()

        def replace(pattern: re.Pattern[str], kind: str, value: str) -> str:
            if pattern.fullmatch(value):
                signals.add(kind.casefold())
                if self.mode == "pseudonymize":
                    return self._token(kind, value)
                return f"[{kind}_REDACTED]"
            return value

        masked = _EMAIL.sub(lambda match: replace(_EMAIL, "EMAIL", match.group(0)), text)
        masked = _CARD.sub(lambda match: replace(_CARD, "PAYMENT_CARD", match.group(0)), masked)
        masked = _API_KEY.sub(lambda match: replace(_API_KEY, "API_KEY", match.group(0)), masked)
        return MaskingResult(
            text=masked,
            signals=tuple(sorted(signals)),
            masked=masked != text,
        )
