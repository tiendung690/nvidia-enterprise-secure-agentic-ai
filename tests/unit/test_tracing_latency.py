from __future__ import annotations

from nvidia_agentic_rag.identity import IdentityContext
from nvidia_agentic_rag.tracing.models import RunTrace
from nvidia_agentic_rag.tracing.service import TraceService


class Repository:
    def __init__(self) -> None:
        self.saved: list[RunTrace] = []

    def ping(self) -> bool:
        return True

    def save(self, trace: RunTrace) -> None:
        self.saved.append(trace.model_copy(deep=True))

    def get(self, run_id: str, *, tenant_id=None, user_id=None):
        return next((item for item in reversed(self.saved) if item.run_id == run_id), None)


def test_run_trace_preserves_fractional_millisecond_latency() -> None:
    repository = Repository()
    service = TraceService(repository)
    identity = IdentityContext(
        user_id="u1",
        tenant_id="tenant-a",
        roles=("analyst",),
        departments=(),
        clearance="confidential",
    )
    trace = service.start(
        request_id="r1",
        session_id="s1",
        identity=identity,
        purpose="business-analytics",
        query="rank books",
        index_version="v1",
        memory_version="m1",
        prompt_version="p1",
    )
    service.complete(
        trace,
        answer="ok",
        latency_ms=72.89,
        source_ids=[],
        tool_names=[],
        memory_reads={},
    )
    assert trace.latency_ms == 72.89
    assert repository.saved[-1].latency_ms == 72.89
