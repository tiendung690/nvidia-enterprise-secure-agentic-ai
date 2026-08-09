from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator, Literal

from nvidia_agentic_rag.identity.models import IdentityContext

AnswerMode = Literal["enterprise_factual", "general_advisory"]


@dataclass(frozen=True)
class RequestSecurityContext:
    identity: IdentityContext
    purpose: str
    answer_mode: AnswerMode
    request_id: str
    policy_decision_id: str
    max_sources_per_corpus: int | None = None


_current_scope: ContextVar[RequestSecurityContext | None] = ContextVar(
    "enterprise_request_security_context", default=None
)


def get_request_security_context() -> RequestSecurityContext:
    value = _current_scope.get()
    if value is None:
        raise RuntimeError("No verified request security context is active")
    return value


@contextmanager
def request_security_scope(scope: RequestSecurityContext) -> Iterator[None]:
    token: Token[RequestSecurityContext | None] = _current_scope.set(scope)
    try:
        yield
    finally:
        _current_scope.reset(token)
