from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from nvidia_agentic_rag.policy.models import DocumentPolicyRecord


class DocumentRegistry(Protocol):
    def get(self, corpus: str, relative_path: str) -> DocumentPolicyRecord | None: ...

    def fingerprint(self) -> str: ...


class JsonDocumentRegistry:
    """Fail-closed local registry used for reproducible development and CI."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._records = self._load()

    @staticmethod
    def _key(corpus: str, relative_path: str) -> tuple[str, str]:
        return corpus.casefold(), relative_path.replace("\\", "/").casefold()

    def _load(self) -> dict[tuple[str, str], DocumentPolicyRecord]:
        if not self.path.exists():
            raise FileNotFoundError(f"Document security manifest not found: {self.path}")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        raw_records = payload.get("documents", [])
        records: dict[tuple[str, str], DocumentPolicyRecord] = {}
        for raw in raw_records:
            record = DocumentPolicyRecord.model_validate(raw)
            key = self._key(record.corpus, record.relative_path)
            if key in records:
                raise ValueError(f"Duplicate document security record: {key}")
            records[key] = record
        return records

    def get(self, corpus: str, relative_path: str) -> DocumentPolicyRecord | None:
        return self._records.get(self._key(corpus, relative_path))

    def fingerprint(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


class PostgresDocumentRegistry:
    """Authoritative registry adapter. Imports psycopg lazily so unit tests stay lightweight."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def get(self, corpus: str, relative_path: str) -> DocumentPolicyRecord | None:
        import psycopg

        sql = """
            SELECT corpus, relative_path, document_id, tenant_id, classification,
                   is_public, owner_department, allowed_roles, allowed_departments,
                   allowed_purposes, shared_with_tenants, source_version,
                   policy_version, valid_from, expires_at, content_hash
            FROM document_registry
            WHERE lower(corpus) = lower(%s)
              AND lower(relative_path) = lower(%s)
              AND active = true
        """
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (corpus, relative_path.replace("\\", "/")))
                row = cursor.fetchone()
                if row is None:
                    return None
                columns = [description.name for description in cursor.description]
                return DocumentPolicyRecord.model_validate(dict(zip(columns, row, strict=True)))

    def fingerprint(self) -> str:
        import psycopg

        sql = """
            SELECT coalesce(max(updated_at)::text, 'empty'), count(*)::text,
                   coalesce(max(policy_version), 'unknown')
            FROM document_registry WHERE active = true
        """
        with psycopg.connect(self.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                payload = ":".join(str(item) for item in cursor.fetchone())
        return hashlib.sha256(payload.encode()).hexdigest()
