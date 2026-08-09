from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Protocol, Sequence

from nvidia_agentic_rag.identity import IdentityContext
from nvidia_agentic_rag.memory.models import (
    MemoryCandidate,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    MemoryType,
)
from nvidia_agentic_rag.retrieval import tokenize


class MemoryRepository(Protocol):
    def ping(self) -> bool: ...

    def version(self, identity: IdentityContext | None = None) -> str: ...

    def enumerate_exact(
        self,
        *,
        identity: IdentityContext,
        memory_types: Sequence[MemoryType],
        limit: int,
    ) -> list[MemoryRecord]: ...

    def search(
        self,
        *,
        identity: IdentityContext,
        query: str,
        memory_types: Sequence[MemoryType],
        limit: int,
    ) -> list[MemoryRecord]: ...

    def promote(
        self,
        *,
        candidate: MemoryCandidate,
        identity: IdentityContext,
        final_scope: MemoryScope,
        status: MemoryStatus,
    ) -> tuple[MemoryRecord, bool, str | None]: ...

    def get(self, memory_id: str, *, identity: IdentityContext) -> MemoryRecord | None: ...

    def forget(self, memory_id: str, *, identity: IdentityContext) -> bool: ...

    def approve(self, memory_id: str, *, identity: IdentityContext) -> bool: ...


