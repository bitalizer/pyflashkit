"""AS3 source printer for the AST.

``AstPrinter.print(node)`` returns a string. Indentation is 4 spaces
by default (configurable via constructor). Parentheses are emitted
only where operator precedence or associativity requires them — no
defensive parens.

Precedence table (higher binds tighter):

    20  primary        Literal, Identifier, ArrayLit, ObjLit, FuncExpr
    19  postfix/member ``.``, ``[]``, ``f()``, ``new``
    17  prefix         ``!``, ``~``, ``-`` (unary), ``typeof``, ``delete``
    14  multiplicative ``*`` ``/`` ``%``
    13  additive       ``+`` ``-``
    12  shift          ``<<`` ``>>`` ``>>>``
    11  relational     ``<`` ``<=`` ``>`` ``>=`` ``is`` ``as`` ``in``
    10  equality       ``==`` ``!=`` ``===`` ``!==``
     9  bit-and        ``&``
     8  bit-xor        ``^``
     7  bit-or         ``|``
     6  logical-and    ``&&``
     5  logical-or     ``||``
     4  ternary        ``? :``
     3  assignment     ``=`` and compound (right-assoc)
"""

from __future__ import annotations

import math

from ..helpers import escape_str
from . import nodes as N


# ── precedence ─────────────────────────────────────────────────────────────

_PRIMARY = 20
_POSTFIX = 19
_PREFIX = 17
_TERNARY = 4
_ASSIGN = 3

_BINARY_PRECEDENCE: dict[str, int] = {
    "*": 14, "/": 14, "%": 14,
    "+": 13, "-": 13,
    "<<": 12, ">>": 12, ">>>": 12,
    "<": 11, "<=": 11, ">": 11, ">=": 11,
    "is": 11, "as": 11, "in": 11,
    "==": 10, "!=": 10, "===": 10, "!==": 10,
    "&": 9,
    "^": 8,
    "|": 7,
    "&&": 6,
    "||": 5,
}


def _precedence_of(node: N.Node) -> int:
    if isinstance(node, (N.Literal, N.Identifier, N.ArrayLiteral,
                         N.ObjectLiteral, N.FunctionExpr)):
        return _PRIMARY
    if isinstance(node, (N.MemberAccess, N.IndexAccess, N.MethodCall,
                         N.NewExpr, N.CastExpr)):
        return _POSTFIX
    if isinstance(node, (N.UnaryOp, N.TypeofExpr, N.DeleteExpr)):
        return _PREFIX
    if isinstance(node, N.BinaryOp):
        return _BINARY_PRECEDENCE.get(node.op, 0)
    if isinstance(node, (N.IsExpr, N.AsExpr, N.InExpr)):
        return 11
    if isinstance(node, N.TernaryOp):
        return _TERNARY
    if isinstance(node, (N.AssignExpr, N.CompoundAssignExpr)):
        return _ASSIGN
    return 0


# ── printer ────────────────────────────────────────────────────────────────


