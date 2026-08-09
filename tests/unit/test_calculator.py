import pytest

from nvidia_agentic_rag.tools.calculator import safe_calculate


def test_basic_math() -> None:
    assert safe_calculate("125 * 5") == "625"
    assert safe_calculate("(10 + 2) / 4") == "3"


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "x + 1",
        "(1).__class__",
    ],
)
def test_rejects_code_execution(expression: str) -> None:
    with pytest.raises(ValueError):
        safe_calculate(expression)