def content_hash(candidate: MemoryCandidate) -> str:
    payload = {
        "memory_type": candidate.memory_type.value,
        "subject": candidate.subject.casefold(),
        "predicate": (candidate.predicate or "").casefold(),
        "value": (candidate.value or "").casefold(),
        "content": candidate.content.casefold(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class InMemoryMemoryRepository:
    """Deterministic repository for tests/local runs; not shared across replicas."""

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self._revision = 0
        self._lock = threading.RLock()
        self.outbox: list[dict[str, object]] = []

    @staticmethod
    def _scope_visible(record: MemoryRecord, identity: IdentityContext) -> bool:
        if record.scope == MemoryScope.GLOBAL:
            return True
        if record.scope == MemoryScope.TENANT:
            return record.tenant_id == identity.tenant_id
        return record.tenant_id == identity.tenant_id and record.user_id == identity.user_id

    def _active_visible(self, identity: IdentityContext) -> list[MemoryRecord]:
        return [
            record
            for record in self._records.values()
            if record.active_at() and self._scope_visible(record, identity)
        ]

    def ping(self) -> bool:
        return True

    def version(self, identity: IdentityContext | None = None) -> str:
        identity_key = identity.authorization_hash() if identity else "all"
        payload = f"{self._revision}:{identity_key}:{len(self._records)}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def enumerate_exact(
        self,
        *,
        identity: IdentityContext,
        memory_types: Sequence[MemoryType],
        limit: int,
    ) -> list[MemoryRecord]:
        allowed = set(memory_types)
        records = [
            record for record in self._active_visible(identity) if record.memory_type in allowed
        ]
        priority = {
            MemoryType.POLICY: 0,
            MemoryType.PREFERENCE: 1,
            MemoryType.FACT: 2,
            MemoryType.EPISODIC: 3,
            MemoryType.TRACE: 4,
        }
        records.sort(key=lambda item: (priority[item.memory_type], item.subject, item.created_at))
        return records[:limit]

    def search(
        self,
        *,
        identity: IdentityContext,
        query: str,
        memory_types: Sequence[MemoryType],
        limit: int,
    ) -> list[MemoryRecord]:
        query_terms = set(tokenize(query))
        if not query_terms:
            return []
        allowed = set(memory_types)
        ranked: list[tuple[float, MemoryRecord]] = []
        for record in self._active_visible(identity):
            if record.memory_type not in allowed:
                continue
            record_terms = set(
                tokenize(
                    " ".join(
                        filter(
                            None,
                            (record.subject, record.predicate, record.value, record.content),
                        )
                    )
                )
            )
            overlap = len(query_terms.intersection(record_terms))
            if overlap == 0:
                continue
            coverage = overlap / len(query_terms)
            specificity = overlap / max(1, len(record_terms))
            ranked.append((0.8 * coverage + 0.2 * specificity, record))
        ranked.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        return [record for _, record in ranked[:limit]]

    @staticmethod
    def _scope_tuple(
        final_scope: MemoryScope, identity: IdentityContext
    ) -> tuple[str | None, str | None]:
        if final_scope == MemoryScope.GLOBAL:
            return None, None
        if final_scope == MemoryScope.TENANT:
            return identity.tenant_id, None
        return identity.tenant_id, identity.user_id

    def promote(
        self,
        *,
        candidate: MemoryCandidate,
        identity: IdentityContext,
        final_scope: MemoryScope,
        status: MemoryStatus,
    ) -> tuple[MemoryRecord, bool, str | None]:
        now = datetime.now(timezone.utc)
        digest = content_hash(candidate)
        tenant_id, user_id = self._scope_tuple(final_scope, identity)
        with self._lock:
            for record in self._records.values():
                if (
                    record.status == MemoryStatus.ACTIVE
                    and record.memory_type == candidate.memory_type
                    and record.scope == final_scope
                    and record.tenant_id == tenant_id
                    and record.user_id == user_id
                    and record.content_hash == digest
                ):
                    return record, True, None

            superseded: MemoryRecord | None = None
            if candidate.memory_type in {MemoryType.FACT, MemoryType.PREFERENCE}:
                for record in self._records.values():
                    if (
                        record.status == MemoryStatus.ACTIVE
                        and record.memory_type == candidate.memory_type
                        and record.scope == final_scope
                        and record.tenant_id == tenant_id
                        and record.user_id == user_id
                        and record.subject.casefold() == candidate.subject.casefold()
                        and (record.predicate or "").casefold()
                        == (candidate.predicate or "").casefold()
                        and record.content_hash != digest
                    ):
                        superseded = record
                        break

            memory_id = "MEM-" + uuid.uuid4().hex[:20].upper()
            record = MemoryRecord(
                memory_id=memory_id,
                memory_type=candidate.memory_type,
                status=status,
                scope=final_scope,
                tenant_id=tenant_id,
                user_id=user_id,
                subject=candidate.subject,
                predicate=candidate.predicate,
                value=candidate.value,
                content=candidate.content,
                content_hash=digest,
                confidence=candidate.confidence,
                provenance=candidate.provenance,
                source_run_id=candidate.source_run_id,
                source_ids=candidate.source_ids,
                effective_from=candidate.effective_from or now,
                effective_until=candidate.effective_until,
                created_at=now,
                updated_at=now,
                metadata=candidate.metadata,
            )
            if superseded and status == MemoryStatus.ACTIVE:
                self._records[superseded.memory_id] = superseded.model_copy(
                    update={
                        "status": MemoryStatus.SUPERSEDED,
                        "effective_until": now,
                        "superseded_by": memory_id,
                        "updated_at": now,
                    }
                )
            self._records[memory_id] = record
            self._revision += 1
            self.outbox.append(
                {
                    "event_id": "EVT-" + uuid.uuid4().hex[:20].upper(),
                    "event_type": "memory.promoted",
                    "aggregate_id": memory_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "created_at": now.isoformat(),
                }
            )
            if superseded and status == MemoryStatus.ACTIVE:
                self.outbox.append(
                    {
                        "event_id": "EVT-" + uuid.uuid4().hex[:20].upper(),
                        "event_type": "memory.superseded",
                        "aggregate_id": superseded.memory_id,
                        "superseded_by": memory_id,
                        "created_at": now.isoformat(),
                    }
                )
            return (
                record,
                False,
                superseded.memory_id if superseded and status == MemoryStatus.ACTIVE else None,
            )

    def get(self, memory_id: str, *, identity: IdentityContext) -> MemoryRecord | None:
        record = self._records.get(memory_id)
        if record is None or not self._scope_visible(record, identity):
            return None
        return record

    def forget(self, memory_id: str, *, identity: IdentityContext) -> bool:
        with self._lock:
            record = self.get(memory_id, identity=identity)
            if record is None:
                return False
            if record.scope == MemoryScope.GLOBAL:
                return False
            if record.scope == MemoryScope.TENANT and "memory-admin" not in identity.roles:
                return False
            now = datetime.now(timezone.utc)
            del self._records[memory_id]
            for key, item in tuple(self._records.items()):
                if item.superseded_by == memory_id:
                    self._records[key] = item.model_copy(
                        update={"superseded_by": None, "updated_at": now}
                    )
            self._revision += 1
            self.outbox.append(
                {
                    "event_id": "EVT-" + uuid.uuid4().hex[:20].upper(),
                    "event_type": "memory.erased",
                    "aggregate_id": memory_id,
                    "tenant_id": record.tenant_id,
                    "user_id": record.user_id,
                    "created_at": now.isoformat(),
                }
            )
            return True


    def approve(self, memory_id: str, *, identity: IdentityContext) -> bool:
        if "memory-admin" not in identity.roles:
            return False
        with self._lock:
            record = self.get(memory_id, identity=identity)
            if record is None or record.status != MemoryStatus.PROVISIONAL:
                return False
            now = datetime.now(timezone.utc)
            duplicate = next(
                (
                    item
                    for item in self._records.values()
                    if item.status == MemoryStatus.ACTIVE
                    and item.memory_type == record.memory_type
                    and item.scope == record.scope
                    and item.tenant_id == record.tenant_id
                    and item.user_id == record.user_id
                    and item.content_hash == record.content_hash
                ),
                None,
            )
            if duplicate is not None:
                self._records[memory_id] = record.model_copy(
                    update={
                        "status": MemoryStatus.SUPERSEDED,
                        "effective_until": now,
                        "superseded_by": duplicate.memory_id,
                        "updated_at": now,
                    }
                )
                event_type = "memory.approval_deduplicated"
                superseded_id = None
            else:
                superseded = None
                if record.memory_type in {MemoryType.FACT, MemoryType.PREFERENCE}:
                    superseded = next(
                        (
                            item
                            for item in self._records.values()
                            if item.status == MemoryStatus.ACTIVE
                            and item.memory_type == record.memory_type
                            and item.scope == record.scope
                            and item.tenant_id == record.tenant_id
                            and item.user_id == record.user_id
                            and item.subject.casefold() == record.subject.casefold()
                            and (item.predicate or "").casefold()
                            == (record.predicate or "").casefold()
                            and item.memory_id != memory_id
                        ),
                        None,
                    )
                if superseded is not None:
                    self._records[superseded.memory_id] = superseded.model_copy(
                        update={
                            "status": MemoryStatus.SUPERSEDED,
                            "effective_until": now,
                            "superseded_by": memory_id,
                            "updated_at": now,
                        }
                    )
                self._records[memory_id] = record.model_copy(
                    update={"status": MemoryStatus.ACTIVE, "updated_at": now}
                )
                event_type = "memory.approved"
                superseded_id = superseded.memory_id if superseded else None
            self._revision += 1
            self.outbox.append(
                {
                    "event_id": "EVT-" + uuid.uuid4().hex[:20].upper(),
                    "event_type": event_type,
                    "aggregate_id": memory_id,
                    "tenant_id": record.tenant_id,
                    "user_id": record.user_id,
                    "superseded_memory_id": superseded_id,
                    "created_at": now.isoformat(),
                }
            )
            return True


class PostgresMemoryRepository:
    """Transactional durable repository with exact and lexical discovery paths."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    @staticmethod
    def _row_to_record(row: dict[str, object]) -> MemoryRecord:
        return MemoryRecord.model_validate(row)

    @staticmethod
    def _set_scope(cursor: object, identity: IdentityContext) -> None:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (identity.tenant_id,))
        cursor.execute("SELECT set_config('app.user_id', %s, true)", (identity.user_id,))
        cursor.execute(
            "SELECT set_config('app.is_memory_admin', %s, true)",
            ("true" if "memory-admin" in identity.roles else "false",),
        )

    def ping(self) -> bool:
        import psycopg

        try:
            with psycopg.connect(self.database_url, connect_timeout=3) as connection:
                row = connection.execute(
                    """
                    SELECT to_regclass('public.agent_memory') IS NOT NULL
                       AND to_regclass('public.agent_outbox') IS NOT NULL
                    """
                ).fetchone()
                return bool(row and row[0])
        except Exception:
            return False

    def version(self, identity: IdentityContext | None = None) -> str:
        import psycopg

        from psycopg.rows import dict_row

        sql = """
            SELECT coalesce(max(updated_at)::text, 'empty') AS updated_at,
                   count(*)::text AS count
            FROM agent_memory
            WHERE status IN ('active', 'provisional')
              AND (%s IS NULL OR tenant_id IS NULL OR tenant_id = %s)
        """
        tenant_id = identity.tenant_id if identity else None
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                if identity is not None:
                    self._set_scope(cursor, identity)
                cursor.execute(sql, (tenant_id, tenant_id))
                row = cursor.fetchone() or {"updated_at": "empty", "count": "0"}
        payload = f"{row['updated_at']}:{row['count']}:{tenant_id or 'all'}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def enumerate_exact(
        self,
        *,
        identity: IdentityContext,
        memory_types: Sequence[MemoryType],
        limit: int,
    ) -> list[MemoryRecord]:
        import psycopg

        from psycopg.rows import dict_row

        sql = """
            SELECT memory_id, memory_type, status, scope, tenant_id, user_id, subject,
                   predicate, value, content, content_hash, confidence, provenance,
                   source_run_id, source_ids, effective_from, effective_until,
                   superseded_by, created_at, updated_at, metadata
            FROM agent_memory
            WHERE status = 'active'
              AND memory_type = ANY(%s)
              AND effective_from <= now()
              AND (effective_until IS NULL OR effective_until > now())
              AND (
                    scope = 'global'
                 OR (scope = 'tenant' AND tenant_id = %s)
                 OR (scope = 'user' AND tenant_id = %s AND user_id = %s)
              )
            ORDER BY CASE memory_type WHEN 'policy' THEN 0 ELSE 1 END,
                     subject, updated_at DESC
            LIMIT %s
        """
        values = [item.value for item in memory_types]
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                self._set_scope(cursor, identity)
                cursor.execute(
                    sql,
                    (values, identity.tenant_id, identity.tenant_id, identity.user_id, limit),
                )
                return [self._row_to_record(row) for row in cursor.fetchall()]

    def search(
        self,
        *,
        identity: IdentityContext,
        query: str,
        memory_types: Sequence[MemoryType],
        limit: int,
    ) -> list[MemoryRecord]:
        import psycopg

        from psycopg.rows import dict_row

        sql = """
            SELECT memory_id, memory_type, status, scope, tenant_id, user_id, subject,
                   predicate, value, content, content_hash, confidence, provenance,
                   source_run_id, source_ids, effective_from, effective_until,
                   superseded_by, created_at, updated_at, metadata,
                   ts_rank_cd(search_vector, websearch_to_tsquery('simple', %s)) AS rank
            FROM agent_memory
            WHERE status = 'active'
              AND memory_type = ANY(%s)
              AND effective_from <= now()
              AND (effective_until IS NULL OR effective_until > now())
              AND (
                    scope = 'global'
                 OR (scope = 'tenant' AND tenant_id = %s)
                 OR (scope = 'user' AND tenant_id = %s AND user_id = %s)
              )
              AND search_vector @@ websearch_to_tsquery('simple', %s)
            ORDER BY rank DESC, updated_at DESC
            LIMIT %s
        """
        values = [item.value for item in memory_types]
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                self._set_scope(cursor, identity)
                cursor.execute(
                    sql,
                    (
                        query,
                        values,
                        identity.tenant_id,
                        identity.tenant_id,
                        identity.user_id,
                        query,
                        limit,
                    ),
                )
                return [self._row_to_record(row) for row in cursor.fetchall()]

    @staticmethod
    def _scope_values(
        final_scope: MemoryScope, identity: IdentityContext
    ) -> tuple[str | None, str | None]:
        if final_scope == MemoryScope.GLOBAL:
            return None, None
        if final_scope == MemoryScope.TENANT:
            return identity.tenant_id, None
        return identity.tenant_id, identity.user_id

    def promote(
        self,
        *,
        candidate: MemoryCandidate,
        identity: IdentityContext,
        final_scope: MemoryScope,
        status: MemoryStatus,
    ) -> tuple[MemoryRecord, bool, str | None]:
        import psycopg

        from psycopg.rows import dict_row

        tenant_id, user_id = self._scope_values(final_scope, identity)
        digest = content_hash(candidate)
        now = datetime.now(timezone.utc)
        memory_id = "MEM-" + uuid.uuid4().hex[:20].upper()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    self._set_scope(cursor, identity)
                    logical_slot = "|".join(
                        (
                            candidate.memory_type.value,
                            final_scope.value,
                            tenant_id or "",
                            user_id or "",
                            candidate.subject.casefold(),
                            (candidate.predicate or "").casefold(),
                        )
                    )
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (logical_slot,),
                    )
                    cursor.execute(
                        """
                        SELECT memory_id, memory_type, status, scope, tenant_id, user_id,
                               subject, predicate, value, content, content_hash, confidence,
                               provenance, source_run_id, source_ids, effective_from,
                               effective_until, superseded_by, created_at, updated_at, metadata
                        FROM agent_memory
                        WHERE status = 'active' AND memory_type = %s AND scope = %s
                          AND tenant_id IS NOT DISTINCT FROM %s
                          AND user_id IS NOT DISTINCT FROM %s
                          AND content_hash = %s
                        FOR UPDATE
                        """,
                        (
                            candidate.memory_type.value,
                            final_scope.value,
                            tenant_id,
                            user_id,
                            digest,
                        ),
                    )
                    duplicate = cursor.fetchone()
                    if duplicate:
                        return self._row_to_record(duplicate), True, None

                    superseded_id: str | None = None
                    if candidate.memory_type in {MemoryType.FACT, MemoryType.PREFERENCE}:
                        cursor.execute(
                            """
                            SELECT memory_id
                            FROM agent_memory
                            WHERE status = 'active' AND memory_type = %s AND scope = %s
                              AND tenant_id IS NOT DISTINCT FROM %s
                              AND user_id IS NOT DISTINCT FROM %s
                              AND lower(subject) = lower(%s)
                              AND lower(coalesce(predicate, '')) = lower(coalesce(%s, ''))
                              AND content_hash <> %s
                            ORDER BY updated_at DESC
                            LIMIT 1 FOR UPDATE
                            """,
                            (
                                candidate.memory_type.value,
                                final_scope.value,
                                tenant_id,
                                user_id,
                                candidate.subject,
                                candidate.predicate,
                                digest,
                            ),
                        )
                        row = cursor.fetchone()
                        superseded_id = str(row["memory_id"]) if row else None

                    cursor.execute(
                        """
                        INSERT INTO agent_memory (
                            memory_id, memory_type, status, scope, tenant_id, user_id,
                            subject, predicate, value, content, content_hash, confidence,
                            provenance, source_run_id, source_ids, effective_from,
                            effective_until, metadata, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        RETURNING memory_id, memory_type, status, scope, tenant_id, user_id,
                                  subject, predicate, value, content, content_hash, confidence,
                                  provenance, source_run_id, source_ids, effective_from,
                                  effective_until, superseded_by, created_at, updated_at, metadata
                        """,
                        (
                            memory_id,
                            candidate.memory_type.value,
                            status.value,
                            final_scope.value,
                            tenant_id,
                            user_id,
                            candidate.subject,
                            candidate.predicate,
                            candidate.value,
                            candidate.content,
                            digest,
                            candidate.confidence,
                            candidate.provenance.value,
                            candidate.source_run_id,
                            list(candidate.source_ids),
                            candidate.effective_from or now,
                            candidate.effective_until,
                            json.dumps(candidate.metadata),
                            now,
                            now,
                        ),
                    )
                    record = self._row_to_record(cursor.fetchone())
                    if superseded_id and status == MemoryStatus.ACTIVE:
                        cursor.execute(
                            """
                            UPDATE agent_memory
                            SET status = 'superseded', effective_until = %s,
                                superseded_by = %s, updated_at = %s
                            WHERE memory_id = %s
                            """,
                            (now, memory_id, now, superseded_id),
                        )
                    cursor.execute(
                        """
                        INSERT INTO agent_outbox (
                            event_id, aggregate_type, aggregate_id, event_type, tenant_id,
                            user_id, payload
                        ) VALUES (%s, 'memory', %s, 'memory.promoted', %s, %s, %s::jsonb)
                        """,
                        (
                            "EVT-" + uuid.uuid4().hex[:20].upper(),
                            memory_id,
                            tenant_id,
                            user_id,
                            json.dumps(
                                {
                                    "memory_id": memory_id,
                                    "memory_type": candidate.memory_type.value,
                                    "scope": final_scope.value,
                                    "superseded_memory_id": superseded_id,
                                }
                            ),
                        ),
                    )
                    return (
                        record,
                        False,
                        superseded_id if status == MemoryStatus.ACTIVE else None,
                    )

    def get(self, memory_id: str, *, identity: IdentityContext) -> MemoryRecord | None:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                self._set_scope(cursor, identity)
                cursor.execute(
                    """
                    SELECT memory_id, memory_type, status, scope, tenant_id, user_id, subject,
                           predicate, value, content, content_hash, confidence, provenance,
                           source_run_id, source_ids, effective_from, effective_until,
                           superseded_by, created_at, updated_at, metadata
                    FROM agent_memory
                    WHERE memory_id = %s
                    """,
                    (memory_id,),
                )
                row = cursor.fetchone()
        return self._row_to_record(row) if row else None

    def forget(self, memory_id: str, *, identity: IdentityContext) -> bool:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    self._set_scope(cursor, identity)
                    cursor.execute(
                        """
                        SELECT memory_id, scope, tenant_id, user_id
                        FROM agent_memory
                        WHERE memory_id = %s
                        FOR UPDATE
                        """,
                        (memory_id,),
                    )
                    record = cursor.fetchone()
                    if not record or record["scope"] == MemoryScope.GLOBAL.value:
                        return False
                    if (
                        record["scope"] == MemoryScope.TENANT.value
                        and "memory-admin" not in identity.roles
                    ):
                        return False
                    cursor.execute(
                        """
                        INSERT INTO agent_outbox (
                            event_id, aggregate_type, aggregate_id, event_type, tenant_id,
                            user_id, payload
                        ) VALUES (%s, 'memory', %s, 'memory.erased', %s, %s, '{}'::jsonb)
                        """,
                        (
                            "EVT-" + uuid.uuid4().hex[:20].upper(),
                            memory_id,
                            record["tenant_id"],
                            record["user_id"],
                        ),
                    )
                    cursor.execute("DELETE FROM agent_memory WHERE memory_id = %s", (memory_id,))
                    return cursor.rowcount > 0


    def approve(self, memory_id: str, *, identity: IdentityContext) -> bool:
        if "memory-admin" not in identity.roles:
            return False
        import psycopg
        from psycopg.rows import dict_row

        now = datetime.now(timezone.utc)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    self._set_scope(cursor, identity)
                    cursor.execute(
                        """
                        SELECT memory_id, memory_type, status, scope, tenant_id, user_id,
                               subject, predicate, content_hash
                        FROM agent_memory
                        WHERE memory_id = %s AND status = 'provisional' AND tenant_id = %s
                        FOR UPDATE
                        """,
                        (memory_id, identity.tenant_id),
                    )
                    record = cursor.fetchone()
                    if not record:
                        return False
                    logical_slot = "|".join(
                        (
                            str(record["memory_type"]),
                            str(record["scope"]),
                            str(record["tenant_id"] or ""),
                            str(record["user_id"] or ""),
                            str(record["subject"]).casefold(),
                            str(record["predicate"] or "").casefold(),
                        )
                    )
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (logical_slot,),
                    )
                    cursor.execute(
                        """
                        SELECT memory_id FROM agent_memory
                        WHERE status = 'active' AND memory_type = %s AND scope = %s
                          AND tenant_id IS NOT DISTINCT FROM %s
                          AND user_id IS NOT DISTINCT FROM %s
                          AND content_hash = %s
                        LIMIT 1 FOR UPDATE
                        """,
                        (
                            record["memory_type"],
                            record["scope"],
                            record["tenant_id"],
                            record["user_id"],
                            record["content_hash"],
                        ),
                    )
                    duplicate = cursor.fetchone()
                    superseded_id: str | None = None
                    if duplicate:
                        cursor.execute(
                            """
                            UPDATE agent_memory
                            SET status='superseded', effective_until=%s, superseded_by=%s,
                                updated_at=%s
                            WHERE memory_id=%s
                            """,
                            (now, duplicate["memory_id"], now, memory_id),
                        )
                        event_type = "memory.approval_deduplicated"
                    else:
                        if record["memory_type"] in {
                            MemoryType.FACT.value,
                            MemoryType.PREFERENCE.value,
                        }:
                            cursor.execute(
                                """
                                SELECT memory_id FROM agent_memory
                                WHERE status='active' AND memory_type=%s AND scope=%s
                                  AND tenant_id IS NOT DISTINCT FROM %s
                                  AND user_id IS NOT DISTINCT FROM %s
                                  AND lower(subject)=lower(%s)
                                  AND lower(coalesce(predicate,''))=
                                      lower(coalesce(%s,''))
                                  AND memory_id <> %s
                                ORDER BY updated_at DESC
                                LIMIT 1 FOR UPDATE
                                """,
                                (
                                    record["memory_type"],
                                    record["scope"],
                                    record["tenant_id"],
                                    record["user_id"],
                                    record["subject"],
                                    record["predicate"],
                                    memory_id,
                                ),
                            )
                            conflict = cursor.fetchone()
                            superseded_id = str(conflict["memory_id"]) if conflict else None
                        if superseded_id:
                            cursor.execute(
                                """
                                UPDATE agent_memory
                                SET status='superseded', effective_until=%s, superseded_by=%s,
                                    updated_at=%s
                                WHERE memory_id=%s
                                """,
                                (now, memory_id, now, superseded_id),
                            )
                        cursor.execute(
                            """
                            UPDATE agent_memory SET status='active', updated_at=%s
                            WHERE memory_id=%s AND status='provisional'
                            """,
                            (now, memory_id),
                        )
                        event_type = "memory.approved"
                    cursor.execute(
                        """
                        INSERT INTO agent_outbox (
                            event_id, aggregate_type, aggregate_id, event_type, tenant_id,
                            user_id, payload
                        ) VALUES (%s, 'memory', %s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            "EVT-" + uuid.uuid4().hex[:20].upper(),
                            memory_id,
                            event_type,
                            record["tenant_id"],
                            record["user_id"],
                            json.dumps({"superseded_memory_id": superseded_id}),
                        ),
                    )
                    return True