class AstPrinter:
    """AS3 source printer. Hold state for a single print call — create
    a new instance per top-level print, or reset by calling ``print``
    again (state is rebuilt each call)."""

    def __init__(self, indent: str = "    "):
        self._indent_unit = indent
        self._depth = 0
        self._out: list[str] = []

    # Public API ───────────────────────────────────────────────────────────

    def print(self, node: N.Node) -> str:
        self._depth = 0
        self._out = []
        self._print(node)
        return "".join(self._out)

    # Internal plumbing ────────────────────────────────────────────────────

    def _emit(self, text: str) -> None:
        self._out.append(text)

    def _indent(self) -> None:
        self._emit(self._indent_unit * self._depth)

    def _newline(self) -> None:
        self._emit("\n")

    def _print(self, node: N.Node) -> None:
        method_name = f"_p_{type(node).__name__}"
        method = getattr(self, method_name, None)
        if method is None:
            raise NotImplementedError(
                f"AstPrinter has no handler for {type(node).__name__}"
            )
        method(node)

    def _print_expr_in_context(self, node: N.Node, ctx_precedence: int,
                               right_of_right_assoc: bool = False) -> None:
        """Print an expression, wrapping in parens if its precedence is
        lower than ``ctx_precedence``."""
        p = _precedence_of(node)
        # For right-associative operators (``=``, ``?:``), the RIGHT
        # operand at the same precedence doesn't need parens, but the
        # left does. Most binary ops are left-associative so the
        # opposite applies. The caller signals right-associativity by
        # passing ``right_of_right_assoc=True`` when printing the right
        # child of a left-assoc context at equal precedence.
        need_parens = p < ctx_precedence or (
            p == ctx_precedence and right_of_right_assoc
        )
        if need_parens:
            self._emit("(")
            self._print(node)
            self._emit(")")
        else:
            self._print(node)

    # Expression handlers ──────────────────────────────────────────────────

    def _p_Literal(self, node: N.Literal) -> None:
        v = node.value
        if v is None:
            self._emit("null")
        elif isinstance(v, bool):
            # bool before int — bool is a subclass of int in Python
            self._emit("true" if v else "false")
        elif isinstance(v, float):
            if math.isnan(v):
                self._emit("NaN")
            elif math.isinf(v):
                self._emit("-Infinity" if v < 0 else "Infinity")
            else:
                # Prefer Python's repr but collapse trailing ``.0`` to
                # match typical AS3 formatting.
                s = repr(v)
                if s.endswith(".0"):
                    s = s[:-2]
                self._emit(s)
        elif isinstance(v, int):
            self._emit(str(v))
        elif isinstance(v, str):
            self._emit(f'"{escape_str(v)}"')
        else:
            self._emit(str(v))

    def _p_Identifier(self, node: N.Identifier) -> None:
        self._emit(node.name)

    def _p_MemberAccess(self, node: N.MemberAccess) -> None:
        self._print_expr_in_context(node.target, _POSTFIX)
        self._emit(".")
        self._emit(node.name)

    def _p_IndexAccess(self, node: N.IndexAccess) -> None:
        self._print_expr_in_context(node.target, _POSTFIX)
        self._emit("[")
        self._print(node.index)
        self._emit("]")

    def _p_MethodCall(self, node: N.MethodCall) -> None:
        self._print_expr_in_context(node.callee, _POSTFIX)
        self._emit("(")
        for i, arg in enumerate(node.args):
            if i:
                self._emit(", ")
            # Arguments are in "primary" position — assignment/ternary
            # are allowed without parens. Use precedence 0 to never
            # parenthesise.
            self._print(arg)
        self._emit(")")

    def _p_NewExpr(self, node: N.NewExpr) -> None:
        self._emit("new ")
        self._print_expr_in_context(node.callee, _POSTFIX)
        self._emit("(")
        for i, arg in enumerate(node.args):
            if i:
                self._emit(", ")
            self._print(arg)
        self._emit(")")

    def _p_BinaryOp(self, node: N.BinaryOp) -> None:
        prec = _BINARY_PRECEDENCE.get(node.op, 0)
        # Left-associative: left child allowed at equal precedence, right
        # child must be strictly greater.
        self._print_expr_in_context(node.left, prec)
        self._emit(f" {node.op} ")
        self._print_expr_in_context(node.right, prec,
                                    right_of_right_assoc=True)

    def _p_UnaryOp(self, node: N.UnaryOp) -> None:
        # ``typeof`` and ``delete`` are their own nodes; UnaryOp covers
        # !, ~, -, +, ++, --.
        op = node.op
        self._emit(op)
        self._print_expr_in_context(node.operand, _PREFIX)

    def _p_TernaryOp(self, node: N.TernaryOp) -> None:
        self._print_expr_in_context(node.cond, _TERNARY + 1)
        self._emit(" ? ")
        # Ternary is right-assoc; middle and right arms allow ternary
        # without parens.
        self._print_expr_in_context(node.then_expr, _TERNARY)
        self._emit(" : ")
        self._print_expr_in_context(node.else_expr, _TERNARY)

    def _p_AssignExpr(self, node: N.AssignExpr) -> None:
        self._print_expr_in_context(node.target, _ASSIGN + 1)
        self._emit(" = ")
        # Right-assoc: nested = on the right side is fine.
        self._print_expr_in_context(node.value, _ASSIGN)

    def _p_CompoundAssignExpr(self, node: N.CompoundAssignExpr) -> None:
        self._print_expr_in_context(node.target, _ASSIGN + 1)
        self._emit(f" {node.op} ")
        self._print_expr_in_context(node.value, _ASSIGN)

    def _p_CastExpr(self, node: N.CastExpr) -> None:
        self._emit(node.type_name)
        self._emit("(")
        self._print(node.value)
        self._emit(")")

    def _p_IsExpr(self, node: N.IsExpr) -> None:
        self._print_expr_in_context(node.value, 11)
        self._emit(" is ")
        self._print_expr_in_context(node.type_ref, 11,
                                    right_of_right_assoc=True)

    def _p_AsExpr(self, node: N.AsExpr) -> None:
        self._print_expr_in_context(node.value, 11)
        self._emit(" as ")
        self._print_expr_in_context(node.type_ref, 11,
                                    right_of_right_assoc=True)

    def _p_TypeofExpr(self, node: N.TypeofExpr) -> None:
        self._emit("typeof ")
        self._print_expr_in_context(node.value, _PREFIX)

    def _p_DeleteExpr(self, node: N.DeleteExpr) -> None:
        self._emit("delete ")
        self._print_expr_in_context(node.target, _PREFIX)

    def _p_InExpr(self, node: N.InExpr) -> None:
        self._print_expr_in_context(node.key, 11)
        self._emit(" in ")
        self._print_expr_in_context(node.obj, 11, right_of_right_assoc=True)

    def _p_ArrayLiteral(self, node: N.ArrayLiteral) -> None:
        self._emit("[")
        for i, el in enumerate(node.elements):
            if i:
                self._emit(", ")
            self._print(el)
        self._emit("]")

    def _p_ObjectLiteral(self, node: N.ObjectLiteral) -> None:
        self._emit("{")
        for i, prop in enumerate(node.properties):
            if i:
                self._emit(", ")
            self._emit(f"{prop.key}: ")
            self._print(prop.value)
        self._emit("}")

    def _p_FunctionExpr(self, node: N.FunctionExpr) -> None:
        self._emit("function")
        if node.name is not None:
            self._emit(f" {node.name}")
        self._emit("(")
        for i, (pname, ptype) in enumerate(node.params):
            if i:
                self._emit(", ")
            self._emit(pname)
            if ptype is not None:
                self._emit(f":{ptype}")
        self._emit(")")
        if node.return_type is not None:
            self._emit(f":{node.return_type}")
        self._emit(" ")
        self._print(node.body)

    # Statement handlers ───────────────────────────────────────────────────

    def _p_BlockStmt(self, node: N.BlockStmt) -> None:
        self._emit("{")
        self._depth += 1
        for stmt in node.statements:
            self._newline()
            self._indent()
            self._print(stmt)
        self._depth -= 1
        self._newline()
        self._indent()
        self._emit("}")

    def _p_ExpressionStmt(self, node: N.ExpressionStmt) -> None:
        self._print(node.expression)
        self._emit(";")

    def _p_ReturnStmt(self, node: N.ReturnStmt) -> None:
        if node.value is None:
            self._emit("return;")
        else:
            self._emit("return ")
            self._print(node.value)
            self._emit(";")

    def _p_ThrowStmt(self, node: N.ThrowStmt) -> None:
        self._emit("throw ")
        self._print(node.value)
        self._emit(";")

    def _p_BreakStmt(self, node: N.BreakStmt) -> None:
        if node.label:
            self._emit(f"break {node.label};")
        else:
            self._emit("break;")

    def _p_ContinueStmt(self, node: N.ContinueStmt) -> None:
        if node.label:
            self._emit(f"continue {node.label};")
        else:
            self._emit("continue;")

    def _p_LabeledStmt(self, node: N.LabeledStmt) -> None:
        self._emit(f"{node.label}: ")
        self._print(node.body)

    def _p_VarDeclStmt(self, node: N.VarDeclStmt) -> None:
        self._emit(self._var_decl_header(node))
        self._emit(";")

    def _var_decl_header(self, node: N.VarDeclStmt) -> str:
        out = f"var {node.name}"
        if node.type_name is not None:
            out += f":{node.type_name}"
        if node.init is not None:
            # Hand off to a nested printer so we don't fight the output buffer.
            init_str = AstPrinter(self._indent_unit).print(node.init)
            out += f" = {init_str}"
        return out

    def _p_IfStmt(self, node: N.IfStmt) -> None:
        self._emit("if (")
        self._print(node.cond)
        self._emit(") ")
        self._print(node.then_body)
        if node.else_body is not None:
            self._emit(" else ")
            # Collapse ``else { if (...) }`` into ``else if (...)`` when
            # the else body is a bare IfStmt.
            self._print(node.else_body)

    def _p_WhileStmt(self, node: N.WhileStmt) -> None:
        self._emit("while (")
        self._print(node.cond)
        self._emit(") ")
        self._print(node.body)

    def _p_DoWhileStmt(self, node: N.DoWhileStmt) -> None:
        self._emit("do ")
        self._print(node.body)
        self._emit(" while (")
        self._print(node.cond)
        self._emit(");")

    def _p_ForStmt(self, node: N.ForStmt) -> None:
        self._emit("for (")
        if node.init is not None:
            # Init may be a VarDeclStmt or an ExpressionStmt — in the
            # ``for`` header these are emitted without their trailing
            # semicolons (the ``for`` syntax adds the separators).
            if isinstance(node.init, N.VarDeclStmt):
                self._emit(self._var_decl_header(node.init))
            elif isinstance(node.init, N.ExpressionStmt):
                self._print(node.init.expression)
            else:
                self._print(node.init)
        self._emit("; ")
        if node.cond is not None:
            self._print(node.cond)
        self._emit("; ")
        if node.step is not None:
            self._print(node.step)
        self._emit(") ")
        self._print(node.body)

    def _p_ForInStmt(self, node: N.ForInStmt) -> None:
        self._emit("for (var ")
        self._emit(node.var)
        if node.var_type is not None:
            self._emit(f":{node.var_type}")
        self._emit(" in ")
        self._print(node.iterable)
        self._emit(") ")
        self._print(node.body)

    def _p_ForEachStmt(self, node: N.ForEachStmt) -> None:
        self._emit("for each (var ")
        self._emit(node.var)
        if node.var_type is not None:
            self._emit(f":{node.var_type}")
        self._emit(" in ")
        self._print(node.iterable)
        self._emit(") ")
        self._print(node.body)

    def _p_SwitchStmt(self, node: N.SwitchStmt) -> None:
        self._emit("switch (")
        self._print(node.discriminant)
        self._emit(") {")
        self._depth += 1
        for case in node.cases:
            self._newline()
            self._indent()
            if case.label is None:
                self._emit("default:")
            else:
                self._emit("case ")
                self._print(case.label)
                self._emit(":")
            self._depth += 1
            for stmt in case.body:
                self._newline()
                self._indent()
                self._print(stmt)
            self._depth -= 1
        self._depth -= 1
        self._newline()
        self._indent()
        self._emit("}")

    def _p_TryStmt(self, node: N.TryStmt) -> None:
        self._emit("try ")
        self._print(node.try_body)
        for clause in node.catches:
            self._emit(" catch (")
            self._emit(clause.var)
            if clause.var_type is not None:
                self._emit(f":{clause.var_type}")
            self._emit(") ")
            self._print(clause.body)
        if node.finally_body is not None:
            self._emit(" finally ")
            self._print(node.finally_body)
