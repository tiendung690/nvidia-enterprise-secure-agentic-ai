from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from nvidia_agentic_rag.schemas import CitationAudit, SourceReference

_CITATION_PATTERN = re.compile(r"\[([SD][A-F0-9]{6})\]")
_ANY_CITATION_PATTERN = re.compile(r"\[([A-Z][A-Z0-9]{5,15})\]")
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
_FACT_SIGNAL_PATTERN = re.compile(
    r"\d|\b(is|are|was|were|has|have|had|uses?|provides?|reports?|improves?|reduces?|"
    r"scales?|supports?|requires?|contains?|consists?|achieves?|enables?|allows?|"
    r"represents?|means?|equals?|returns?|stores?|retrieves?|processes?|evaluates?)\b",
    re.IGNORECASE,
)
_TABLE_SEPARATOR_PATTERN = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
_BULLET_PATTERN = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
_HEADING_PATTERN = re.compile(r"^\s*#{1,6}\s+")


@dataclass(frozen=True)
class CitationPolicy:
    require_when_sources_exist: bool = True
    minimum_coverage: float = 0.70


@dataclass(frozen=True)
class ClaimUnit:
    text: str
    kind: str


@dataclass(frozen=True)
class CitationRepairResult:
    answer: str
    removed_claim_count: int


def extract_citation_ids(answer: str) -> set[str]:
    return set(_CITATION_PATTERN.findall(answer))


def available_citation_ids(sources: Iterable[SourceReference]) -> set[str]:
    return {source.citation_id for source in sources}


def _is_factual(text: str) -> bool:
    normalized = text.strip()
    if len(normalized) < 16:
        return False
    return bool(_FACT_SIGNAL_PATTERN.search(normalized))


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 2


def _is_table_separator(line: str) -> bool:
    return bool(_TABLE_SEPARATOR_PATTERN.match(line.strip()))


def _split_sentences(paragraph: str) -> list[str]:
    normalized = " ".join(paragraph.split())
    if not normalized:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT_PATTERN.split(normalized) if part.strip()]


def extract_claim_units(answer: str) -> list[ClaimUnit]:
    """Extract factual units from prose, bullets, and Markdown tables.

    Markdown table data rows are treated as one claim unit, while headings, separator rows,
    fenced code, and table headers are ignored. This fixes the common false-negative pattern
    where a citation in the final table column was not associated with the quantitative row.
    """

    lines = answer.splitlines()
    units: list[ClaimUnit] = []
    paragraph_lines: list[str] = []
    in_code_fence = False
    table_header_pending = False

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        paragraph = " ".join(paragraph_lines)
        paragraph_lines.clear()
        for sentence in _split_sentences(paragraph):
            if _is_factual(sentence):
                units.append(ClaimUnit(sentence, "sentence"))

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            in_code_fence = not in_code_fence
            index += 1
            continue
        if in_code_fence:
            index += 1
            continue

        if not stripped:
            flush_paragraph()
            table_header_pending = False
            index += 1
            continue

        if _HEADING_PATTERN.match(stripped) or stripped in {"---", "***", "___"}:
            flush_paragraph()
            index += 1
            continue

        if _is_table_line(line):
            flush_paragraph()
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            if _is_table_separator(line):
                table_header_pending = False
                index += 1
                continue
            if _is_table_separator(next_line):
                table_header_pending = True
                index += 1
                continue
            if table_header_pending:
                # The first row after a header/separator sequence is a data row.
                table_header_pending = False
            if _is_factual(stripped):
                units.append(ClaimUnit(stripped, "table_row"))
            index += 1
            continue

        if _BULLET_PATTERN.match(line):
            flush_paragraph()
            if _is_factual(stripped):
                units.append(ClaimUnit(stripped, "bullet"))
            index += 1
            continue

        paragraph_lines.append(stripped)
        index += 1

    flush_paragraph()
    return units


def citation_coverage(answer: str) -> tuple[float, int, int]:
    factual = extract_claim_units(answer)
    if not factual:
        return 1.0, 0, 0
    cited = sum(1 for unit in factual if _CITATION_PATTERN.search(unit.text))
    return cited / len(factual), len(factual), cited


