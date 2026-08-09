from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

CHECKS: dict[str, list[str]] = {
    "data/papers/paper2.txt": [
        "eRAG",
        "Computational Efficiency",
        "2.468 times faster",
        "30 to 48 times",
    ],
    "data/course/00.pdf": [
        "Agentic RAG",
        "standard RAG",
        "reason",
        "plan",
    ],
    "data/course/01.pdf": [
        "Brain",
        "Tools",
        "Planner",
        "Memory",
    ],
    "data/course/02.pdf": [
        "ReAct",
        "Observation",
        "Plan-and-Execute",
    ],
    "data/course/04.pdf": [
        "Basic RAG",
        "Agentic RAG",
        "QueryEngineTool",
    ],
}


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except (ImportError, OSError, ValueError):
        pass

    with tempfile.NamedTemporaryFile(suffix=".txt") as output:
        try:
            subprocess.run(
                ["pdftotext", str(path), output.name],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            return ""
        return Path(output.name).read_text(encoding="utf-8", errors="ignore")


def _read_source(path: Path) -> str:
    if not path.exists():
        return ""
    if path.suffix.casefold() == ".pdf":
        return _read_pdf(path)
    return path.read_text(encoding="utf-8", errors="ignore")


def build_report() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for relative_path, required_terms in CHECKS.items():
        path = ROOT / relative_path
        text = _read_source(path)
        missing = [term for term in required_terms if term.casefold() not in text.casefold()]
        results.append(
            {
                "file": relative_path,
                "exists": path.exists(),
                "extracted_characters": len(text),
                "required_terms": required_terms,
                "missing_terms": missing,
                "passed": path.exists() and bool(text.strip()) and not missing,
            }
        )
    return {"passed": all(result["passed"] for result in results), "checks": results}


def main() -> None:
    report = build_report()
    output = ROOT / "artifacts/corpus-audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
