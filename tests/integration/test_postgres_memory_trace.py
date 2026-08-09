from __future__ import annotations

import os
import uuid

import pytest

from nvidia_agentic_rag.audit import AuditEvent, PostgresAuditService
from nvidia_agentic_rag.identity import IdentityContext
from nvidia_agentic_rag.memory import (
    MemoryCandidate,
    MemoryScope,
    MemoryService,
    MemoryStatus,
    MemoryType,
    PostgresMemoryRepository,
    ProvenanceKind,
)
from nvidia_agentic_rag.tracing import PostgresTraceRepository, TraceService

pytestmark = pytest.mark.integration


def _urls() -> tuple[str, str]:
    app_url = os.getenv("TEST_DATABASE_URL", "")
    admin_url = os.getenv("TEST_ADMIN_DATABASE_URL", "")
    if not app_url or not admin_url:
        pytest.skip("TEST_DATABASE_URL and TEST_ADMIN_DATABASE_URL are required")
    return app_url, admin_url


def _identity(*, tenant_id: str, user_id: str, roles: tuple[str, ...] = ()) -> IdentityContext:
    return IdentityContext(user_id=user_id, tenant_id=tenant_id, roles=roles)


def _candidate(*, run_id: str, value: str, inferred: bool = False) -> MemoryCandidate:
    return MemoryCandidate(
        memory_type=MemoryType.FACT,
        content=f"Service A uses {value}",
        subject="Service A",
        predicate="uses_database",
        value=value,
        requested_scope=MemoryScope.USER,
        confidence=0.9,
        provenance=(
            ProvenanceKind.MODEL_INFERRED if inferred else ProvenanceKind.DOCUMENT_DERIVED
        ),
        source_run_id=run_id,
        source_ids=("doc-1",),
    )


def _cleanup(admin_url: str, tenant_ids: tuple[str, ...]) -> None:
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(admin_url) as connection, connection.cursor() as cursor:
        values = (list(tenant_ids),)
        cursor.execute("DELETE FROM agent_outbox WHERE tenant_id = ANY(%s)", values)
        cursor.execute("DELETE FROM agent_run_trace WHERE tenant_id = ANY(%s)", values)
        cursor.execute("DELETE FROM security_audit_event WHERE tenant_id = ANY(%s)", values)
        cursor.execute("DELETE FROM agent_memory WHERE tenant_id = ANY(%s)", values)
        connection.commit()


def test_postgres_v6_schema_smoke() -> None:
    _, admin_url = _urls()
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(admin_url) as connection:
        rows = connection.execute(
            """
            SELECT to_regclass('public.agent_memory'),
                   to_regclass('public.agent_run_trace'),
                   to_regclass('public.agent_outbox'),
                   to_regclass('public.security_audit_event')
            """
        ).fetchone()
    assert all(rows)


def test_postgres_memory_trace_audit_and_rls() -> None:
    app_url, admin_url = _urls()
    suffix = uuid.uuid4().hex[:10]
    tenant_a = f"it-tenant-a-{suffix}"
    tenant_b = f"it-tenant-b-{suffix}"
    user_a = _identity(tenant_id=tenant_a, user_id=f"user-a-{suffix}")
    admin_a = _identity(
        tenant_id=tenant_a,
        user_id=f"admin-a-{suffix}",
        roles=("memory-admin",),
    )
    user_b = _identity(tenant_id=tenant_b, user_id=f"user-b-{suffix}")
    admin_b = _identity(
        tenant_id=tenant_b,
        user_id=f"admin-b-{suffix}",
        roles=("memory-admin",),
    )
    repository = PostgresMemoryRepository(app_url)
    memory = MemoryService(repository)
    trace = TraceService(PostgresTraceRepository(app_url))
    audit = PostgresAuditService(app_url)

    try:
        assert repository.ping()
        assert trace.ping()
        assert audit.ping()

        run_a = trace.start(
            request_id=f"req-a-{suffix}",
            session_id=f"session-a-{suffix}",
            identity=user_a,
            purpose="research",
            query="Which database does Service A use?",
            index_version="idx-1",
            memory_version=memory.version(user_a),
            prompt_version="prompt-1",
        )
        trace.complete(
            run_a,
            answer="Service A uses PostgreSQL.",
            latency_ms=10,
            source_ids=["doc-1"],
            tool_names=["rag"],
            memory_reads={"policy": 0, "preference": 0, "semantic": 0},
        )
        assert trace.get(run_a.run_id, identity=user_a) is not None
        assert TraceService(PostgresTraceRepository(app_url)).get(
            run_a.run_id,
            identity=user_b,
        ) is None

        version_before = memory.version(user_a)
        active = memory.promote(
            [_candidate(run_id=run_a.run_id, value="PostgreSQL")],
            identity=user_a,
        ).decisions[0]
        assert active.status == MemoryStatus.ACTIVE
        assert memory.version(user_a) != version_before

        provisional = memory.promote(
            [_candidate(run_id=run_a.run_id, value="AlloyDB", inferred=True)],
            identity=user_a,
        ).decisions[0]
        assert provisional.status == MemoryStatus.PROVISIONAL
        assert provisional.superseded_memory_id is None
        assert memory.approve(provisional.memory_id or "", identity=admin_a)
        assert repository.get(active.memory_id or "", identity=user_a).status == (
            MemoryStatus.SUPERSEDED
        )

        tenant_b_record = memory.promote(
            [_candidate(run_id="run-b", value="Aurora PostgreSQL")],
            identity=user_b,
        ).decisions[0]
        assert repository.get(
            tenant_b_record.memory_id or "", identity=admin_b
        ) is not None
        assert repository.get(tenant_b_record.memory_id or "", identity=admin_a) is None

        event = AuditEvent(
            event_id=f"AE-{suffix}",
            request_id=f"req-a-{suffix}",
            user_id=user_a.user_id,
            tenant_id=user_a.tenant_id,
            purpose="security-audit",
            action="integration-test",
            outcome="allowed",
            policy_version="policy-1",
            query_hash="q" * 64,
        )
        audit.record(event)

        psycopg = pytest.importorskip("psycopg")
        with psycopg.connect(admin_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM agent_outbox WHERE tenant_id=%s",
                (tenant_a,),
            )
            assert cursor.fetchone()[0] >= 2
            cursor.execute(
                "SELECT count(*) FROM security_audit_event WHERE event_id=%s",
                (event.event_id,),
            )
            assert cursor.fetchone()[0] == 1
    finally:
        _cleanup(admin_url, (tenant_a, tenant_b))
