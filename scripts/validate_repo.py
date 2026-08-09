from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".md", ".toml", ".yml", ".yaml", ".json", ".jsonl", ".txt", ".example"}
SKIP_PARTS = {".git", ".pytest_cache", "__pycache__", "artifacts", "storage"}

# Runtime files must not depend on local inference. Documentation may mention removed course code.
RUNTIME_TARGETS = (
    ROOT / "src",
    ROOT / "tests",
    ROOT / "pyproject.toml",
    ROOT / "docker-compose.yml",
    ROOT / "Dockerfile",
    ROOT / ".env.example",
)
SECRET_TARGETS = (
    ROOT / "src",
    ROOT / "tests",
    ROOT / "scripts",
    ROOT / "docs",
    ROOT / "evaluation",
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "pyproject.toml",
    ROOT / "docker-compose.yml",
    ROOT / "Dockerfile",
)

SECRET_PATTERNS = (
    re.compile(r"nvapi-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
)
FORBIDDEN_RUNTIME = ("ollamaembedding", "ollama_base_url", "nomic-embed-text")


def _is_text_file(path: Path) -> bool:
    return path.name == ".env.example" or path.suffix.casefold() in TEXT_SUFFIXES


def _iter_files(targets: Iterable[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for target in targets:
        candidates = [target] if target.is_file() else target.rglob("*") if target.exists() else []
        for path in candidates:
            if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
                continue
            if not _is_text_file(path) or path in seen:
                continue
            seen.add(path)
            yield path


def main() -> None:
    violations: list[str] = []
    if (ROOT / ".env").exists():
        violations.append(".env must not be included in the distributable repository")

    for path in _iter_files(RUNTIME_TARGETS):
        lower = path.read_text(encoding="utf-8", errors="ignore").casefold()
        for token in FORBIDDEN_RUNTIME:
            if token in lower:
                violations.append(
                    f"Forbidden local-model runtime reference {token}: {path.relative_to(ROOT)}"
                )

    for path in _iter_files(SECRET_TARGETS):
        if path.name == ".env.example":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                violations.append(f"Potential secret in {path.relative_to(ROOT)}")

    if violations:
        raise SystemExit("\n".join(sorted(set(violations))))
    print(
        "Repository validation passed: no packaged .env, exposed API-key pattern, "
        "or local-inference runtime dependency."
    )


if __name__ == "__main__":
    main()
