from __future__ import annotations

from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.memory.repository import (
    InMemoryMemoryRepository,
    PostgresMemoryRepository,
)
from nvidia_agentic_rag.memory.service import MemoryService, NoopMemoryService


def build_memory_service(settings: Settings):
    if settings.memory_backend == "disabled":
        return NoopMemoryService()
    if settings.memory_backend == "postgres":
        repository = PostgresMemoryRepository(settings.memory_database_url or settings.database_url)
    else:
        repository = InMemoryMemoryRepository()
    return MemoryService(
        repository,
        exact_limit=settings.memory_exact_limit,
        semantic_limit=settings.memory_semantic_limit,
        prompt_max_chars=settings.memory_prompt_max_chars,
    )
