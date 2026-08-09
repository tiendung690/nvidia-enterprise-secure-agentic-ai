from __future__ import annotations

from enum import IntEnum


class DataClassification(IntEnum):
    """Ordered enterprise data-classification levels used by policy checks."""

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3

    @classmethod
    def parse(cls, value: str | int | "DataClassification") -> "DataClassification":
        if isinstance(value, cls):
            return value
        if isinstance(value, int):
            return cls(value)
        normalized = value.strip().replace("-", "_").upper()
        return cls[normalized]

    def label(self) -> str:
        return self.name.lower()
