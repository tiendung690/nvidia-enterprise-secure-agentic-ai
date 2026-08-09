from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.tracing.repository import (
    InMemoryTraceRepository, JsonlTraceRepository, PostgresTraceRepository,
)
from nvidia_agentic_rag.tracing.service import TraceService


def build_trace_service(settings: Settings) -> TraceService:
    if settings.trace_backend == "postgres":
        repository = PostgresTraceRepository(settings.database_url)
    elif settings.trace_backend == "memory":
        repository = InMemoryTraceRepository()
    else:
        repository = JsonlTraceRepository(settings.trace_log_path)
    return TraceService(repository)
