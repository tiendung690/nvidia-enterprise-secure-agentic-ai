from __future__ import annotations

from nvidia_agentic_rag.grounding.citations import CitationPolicy, validate_citations
from nvidia_agentic_rag.schemas import SourceReference


def source(citation_id: str = "SABC123") -> SourceReference:
    return SourceReference(
        citation_id=citation_id,
        source_id="paper:chunk-1",
        corpus="research-papers",
        file_name="paper2.txt",
        excerpt="Evidence",
    )


def test_accepts_known_citation() -> None:
    audit = validate_citations(
        "eRAG evaluates each document independently [SABC123].",
        [source()],
        CitationPolicy(minimum_coverage=0.5),
    )
    assert audit.valid
    assert audit.coverage == 1.0


def test_rejects_unknown_citation() -> None:
    audit = validate_citations(
        "The paper reports a speedup [SFFFFFF].",
        [source()],
        CitationPolicy(minimum_coverage=0.0),
    )
    assert not audit.valid
    assert audit.unknown_ids == ["SFFFFFF"]


def test_requires_citation_when_sources_exist() -> None:
    audit = validate_citations(
        "The paper reports a speedup of 2.47 times.",
        [source()],
        CitationPolicy(minimum_coverage=0.5),
    )
    assert not audit.valid
    assert any("no citation" in error.lower() for error in audit.errors)


def test_markdown_table_rows_are_counted_as_claim_units() -> None:
    answer = """
| Metric | Result | Citation |
|---|---|---|
| Inference speed | 2.468 times faster | [SABC123] |
| Memory | 7 to 15 times more efficient | [SABC123] |
"""
    audit = validate_citations(
        answer,
        [source()],
        CitationPolicy(minimum_coverage=1.0),
    )
    assert audit.valid
    assert audit.claim_count == 2
    assert audit.cited_claim_count == 2
    assert audit.coverage == 1.0


def test_uncited_summary_after_cited_table_fails_coverage() -> None:
    answer = """
| Metric | Result | Citation |
|---|---|---|
| Inference speed | 2.468 times faster | [SABC123] |

In summary, the method is 2.5 times faster.
"""
    audit = validate_citations(
        answer,
        [source()],
        CitationPolicy(minimum_coverage=1.0),
    )
    assert not audit.valid
    assert audit.claim_count == 2
    assert audit.cited_claim_count == 1
    assert audit.coverage == 0.5


def test_non_applicable_audit_uses_null_coverage() -> None:
    audit = validate_citations("Blocked request.", [], applicable=False)
    assert audit.valid
    assert audit.applicable is False
    assert audit.coverage is None


def test_conservative_repair_removes_uncited_summary_without_inventing_citation() -> None:
    from nvidia_agentic_rag.grounding.citations import repair_citations_conservatively

    answer = """
| Metric | Result | Citation |
|---|---|---|
| Inference speed | 2.468 times faster | [SABC123] |

In summary, the method is 2.5 times faster.
"""
    repair = repair_citations_conservatively(answer, [source()])
    assert "In summary" not in repair.answer
    assert "[SABC123]" in repair.answer
    assert repair.removed_claim_count == 1
    audit = validate_citations(
        repair.answer,
        [source()],
        CitationPolicy(minimum_coverage=1.0),
    )
    assert audit.valid


def test_conservative_repair_strips_unknown_citation_and_drops_claim() -> None:
    from nvidia_agentic_rag.grounding.citations import repair_citations_conservatively

    repair = repair_citations_conservatively(
        "The paper reports a 9 times speedup [SFFFFFF].",
        [source()],
    )
    assert "SFFFFFF" not in repair.answer
    assert repair.answer == ""
    assert repair.removed_claim_count == 1


def test_claim_extraction_ignores_headings_and_fenced_code_but_counts_bullets() -> None:
    from nvidia_agentic_rag.grounding.citations import extract_claim_units

    answer = """
# Results

```python
value = 42
```

- The method is 2 times faster [SABC123].
- Background only
---
The system provides retrieval [SABC123].
"""
    units = extract_claim_units(answer)
    assert [unit.kind for unit in units] == ["bullet", "sentence"]


def test_repair_preserves_code_headings_cited_bullets_and_removes_uncited_rows() -> None:
    from nvidia_agentic_rag.grounding.citations import repair_citations_conservatively

    answer = """
## Evidence

```text
value = 42
```

- The method is supported [SABC123].
- The method is 9 times faster.

| Metric | Result | Citation |
|---|---|---|
| Speed | 2 times faster | [SABC123] |
| Memory | 8 times better | |
"""
    repair = repair_citations_conservatively(answer, [source()])
    assert "## Evidence" in repair.answer
    assert "value = 42" in repair.answer
    assert "supported [SABC123]" in repair.answer
    assert "9 times faster" not in repair.answer
    assert "8 times better" not in repair.answer
    assert repair.removed_claim_count == 2


def test_empty_text_has_full_coverage_and_no_claims() -> None:
    audit = validate_citations("", [])
    assert audit.coverage == 1.0
    assert audit.claim_count == 0
