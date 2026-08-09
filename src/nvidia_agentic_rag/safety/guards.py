from __future__ import annotations

import re
from dataclasses import dataclass

_DIRECT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_previous_instructions",
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    ),
    ("reveal_system_prompt", re.compile(r"reveal\s+(the\s+)?system\s+prompt", re.I)),
    ("developer_message_exfiltration", re.compile(r"developer\s+message", re.I)),
    ("destructive_function", re.compile(r"delete_all\s*\(", re.I)),
    ("shell_execution", re.compile(r"run\s+.*system\s+shell", re.I)),
    (
        "credential_exfiltration",
        re.compile(
            r"(show|send|upload|exfiltrate).{0,40}"
            r"(api[_ -]?key|secret|token|credential)",
            re.I,
        ),
    ),
)

_INDIRECT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "embedded_instruction_override",
        re.compile(r"(system|assistant)\s*(message|instruction)\s*:", re.I),
    ),
    (
        "embedded_ignore_instruction",
        re.compile(r"ignore\s+(all\s+)?(prior|previous)\s+instructions", re.I),
    ),
    (
        "embedded_secret_request",
        re.compile(
            r"(reveal|return|transmit).{0,50}"
            r"(secret|credential|api[_ -]?key|system prompt)",
            re.I,
        ),
    ),
    (
        "embedded_tool_command",
        re.compile(r"(call|invoke|execute)\s+(the\s+)?[a-z0-9_\-]+\s+tool", re.I),
    ),
)


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    signals: tuple[str, ...]


def _inspect(text: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> tuple[str, ...]:
    return tuple(name for name, pattern in patterns if pattern.search(text))


def inspect_prompt(text: str) -> GuardResult:
    signals = _inspect(text, _DIRECT_PATTERNS)
    return GuardResult(allowed=not signals, signals=signals)


def inspect_untrusted_content(text: str) -> GuardResult:
    """Detect likely indirect prompt-injection instructions in retrieved/tool data.

    This is a risk signal, not an authorization boundary. Hard controls remain tool
    allow-lists, read-only capabilities, schemas, authentication, and approval policy.
    """

    signals = _inspect(text, _INDIRECT_PATTERNS)
    return GuardResult(allowed=not signals, signals=signals)
