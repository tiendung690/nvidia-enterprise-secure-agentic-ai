from __future__ import annotations

import json

import pytest

from nvidia_agentic_rag.data import JsonDocumentRegistry, JsonOrderRepository


def test_json_document_registry_loads_and_fingerprints(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    payload = {
        "documents": [
            {
                "corpus": "c",
                "relative_path": "A.pdf",
                "document_id": "d1",
                "tenant_id": "public",
                "classification": "PUBLIC",
                "is_public": True,
                "source_version": 1,
                "policy_version": "p1",
            }
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    registry = JsonDocumentRegistry(path)
    assert registry.get("C", "a.PDF").document_id == "d1"
    before = registry.fingerprint()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert JsonDocumentRegistry(path).fingerprint() != before


def test_json_document_registry_fails_closed(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        JsonDocumentRegistry(tmp_path / "missing.json")

    path = tmp_path / "duplicate.json"
    record = {
        "corpus": "c",
        "relative_path": "a.pdf",
        "document_id": "d1",
        "tenant_id": "public",
        "classification": "PUBLIC",
        "is_public": True,
        "source_version": 1,
        "policy_version": "p1",
    }
    path.write_text(json.dumps({"documents": [record, record]}), encoding="utf-8")
    with pytest.raises(ValueError):
        JsonDocumentRegistry(path)


def test_json_order_repository_is_tenant_scoped(tmp_path) -> None:
    path = tmp_path / "orders.json"
    path.write_text(
        json.dumps(
            {
                "orders": [
                    {
                        "order_id": "A-1",
                        "tenant_id": "t1",
                        "status": "Delivered",
                        "record_version": 1,
                        "updated_at": "2026-08-05T00:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    repository = JsonOrderRepository(path)
    assert repository.get_order(tenant_id="t1", order_id="A-1") is not None
    assert repository.get_order(tenant_id="t2", order_id="A-1") is None