def validate_citations(
    answer: str,
    sources: list[SourceReference],
    policy: CitationPolicy | None = None,
    *,
    applicable: bool = True,
) -> CitationAudit:
    policy = policy or CitationPolicy()
    used = extract_citation_ids(answer)
    available = available_citation_ids(sources)
    unknown = used - available

    if not applicable:
        return CitationAudit(
            applicable=False,
            valid=True,
            used_ids=sorted(used),
            available_ids=sorted(available),
            unknown_ids=sorted(unknown),
            coverage=None,
            claim_count=0,
            cited_claim_count=0,
            errors=[],
        )

    coverage, claim_count, cited_claim_count = citation_coverage(answer)
    errors: list[str] = []

    if unknown:
        errors.append(f"Unknown citation IDs: {sorted(unknown)}")
    if sources and policy.require_when_sources_exist and not used:
        errors.append("Grounded answer contains no citation IDs.")
    if sources and coverage < policy.minimum_coverage:
        errors.append(
            f"Citation coverage {coverage:.2f} is below required "
            f"{policy.minimum_coverage:.2f}."
        )

    return CitationAudit(
        applicable=True,
        valid=not errors,
        used_ids=sorted(used),
        available_ids=sorted(available),
        unknown_ids=sorted(unknown),
        coverage=round(coverage, 4),
        claim_count=claim_count,
        cited_claim_count=cited_claim_count,
        errors=errors,
    )


def _remove_unknown_citations(text: str, available: set[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        return match.group(0) if token in available else ""

    return _ANY_CITATION_PATTERN.sub(replace, text)


def repair_citations_conservatively(
    answer: str,
    sources: list[SourceReference],
) -> CitationRepairResult:
    """Remove uncited factual units without inventing or transferring citations.

    This is deliberately conservative. It is intended as a deterministic final repair for
    strict enterprise mode, especially for uncited summary sentences and Markdown table rows.
    It never appends a citation to a claim based on lexical guesswork. If the remaining answer
    still fails validation, the caller must reject it rather than return an unverified answer.
    """

    available = available_citation_ids(sources)
    cleaned = _remove_unknown_citations(answer, available)
    lines = cleaned.splitlines()
    output: list[str] = []
    paragraph_lines: list[str] = []
    in_code_fence = False
    removed = 0

    def flush_paragraph() -> None:
        nonlocal removed
        if not paragraph_lines:
            return
        paragraph = " ".join(paragraph_lines)
        paragraph_lines.clear()
        kept: list[str] = []
        for sentence in _split_sentences(paragraph):
            if _is_factual(sentence) and not _CITATION_PATTERN.search(sentence):
                removed += 1
                continue
            kept.append(sentence)
        if kept:
            output.append(" ".join(kept))

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            in_code_fence = not in_code_fence
            output.append(line)
            continue
        if in_code_fence:
            output.append(line)
            continue

        if not stripped:
            flush_paragraph()
            if output and output[-1] != "":
                output.append("")
            continue

        if _HEADING_PATTERN.match(stripped) or stripped in {"---", "***", "___"}:
            flush_paragraph()
            output.append(line)
            continue

        if _is_table_line(line):
            flush_paragraph()
            if _is_table_separator(line):
                output.append(line)
            elif _is_factual(stripped) and not _CITATION_PATTERN.search(stripped):
                # Keep probable table headers; drop only factual rows without citations.
                cells = [cell.strip() for cell in stripped.strip("|").split("|")]
                header_like = all(not _FACT_SIGNAL_PATTERN.search(cell) for cell in cells)
                if header_like:
                    output.append(line)
                else:
                    removed += 1
            else:
                output.append(line)
            continue

        if _BULLET_PATTERN.match(line):
            flush_paragraph()
            if _is_factual(stripped) and not _CITATION_PATTERN.search(stripped):
                removed += 1
            else:
                output.append(line)
            continue

        paragraph_lines.append(stripped)

    flush_paragraph()

    # Collapse excessive blank lines and remove empty table shells.
    compact: list[str] = []
    for line in output:
        if line == "" and compact and compact[-1] == "":
            continue
        compact.append(line)
    repaired = "\n".join(compact).strip()
    return CitationRepairResult(answer=repaired, removed_claim_count=removed)
