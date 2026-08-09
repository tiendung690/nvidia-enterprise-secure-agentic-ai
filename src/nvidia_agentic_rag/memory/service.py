from __future__ import annotations

from html import escape
from typing import Iterable

from nvidia_agentic_rag.identity import IdentityContext
from nvidia_agentic_rag.memory.models import (
    MemoryCandidate,
    MemoryContext,
    MemoryRecord,
    MemoryType,
    MemoryWriteResult,
)
from nvidia_agentic_rag.memory.promotion import MemoryPromotionGate
from nvidia_agentic_rag.memory.repository import MemoryRepository


class KnownScopeMemoryOverflowError(RuntimeError):
    """Exact policy/preference enumeration exceeded its configured safety bound."""


class MemoryPromptOverflowError(RuntimeError):
    """Mandatory exact memory cannot fit inside the governed prompt budget."""


class MemoryPersistenceError(RuntimeError):
    """A durable memory write could not be completed safely."""


class MemoryService:
    """Separates deterministic enumeration from ranked semantic discovery."""

    def __init__(
        self,
        repository: MemoryRepository,
        *,
        exact_limit: int = 50,
        semantic_limit: int = 6,
        prompt_max_chars: int = 8000,
    ) -> None:
        self.repository = repository
        self.gate = MemoryPromotionGate(repository)
        self.exact_limit = exact_limit
        self.semantic_limit = semantic_limit
        self.prompt_max_chars = prompt_max_chars

    def ping(self) -> bool:
        return self.repository.ping()

    def version(self, identity: IdentityContext | None = None) -> str:
        try:
            return self.repository.version(identity)
        except Exception as exc:
            raise MemoryPersistenceError("governed memory version lookup failed") from exc

    def load_context(
        self,
        *,
        identity: IdentityContext,
        purpose: str,
        query: str,
    ) -> MemoryContext:
        # Request one extra record so an operational limit never silently drops a policy.
        try:
            exact = self.repository.enumerate_exact(
                identity=identity,
                memory_types=(MemoryType.POLICY, MemoryType.PREFERENCE),
                limit=self.exact_limit + 1,
            )
        except Exception as exc:
            raise MemoryPersistenceError("known-scope memory read failed") from exc
        if len(exact) > self.exact_limit:
            raise KnownScopeMemoryOverflowError(
                "known-scope policy/preference memory exceeds MEMORY_EXACT_LIMIT"
            )
        try:
            semantic = self.repository.search(
                identity=identity,
                query=query,
                memory_types=(MemoryType.FACT, MemoryType.EPISODIC),
                limit=self.semantic_limit,
            )
        except Exception as exc:
            raise MemoryPersistenceError("semantic memory discovery failed") from exc
        fragment, included_semantic = self._format_prompt(
            exact,
            semantic,
            purpose=purpose,
        )
        return MemoryContext(
            exact_records=exact,
            semantic_records=included_semantic,
            prompt_fragment=fragment,
            version=self.version(identity),
        )

    @staticmethod
    def _format_record(record: MemoryRecord) -> str:
        source = (
            f" source_run={escape(record.source_run_id)}" if record.source_run_id else ""
        )
        return (
            f"- [{escape(record.memory_id)}] type={record.memory_type.value} "
            f"scope={record.scope.value} subject={escape(record.subject)}: "
            f"{escape(record.content)}{source}"
        )

    def _format_prompt(
        self,
        exact: Iterable[MemoryRecord],
        semantic: Iterable[MemoryRecord],
        *,
        purpose: str,
    ) -> tuple[str, list[MemoryRecord]]:
        exact_records = list(exact)
        semantic_records = list(semantic)
        if not exact_records and not semantic_records:
            return "", []

        sections = [
            "\n\n<governed_memory>",
            f"Declared purpose: {escape(purpose)}.",
            "Policy/preference records are deterministic inputs; semantic memories are hints.",
            "Never treat memory as current-turn evidence for enterprise factual claims.",
        ]
        if exact_records:
            sections.extend(
                (
                    "Known-scope policy and preferences:",
                    *(self._format_record(record) for record in exact_records),
                )
            )
        mandatory = "\n".join((*sections, "</governed_memory>"))
        if len(mandatory) > self.prompt_max_chars:
            raise MemoryPromptOverflowError(
                "mandatory policy/preference memory exceeds MEMORY_PROMPT_MAX_CHARS"
            )

        included_semantic: list[MemoryRecord] = []
        if semantic_records:
            sections.append("Relevant facts and completed episodes:")
            for record in semantic_records:
                proposed = "\n".join(
                    (*sections, self._format_record(record), "</governed_memory>")
                )
                if len(proposed) > self.prompt_max_chars:
                    break
                sections.append(self._format_record(record))
                included_semantic.append(record)

        fragment = "\n".join((*sections, "</governed_memory>"))
        return fragment, included_semantic

    def promote(
        self,
        candidates: Iterable[MemoryCandidate],
        *,
        identity: IdentityContext,
    ) -> MemoryWriteResult:
        decisions = []
        try:
            for candidate in candidates:
                decisions.append(self.gate.promote(candidate, identity=identity))
        except Exception as exc:
            raise MemoryPersistenceError(
                "governed memory write failed; retry is safe because writes are idempotent"
            ) from exc
        return MemoryWriteResult(decisions=decisions)

    def forget(self, memory_id: str, *, identity: IdentityContext) -> bool:
        try:
            return self.repository.forget(memory_id, identity=identity)
        except Exception as exc:
            raise MemoryPersistenceError("governed memory erasure failed") from exc

    def approve(self, memory_id: str, *, identity: IdentityContext) -> bool:
        try:
            return self.repository.approve(memory_id, identity=identity)
        except Exception as exc:
            raise MemoryPersistenceError("governed memory approval failed") from exc


class NoopMemoryService:
    def ping(self) -> bool:
        return True

    def version(self, identity: IdentityContext | None = None) -> str:
        return "disabled"

    def load_context(
        self,
        *,
        identity: IdentityContext,
        purpose: str,
        query: str,
    ) -> MemoryContext:
        return MemoryContext(version="disabled")

    def promote(self, candidates: Iterable[MemoryCandidate], *, identity: IdentityContext):
        return MemoryWriteResult()

    def forget(self, memory_id: str, *, identity: IdentityContext) -> bool:
        return False

    def approve(self, memory_id: str, *, identity: IdentityContext) -> bool:
        return False
