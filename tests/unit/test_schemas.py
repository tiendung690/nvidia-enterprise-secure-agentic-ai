import pytest
from pydantic import ValidationError

from nvidia_agentic_rag.schemas import SourceReference


def test_source_reference_normalizes_excerpt() -> None:
    source = SourceReference(
        citation_id="SABC123",
        source_id="id",
        corpus="papers",
        file_name="paper.txt",
        excerpt="a\n  b",
    )
    assert source.excerpt == "a b"


def test_source_reference_rejects_invalid_citation_id() -> None:
    with pytest.raises(ValidationError):
        SourceReference(
            citation_id="S1",
            source_id="id",
            corpus="papers",
            file_name="paper.txt",
        )
