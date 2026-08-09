from __future__ import annotations

import ast
import operator
from typing import Callable

_ALLOWED_BINARY: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARY: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def safe_calculate(expression: str) -> str:
    """Evaluate a basic arithmetic expression without using Python eval.

    The expression may contain numbers, parentheses, +, -, *, /, //, %, and **.
    Names, function calls, attributes, imports, and other Python syntax are rejected.
    """
    if not expression or len(expression) > 200:
        raise ValueError("Expression must contain between 1 and 200 characters")
    tree = ast.parse(expression, mode="eval")

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINARY:
            left = visit(node.left)
            right = visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("Exponent is outside the permitted range")
            result = _ALLOWED_BINARY[type(node.op)](left, right)
            if abs(result) > 1e18:
                raise ValueError("Result is outside the permitted range")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
            return _ALLOWED_UNARY[type(node.op)](visit(node.operand))
        raise ValueError(f"Unsupported expression element: {type(node).__name__}")

    result = visit(tree)
    return str(int(result)) if result.is_integer() else str(result)
