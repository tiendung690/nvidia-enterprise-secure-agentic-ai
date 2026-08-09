from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pydantic import SecretStr

from nvidia_agentic_rag.config import Settings
from nvidia_agentic_rag.rag.index_manager import CorpusIndexManager, CorpusSpec
from nvidia_agentic_rag.rag.provenance import (
    deterministic_node_id,
    extract_section_title,
    filter_nodes_by_score,
)


def manager_for(settings: Settings, data_dir: Path) -> CorpusIndexManager:
    class Registry:
        def fingerprint(self):
            return "test-registry"

    return CorpusIndexManager(
        settings,
        llm=object(),
        embed_model=object(),
        spec=CorpusSpec(
            name="test",
            source_type="course",
            data_dir=data_dir,
            persist_name="test_index",
            top_k=8,
            min_score=0.3,
            candidate_multiplier=2,
            tool_name="test_tool",
            tool_description="test",
        ),
        document_registry=Registry(),
        context_broker=object(),
    )


def settings_for(tmp_path, **overrides) -> Settings:
    values = {
        "environment": "test",
        "nvidia_api_key": SecretStr("test-key"),
        "data_dir": tmp_path / "data",
        "course_data_dir": tmp_path / "data",
        "papers_data_dir": tmp_path / "data",
        "storage_dir": tmp_path / "storage",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_legacy_chunk_size_is_capped_for_nvidia_embedding(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    manager = manager_for(
        settings_for(tmp_path, rag_chunk_size=900, rag_chunk_overlap=120), data_dir
    )
    assert manager.effective_chunking() == (320, 53)


def test_default_chunking_has_headroom(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    manager = manager_for(settings_for(tmp_path), data_dir)
    assert manager.effective_chunking() == (256, 32)


def test_fingerprint_changes_when_corpus_changes(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    file = data_dir / "lesson.txt"
    file.write_text("Basic RAG", encoding="utf-8")
    manager = manager_for(settings_for(tmp_path), data_dir)
    before = manager._fingerprint()
    file.write_text("Basic RAG and Agentic RAG", encoding="utf-8")
    assert manager._fingerprint() != before


def test_deterministic_node_id_is_stable_and_content_sensitive() -> None:
    first = deterministic_node_id(
        corpus="papers", relative_path="paper2.txt", chunk_index=3, text="eRAG evidence"
    )
    same = deterministic_node_id(
        corpus="papers", relative_path="paper2.txt", chunk_index=3, text="eRAG evidence"
    )
    changed = deterministic_node_id(
        corpus="papers", relative_path="paper2.txt", chunk_index=3, text="changed"
    )
    assert first == same
    assert first != changed
    assert "chunk-3" in first


def test_extracts_markdown_and_bold_sections() -> None:
    assert extract_section_title("## Computational Efficiency\nBody") == "Computational Efficiency"
    assert extract_section_title("**The eRAG Approach**\nBody") == "The eRAG Approach"


def test_filters_and_limits_nodes_by_score() -> None:
    nodes = [SimpleNamespace(score=value) for value in (0.9, 0.4, 0.2, None)]
    result = filter_nodes_by_score(nodes, min_score=0.3, limit=1)
    assert [node.score for node in result] == [0.9]
