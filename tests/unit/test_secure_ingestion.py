from __future__ import annotations

import pytest
from pydantic import SecretStr

from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.policy import DocumentPolicyRecord
from nvidia_agentic_rag.rag import CorpusIndexManager, CorpusSpec


class Document:
    def __init__(self, path):
        self.id_ = str(path)
        self.metadata = {"file_name": path.name, "file_path": str(path)}


class Registry:
    def __init__(self, record=None):
        self.record = record

    def get(self, corpus, relative_path):
        return self.record

    def fingerprint(self):
        return "registry-v1"


def settings_for(tmp_path):
    return Settings(
        environment="test",
        nvidia_api_key=SecretStr("test-key"),
        data_dir=tmp_path,
        course_data_dir=tmp_path,
        papers_data_dir=tmp_path,
        storage_dir=tmp_path / "storage",
        _env_file=None,
    )


def manager(tmp_path, registry):
    return CorpusIndexManager(
        settings_for(tmp_path),
        llm=object(),
        embed_model=object(),
        spec=CorpusSpec(
            name="private-docs",
            source_type="paper",
            data_dir=tmp_path,
            persist_name="private",
            top_k=4,
            min_score=0.3,
            candidate_multiplier=2,
            tool_name="private_tool",
            tool_description="private",
        ),
        document_registry=registry,
        context_broker=object(),
    )


def policy_record(**updates):
    values = {
        "corpus": "private-docs",
        "relative_path": "policy.pdf",
        "document_id": "policy-1",
        "tenant_id": "tenant-a",
        "classification": "confidential",
        "is_public": False,
        "allowed_roles": ["architect"],
        "allowed_purposes": ["architecture-review"],
        "source_version": 3,
        "policy_version": "p1",
    }
    values.update(updates)
    return DocumentPolicyRecord.model_validate(values)


def test_secure_ingestion_attaches_authoritative_metadata(tmp_path) -> None:
    path = tmp_path / "policy.pdf"
    path.write_bytes(b"pdf-content")
    document = Document(path)
    manager(tmp_path, Registry(policy_record()))._prepare_documents([document])
    assert document.metadata["tenant_id"] == "tenant-a"
    assert document.metadata["classification"] == "confidential"
    assert document.metadata["source_version"] == 3
    assert document.metadata["content_hash"]


def test_secure_ingestion_fails_closed_when_registry_record_missing(tmp_path) -> None:
    path = tmp_path / "policy.pdf"
    path.write_bytes(b"pdf-content")
    with pytest.raises(ValueError, match="Security metadata is required"):
        manager(tmp_path, Registry())._prepare_documents([Document(path)])


def test_secure_ingestion_rejects_content_hash_mismatch(tmp_path) -> None:
    path = tmp_path / "policy.pdf"
    path.write_bytes(b"pdf-content")
    with pytest.raises(ValueError, match="Content hash mismatch"):
        manager(
            tmp_path,
            Registry(policy_record(content_hash="not-the-current-hash")),
        )._prepare_documents([Document(path)])
