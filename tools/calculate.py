"""Safe arithmetic calculator (AUTO_ALLOW). AST whitelist only."""

from __future__ import annotations

import ast
import operator
from typing import Any, Union

Number = Union[int, float]

MAX_EXPR_LEN = 200
MAX_ABS_RESULT = 1e15
MAX_EXPONENT = 12
MAX_BASE_FOR_LARGE_EXP = 1_000_000

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_ALLOWED_FUNCS = {
    "round": round,
    "abs": abs,
    "min": min,
    "max": max,
}


class CalcError(ValueError):
    """Raised when an expression is refused or cannot be evaluated safely."""


def _normalize_percent(expr: str) -> str:
    """Rewrite 17% → (17/100) and 17% of 2350 → ((17/100)*2350)."""
    import re

    s = expr.strip()
    # "17% of 2350" / "17% * 2350"
    s = re.sub(
        r"(?i)(\d+(?:\.\d+)?)\s*%\s*(?:of|×|\*)\s*",
        r"((\1)/100)*",
        s,
    )
    # trailing or mid "17%"
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"((\1)/100)", s)
    return s


def _eval_node(node: ast.AST) -> Number:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    # py3.10 may still emit Num in some paths
    if isinstance(node, ast.Num):  # type: ignore[attr-defined]
        return node.n  # type: ignore[attr-defined]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_EXPONENT:
                raise CalcError(f"Exponent too large (max {MAX_EXPONENT}).")
            if abs(left) > MAX_BASE_FOR_LARGE_EXP and abs(right) > 4:
                raise CalcError("Base too large for this exponent.")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise CalcError("Division by zero.")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise CalcError("Only round/abs/min/max calls are allowed.")
        name = node.func.id
        if name not in _ALLOWED_FUNCS:
            raise CalcError(f"Function '{name}' is not allowed.")
        if node.keywords:
            raise CalcError("Keyword arguments are not allowed.")
        args = [_eval_node(a) for a in node.args]
        if name in {"min", "max"} and len(args) < 2:
            raise CalcError(f"{name}() needs at least two arguments.")
        if name == "round" and not (1 <= len(args) <= 2):
            raise CalcError("round() takes 1 or 2 arguments.")
        if name == "abs" and len(args) != 1:
            raise CalcError("abs() takes one argument.")
        return _ALLOWED_FUNCS[name](*args)
    if isinstance(node, ast.Name):
        raise CalcError("Names/variables are not allowed.")
    if isinstance(node, ast.Attribute):
        raise CalcError("Attribute access is not allowed.")
    raise CalcError(f"Disallowed expression node: {type(node).__name__}")


def safe_calculate(expression: str) -> Number:
    if not isinstance(expression, str):
        raise CalcError("Expression must be a string.")
    raw = expression.strip()
    if not raw:
        raise CalcError("Expression is empty.")
    if len(raw) > MAX_EXPR_LEN:
        raise CalcError(f"Expression too long (max {MAX_EXPR_LEN} characters).")
    # Reject obvious escape hatches before parse
    lowered = raw.lower()
    for bad in ("__", "import", "lambda", "open", "exec", "eval", "os.", "sys."):
        if bad in lowered:
            raise CalcError("Expression contains disallowed content.")
    normalized = _normalize_percent(raw)
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise CalcError(f"Could not parse expression: {exc.msg}") from exc
    # Walk for banned node types early
    for node in ast.walk(tree):
        if isinstance(
            node,
            (
                ast.Attribute,
                ast.Subscript,
                ast.List,
                ast.Dict,
                ast.Set,
                ast.ListComp,
                ast.DictComp,
                ast.SetComp,
                ast.GeneratorExp,
                ast.Await,
                ast.Yield,
                ast.Lambda,
                ast.JoinedStr,
                ast.FormattedValue,
            ),
        ):
            raise CalcError(f"Disallowed syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in _ALLOWED_FUNCS:
            # Names only allowed as call targets checked in _eval_node
            pass
    result = _eval_node(tree)
    if not isinstance(result, (int, float)) or isinstance(result, bool):
        raise CalcError("Result is not a number.")
    if abs(float(result)) > MAX_ABS_RESULT:
        raise CalcError("Result magnitude exceeds the safety cap.")
    return result


def calculate(expression: str) -> str:
    """AUTO_ALLOW tool: evaluate a safe arithmetic expression."""
    from security.gate import Tier, check_permission

    check_permission(
        action="calculate",
        tier=Tier.AUTO_ALLOW,
        description=f"Calculate: {expression}",
    )
    try:
        value = safe_calculate(expression)
    except CalcError as exc:
        return f"Error: {exc}"
    # Prefer int when exact; otherwise round tiny float noise
    if isinstance(value, float):
        if value.is_integer():
            value = int(value)
        else:
            value = round(value, 12)
            if float(value).is_integer():
                value = int(value)
    return str(value)
