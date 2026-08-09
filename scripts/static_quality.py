from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (ROOT / "src", ROOT / "scripts", ROOT / "tests")
MAX_LINE_LENGTH = 100


def main() -> None:
    violations: list[str] = []
    file_count = 0
    line_count = 0

    for target in TARGETS:
        for path in sorted(target.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            file_count += 1
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            line_count += len(lines)
            try:
                ast.parse(text, filename=str(path))
            except SyntaxError as exc:
                violations.append(f"{path.relative_to(ROOT)}:{exc.lineno}: syntax error: {exc.msg}")
            for number, line in enumerate(lines, start=1):
                if len(line) > MAX_LINE_LENGTH:
                    violations.append(
                        f"{path.relative_to(ROOT)}:{number}: "
                        f"line length {len(line)} > {MAX_LINE_LENGTH}"
                    )
                if line.rstrip() != line:
                    violations.append(
                        f"{path.relative_to(ROOT)}:{number}: trailing whitespace"
                    )

    if violations:
        raise SystemExit("\n".join(violations))
    print(
        f"Static quality passed: {file_count} Python files, {line_count} lines, "
        f"valid AST, line length <= {MAX_LINE_LENGTH}, no trailing whitespace."
    )


if __name__ == "__main__":
    main()
