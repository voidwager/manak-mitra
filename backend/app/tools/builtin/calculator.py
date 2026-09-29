"""Arithmetic the model should not be doing in its head.

Language models are unreliable at multi-step arithmetic, and in an
engineering context a quietly wrong pressure drop is worse than no answer.
This evaluates the expression exactly instead.

**This does not use `eval()`.** The input comes from a language model, which
in turn is influenced by document text and user messages - so it is
attacker-reachable, and `eval()` on attacker-reachable input is remote code
execution. The expression is parsed to an AST and walked, and only the node
types listed below are honoured. Anything else - a name, a call, an
attribute, a subscript, a comprehension - is refused rather than evaluated.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from app.tools.base import Tool, ToolArgumentError, ToolContext, ToolResult

#: The only operators that will be executed. Note the absence of `**` on
#: arbitrary operands is handled separately: exponentiation is the one
#: cheap way to burn a CPU (`9**9**9`), so it is bounded below.
_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

#: Whitelisted functions and constants. Everything is pure and total.
_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "atan": math.atan,
    "degrees": math.degrees,
    "radians": math.radians,
    "floor": math.floor,
    "ceil": math.ceil,
    "pow": math.pow,
}

_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}

#: Guards against an expression that is syntactically small but expensive.
MAX_EXPRESSION_CHARS = 500
MAX_EXPONENT = 64


def evaluate(expression: str) -> float:
    """Evaluate an arithmetic expression safely, or raise ToolArgumentError."""
    expression = (expression or "").strip()
    if not expression:
        raise ToolArgumentError("No expression was provided.")
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise ToolArgumentError(
            f"Expression is too long (limit {MAX_EXPRESSION_CHARS} characters)."
        )

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolArgumentError(f"That is not a valid expression: {exc.msg}") from exc

    try:
        value = _eval(tree.body)
    except ToolArgumentError:
        raise
    except ZeroDivisionError as exc:
        raise ToolArgumentError("Division by zero.") from exc
    except (OverflowError, ValueError) as exc:
        raise ToolArgumentError(f"That calculation is not defined: {exc}") from exc

    if isinstance(value, complex):
        raise ToolArgumentError("The result is a complex number.")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ToolArgumentError("The result is not a finite number.")
    return value


def _eval(node: ast.AST) -> Any:
    """Walk the AST, honouring only the node types explicitly allowed."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ToolArgumentError("Only numbers are allowed in an expression.")
        return node.value

    if isinstance(node, ast.BinOp):
        op = _BINARY.get(type(node.op))
        if op is None:
            raise ToolArgumentError(
                f"The operator '{type(node.op).__name__}' is not allowed."
            )
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ToolArgumentError(
                f"Exponents above {MAX_EXPONENT} are refused - the result would "
                "be too large to compute usefully."
            )
        return op(left, right)

    if isinstance(node, ast.UnaryOp):
        op = _UNARY.get(type(node.op))
        if op is None:
            raise ToolArgumentError("That unary operator is not allowed.")
        return op(_eval(node.operand))

    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise ToolArgumentError(
            f"'{node.id}' is not a known constant. Available: "
            f"{', '.join(sorted(_CONSTANTS))}."
        )

    if isinstance(node, ast.Call):
        # Only a bare whitelisted name may be called - never an attribute,
        # which is how `().__class__` style escapes begin.
        if not isinstance(node.func, ast.Name):
            raise ToolArgumentError("Only plain function calls are allowed.")
        function = _FUNCTIONS.get(node.func.id)
        if function is None:
            raise ToolArgumentError(
                f"'{node.func.id}' is not an available function. Available: "
                f"{', '.join(sorted(_FUNCTIONS))}."
            )
        if node.keywords:
            raise ToolArgumentError("Keyword arguments are not supported.")
        return function(*[_eval(a) for a in node.args])

    raise ToolArgumentError(
        f"'{type(node).__name__}' is not allowed in an expression. Only "
        "arithmetic on numbers is supported."
    )


class CalculatorTool(Tool):
    id = "calculator"
    name = "calculator"
    description = (
        "Evaluate an arithmetic expression exactly. Use this for any "
        "calculation rather than working it out yourself - unit conversions, "
        "pressure drops, flow rates, tolerances, percentages. Supports + - * "
        "/ // % **, parentheses, and the functions sqrt, log, log10, exp, "
        "sin, cos, tan, atan, degrees, radians, floor, ceil, abs, round, "
        "min, max, pow, plus the constants pi and e."
    )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": (
                        "The arithmetic expression, e.g. '2.5 * 1.8 + 32' or "
                        "'sqrt(2 * 9.81 * 4.5)'. Numbers and operators only - "
                        "no variables or units."
                    ),
                }
            },
            "required": ["expression"],
        }

    def run(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        expression = kwargs.get("expression", "")
        value = evaluate(expression)

        # Trim float noise (0.30000000000000004) without lying about precision.
        if isinstance(value, float) and value == int(value) and abs(value) < 1e15:
            rendered = str(int(value))
        elif isinstance(value, float):
            rendered = f"{value:.10g}"
        else:
            rendered = str(value)

        return ToolResult(
            content=f"{expression} = {rendered}",
            data={"expression": expression, "result": value},
        )


__all__ = ["CalculatorTool", "evaluate"]
