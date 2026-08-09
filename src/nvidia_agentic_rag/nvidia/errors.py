from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_CONTEXT_LENGTH_MARKERS = (
    "context_length_exceeded",
    "maximum context length",
    "max context length",
    "combined prompt length",
    "prompt length",
    "max_new_tokens",
    "too many tokens",
)

_CAPACITY_MARKERS = (
    "resourceexhausted",
    "resource exhausted",
    "worker local total request limit",
    "too many requests",
    "rate limit",
    "request queue full",
    "service unavailable",
    "temporarily unavailable",
    "capacity",
    "429",
    "503",
)
_TIMEOUT_MARKERS = (
    "readtimeout",
    "connecttimeout",
    "timeouterror",
    "timed out",
    "timeout",
    "gateway timeout",
    "504",
)
_GATEWAY_MARKERS = (
    "bad gateway",
    "connection reset",
    "connection aborted",
    "502",
)


@dataclass(frozen=True)
class ProviderErrorInfo:
    transient: bool
    public_message: str
    error_code: str
    retry_after_seconds: int = 20
    status_code: int | None = None


def _status_code(exc: BaseException) -> int | None:
    direct = getattr(exc, "status_code", None)
    if isinstance(direct, int):
        return direct
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def _retry_after(exc: BaseException, default: int) -> int:
    response: Any = getattr(exc, "response", None)
    headers: Any = getattr(response, "headers", None)
    if headers is None:
        return default
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        return default
    try:
        seconds = int(float(str(raw)))
    except (TypeError, ValueError):
        return default
    # Prevent an upstream header from pinning an interactive request for minutes.
    return min(120, max(1, seconds))


def classify_provider_error(exc: BaseException) -> ProviderErrorInfo:
    """Map upstream errors to stable, retry-aware public contracts.

    Prefer structured HTTP status/Retry-After information when the SDK exposes it,
    then fall back to textual markers for gRPC/wrapped LlamaIndex exceptions.
    """
    status = _status_code(exc)
    text = f"{type(exc).__name__}: {exc}".lower()

    # A context overflow is deterministic and must never be retried as capacity. It usually
    # indicates that the client-side model metadata overstated the provider window or that
    # workflow state was allowed to grow without compaction.
    if any(marker in text for marker in _CONTEXT_LENGTH_MARKERS):
        return ProviderErrorInfo(
            transient=False,
            public_message=(
                "The assembled NVIDIA prompt exceeded the model context budget. "
                "The runtime must compact or bound context before retrying."
            ),
            error_code="NVIDIA_CONTEXT_LENGTH_EXCEEDED",
            retry_after_seconds=0,
            status_code=status,
        )
    if status in {429, 503} or any(marker in text for marker in _CAPACITY_MARKERS):
        return ProviderErrorInfo(
            transient=True,
            public_message=(
                "NVIDIA hosted inference is temporarily at capacity. "
                "Retry after a short delay."
            ),
            error_code="NVIDIA_CAPACITY_EXHAUSTED",
            retry_after_seconds=_retry_after(exc, 20),
            status_code=status,
        )
    if status == 504 or any(marker in text for marker in _TIMEOUT_MARKERS):
        return ProviderErrorInfo(
            transient=True,
            public_message="The NVIDIA hosted inference request timed out.",
            error_code="NVIDIA_PROVIDER_TIMEOUT",
            retry_after_seconds=_retry_after(exc, 10),
            status_code=status,
        )
    if status == 502 or any(marker in text for marker in _GATEWAY_MARKERS):
        return ProviderErrorInfo(
            transient=True,
            public_message="The NVIDIA hosted inference gateway is temporarily unavailable.",
            error_code="NVIDIA_GATEWAY_UNAVAILABLE",
            retry_after_seconds=_retry_after(exc, 10),
            status_code=status,
        )
    if status in {400, 401, 403, 404, 409, 422}:
        return ProviderErrorInfo(
            transient=False,
            public_message="The upstream NVIDIA inference request was rejected.",
            error_code="NVIDIA_PROVIDER_REQUEST_REJECTED",
            retry_after_seconds=0,
            status_code=status,
        )
    return ProviderErrorInfo(
        transient=False,
        public_message="The upstream NVIDIA inference request failed.",
        error_code="NVIDIA_PROVIDER_ERROR",
        retry_after_seconds=0,
        status_code=status,
    )
