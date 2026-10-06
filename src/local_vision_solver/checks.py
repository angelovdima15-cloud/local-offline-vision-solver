"""Bounded numeric AST interpreter. Never eval/sympify/execute model strings."""
import ast
import math

import sympy as sp

from .models import NumericCheck


class UnsafeExpression(ValueError):
    pass


def numeric_expression(source: str) -> sp.Expr:
    if len(source) > 300:
        raise UnsafeExpression("expression too long")
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise UnsafeExpression("invalid numeric syntax") from exc
    if len(list(ast.walk(tree))) > 100:
        raise UnsafeExpression("expression too complex")

    def bounded(value: sp.Expr) -> sp.Expr:
        if value.is_Rational and (int(value.p).bit_length() > 4096 or int(value.q).bit_length() > 4096):
            raise UnsafeExpression("intermediate numeric magnitude out of range")
        return value

    def visit(node: ast.AST, depth: int = 0) -> sp.Expr:
        if depth > 20:
            raise UnsafeExpression("expression too deep")
        if isinstance(node, ast.Expression):
            return visit(node.body, depth + 1)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if not math.isfinite(node.value) or abs(node.value) > 10**30:
                raise UnsafeExpression("numeric literal out of range")
            return sp.Rational(str(node.value))
        if isinstance(node, ast.Name) and node.id == "pi":
            return sp.pi
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand, depth + 1)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
            if isinstance(node.op, ast.Add):
                return bounded(left + right)
            if isinstance(node.op, ast.Sub):
                return bounded(left - right)
            if isinstance(node.op, ast.Mult):
                return bounded(left * right)
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise UnsafeExpression("division by zero")
                return bounded(left / right)
            if isinstance(node.op, ast.Pow):
                if not right.is_Rational or abs(float(right)) > 32:
                    raise UnsafeExpression("exponent out of range")
                if left == 0 and right < 0:
                    raise UnsafeExpression("division by zero")
                return bounded(left ** right)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in {"sqrt", "sin", "cos", "tan", "abs"}
                and len(node.args) == 1 and not node.keywords):
            functions = {"sqrt": sp.sqrt, "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "abs": sp.Abs}
            return functions[node.func.id](visit(node.args[0], depth + 1))
        raise UnsafeExpression("only bounded numeric arithmetic is allowed")

    result = visit(tree)
    if result.is_real is not True or result.is_finite is not True:
        raise UnsafeExpression("result must be real and finite")
    return result


def check_equalities(checks: list[NumericCheck]) -> list[dict]:
    results = []
    for check in checks:
        try:
            difference = numeric_expression(check.left) - numeric_expression(check.right)
            valid = difference == 0 or abs(float(difference.evalf(40))) <= check.absolute_tolerance
            results.append({"label": check.label, "left": check.left, "right": check.right,
                            "passed": bool(valid), "error": None})
        except (UnsafeExpression, ArithmeticError, ValueError, OverflowError) as exc:
            results.append({"label": check.label, "left": check.left, "right": check.right,
                            "passed": False, "error": str(exc)})
    return results
