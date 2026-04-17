"""Typed AST node definitions for AS3.

Two top-level categories:
- ``Statement`` — anything that ends in a ``;`` or a ``}``.
- ``Expression`` — anything that produces a value.

All nodes are dataclasses. Most fields are ``Node`` subclasses; a few
(names, type annotations, operator strings) are plain ``str``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


class Node:
    """Base class for all AST nodes. No behavior; dataclass subclasses
    carry all the data."""


class Statement(Node):
    """Marker base for statement nodes."""


class Expression(Node):
    """Marker base for expression nodes."""


# ── Expressions ───────────────────────────────────────────────────────────


@dataclass
class Literal(Expression):
    """A literal constant. ``value`` may be ``int``, ``float``, ``str``,
    ``bool``, or ``None`` (for the AS3 ``null`` literal)."""
    value: Union[int, float, str, bool, None]


@dataclass
class Identifier(Expression):
    name: str


@dataclass
class MemberAccess(Expression):
    """``obj.name``."""
    target: Expression
    name: str


@dataclass
class IndexAccess(Expression):
    """``obj[index]``."""
    target: Expression
    index: Expression


@dataclass
class MethodCall(Expression):
    """``callee(arg0, arg1, ...)``. ``callee`` may be any expression
    (identifier, member access, etc.)."""
    callee: Expression
    args: list[Expression] = field(default_factory=list)


@dataclass
class NewExpr(Expression):
    """``new Callee(args)``."""
    callee: Expression
    args: list[Expression] = field(default_factory=list)


@dataclass
class BinaryOp(Expression):
    """A binary operation — ``op`` is the operator string (``+``,
    ``&&``, ``<<``, etc.)."""
    op: str
    left: Expression
    right: Expression


@dataclass
class UnaryOp(Expression):
    """A prefix unary operation: ``!x``, ``-x``, ``~x``, ``++x``,
    ``--x``."""
    op: str
    operand: Expression


@dataclass
class TernaryOp(Expression):
    """``cond ? then_expr : else_expr``."""
    cond: Expression
    then_expr: Expression
    else_expr: Expression


@dataclass
class AssignExpr(Expression):
    """``target = value``."""
    target: Expression
    value: Expression


@dataclass
class CompoundAssignExpr(Expression):
    """``target op= value`` (``op`` is ``+``, ``-``, ``*``, etc.)."""
    op: str
    target: Expression
    value: Expression


@dataclass
class CastExpr(Expression):
    """AS3 explicit type coerce-via-call: ``int(x)``, ``String(x)``."""
    type_name: str
    value: Expression


@dataclass
class IsExpr(Expression):
    """``value is TypeRef``."""
    value: Expression
    type_ref: Expression


@dataclass
class AsExpr(Expression):
    """``value as TypeRef``."""
    value: Expression
    type_ref: Expression


@dataclass
class TypeofExpr(Expression):
    """``typeof value``."""
    value: Expression


@dataclass
class DeleteExpr(Expression):
    """``delete target``."""
    target: Expression


@dataclass
class InExpr(Expression):
    """``key in obj``."""
    key: Expression
    obj: Expression


@dataclass
class ArrayLiteral(Expression):
    elements: list[Expression] = field(default_factory=list)


@dataclass
class ObjectProperty(Node):
    """One entry in an object literal. Keys are always strings in AS3
    object literals; numeric/computed keys are represented as strings."""
    key: str
    value: Expression


@dataclass
class ObjectLiteral(Expression):
    properties: list[ObjectProperty] = field(default_factory=list)


@dataclass
class FunctionExpr(Expression):
    """An anonymous function: ``function name?(params):retType { body }``.

    ``params`` is a list of ``(name, type_or_None)`` pairs. ``name`` is
    an optional function name (rarely used in AS3 function
    expressions)."""
    name: str | None
    params: list[tuple[str, str | None]]
    return_type: str | None
    body: "BlockStmt"


# ── Statements ────────────────────────────────────────────────────────────


@dataclass
class BlockStmt(Statement):
    """A braced block of statements."""
    statements: list[Statement] = field(default_factory=list)


@dataclass
class IfStmt(Statement):
    """``if (cond) then_body [else else_body]``. ``else_body`` may be
    another ``IfStmt`` to represent ``else if`` chains."""
    cond: Expression
    then_body: Statement
    else_body: Statement | None = None


@dataclass
class WhileStmt(Statement):
    cond: Expression
    body: Statement


@dataclass
class DoWhileStmt(Statement):
    body: Statement
    cond: Expression


@dataclass
class ForStmt(Statement):
    """``for (init; cond; step) body``. Each header piece may be
    ``None``."""
    init: Statement | None
    cond: Expression | None
    step: Expression | None
    body: Statement


@dataclass
class ForInStmt(Statement):
    """``for (var var_name[:type] in iterable) body``."""
    var: str
    var_type: str | None
    iterable: Expression
    body: Statement


@dataclass
class ForEachStmt(Statement):
    """``for each (var var_name[:type] in iterable) body``."""
    var: str
    var_type: str | None
    iterable: Expression
    body: Statement


@dataclass
class SwitchCase(Node):
    """One arm of a switch. ``label=None`` means the default case."""
    label: Expression | None
    body: list[Statement] = field(default_factory=list)


@dataclass
class SwitchStmt(Statement):
    discriminant: Expression
    cases: list[SwitchCase] = field(default_factory=list)


@dataclass
class CatchClause(Node):
    """A ``catch (var[:type]) { body }`` arm."""
    var: str
    var_type: str | None
    body: Statement


@dataclass
class TryStmt(Statement):
    try_body: Statement
    catches: list[CatchClause] = field(default_factory=list)
    finally_body: Statement | None = None


@dataclass
class ReturnStmt(Statement):
    value: Expression | None = None


@dataclass
class ThrowStmt(Statement):
    value: Expression


@dataclass
class BreakStmt(Statement):
    label: str | None = None


@dataclass
class ContinueStmt(Statement):
    label: str | None = None


@dataclass
class LabeledStmt(Statement):
    """A labelled statement — usually wraps a loop."""
    label: str
    body: Statement


@dataclass
class ExpressionStmt(Statement):
    """An expression used as a statement (side-effecting call,
    assignment, etc.)."""
    expression: Expression


@dataclass
class VarDeclStmt(Statement):
    """``var name[:type] [= init];``."""
    name: str
    type_name: str | None
    init: Expression | None
