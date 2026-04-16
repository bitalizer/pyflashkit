"""AST pattern-matching passes.

Each pass is a local rewrite over the AST produced by Phase 6/7. The
rewrites make the source match what a human would write — none of
them change semantics, they just fold compiler-produced shapes into
AS3 idioms.

Pipeline order matters:
1. Double-negation collapse (``!!x -> x``) — runs first so later
   passes see the canonical form of conditions.
2. Compound-assignment folding (``x = x + 1 -> x += 1``) — must run
   before the for-loop detector so step expressions are in compound
   form when the for-loop test looks at them.
3. Ternary folding (``if(c) { t=x } else { t=y } -> t = c ? x : y``).
4. For-loop detection (``init; while(c){ body; step; } -> for(...)``).

Each pass is implemented as a visitor method on the ``_Transform``
class, recursively traversing the AST with a single-dispatch method
table. Node types not handled pass through unchanged.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from typing import Any

from .ast import nodes as N


# ── driver ─────────────────────────────────────────────────────────────────


def apply_patterns(node: N.Node) -> N.Node:
    """Run the full pattern pipeline. Returns a new AST — the input is
    not mutated."""
    node = _CollapseDoubleNot().visit(node)
    node = _CompoundAssign().visit(node)
    node = _TernaryFromIf().visit(node)
    node = _InlineElseAfterReturn().visit(node)
    node = _ForFromWhile().visit(node)
    node = _strip_trailing_bare_return_at_top(node)
    return node


def _strip_trailing_bare_return_at_top(node: N.Node) -> N.Node:
    """Drop a trailing ``return;`` from the outermost ``BlockStmt``.

    Every AS3 function has an implicit void return, so an explicit
    bare return on the last statement is redundant noise. A return
    with a value is kept — its expression is meaningful. Nested
    blocks (inside if/while/switch arms) keep their returns because
    they may guard early exit paths."""
    if (isinstance(node, N.BlockStmt)
            and node.statements
            and isinstance(node.statements[-1], N.ReturnStmt)
            and node.statements[-1].value is None):
        return N.BlockStmt(list(node.statements[:-1]))
    return node


# ── generic visitor ────────────────────────────────────────────────────────


class _Transform:
    """Base visitor. Walks every field of every dataclass node,
    recursing into ``Node``-typed fields and into ``list``/``tuple``
    containers. Subclasses override ``visit_<ClassName>`` hooks for
    specific rewrites."""

    def visit(self, node: Any) -> Any:
        if isinstance(node, N.Node):
            method = getattr(self, f"visit_{type(node).__name__}", None)
            if method is not None:
                return method(node)
            return self._generic_visit(node)
        if isinstance(node, list):
            return [self.visit(x) for x in node]
        if isinstance(node, tuple):
            return tuple(self.visit(x) for x in node)
        return node

    def _generic_visit(self, node: N.Node) -> N.Node:
        if not is_dataclass(node):
            return node
        changes: dict[str, Any] = {}
        for f in fields(node):
            current = getattr(node, f.name)
            new = self.visit(current)
            if new is not current:
                changes[f.name] = new
        if changes:
            return replace(node, **changes)
        return node


# ── passes ────────────────────────────────────────────────────────────────


class _CollapseDoubleNot(_Transform):
    """``!!x`` collapses to ``x``. Applied recursively so ``!!!!x`` also
    reduces to ``x``."""

    def visit_UnaryOp(self, node: N.UnaryOp) -> N.Node:
        inner = self.visit(node.operand)
        if node.op == "!" and isinstance(inner, N.UnaryOp) and inner.op == "!":
            return inner.operand
        if inner is not node.operand:
            return N.UnaryOp(node.op, inner)
        return node


_COMPOUND_OPS = frozenset({"+", "-", "*", "/", "%", "&", "|", "^",
                           "<<", ">>", ">>>"})


class _CompoundAssign(_Transform):
    """``x = x op y`` → ``x op= y`` when ``op`` is compound-assignable."""

    def visit_AssignExpr(self, node: N.AssignExpr) -> N.Node:
        target = self.visit(node.target)
        value = self.visit(node.value)
        if (isinstance(value, N.BinaryOp)
                and value.op in _COMPOUND_OPS
                and _same_lvalue(target, value.left)):
            return N.CompoundAssignExpr(value.op, target, value.right)
        if target is not node.target or value is not node.value:
            return N.AssignExpr(target, value)
        return node


def _same_lvalue(a: N.Node, b: N.Node) -> bool:
    """Heuristic: does ``a`` refer to the same lvalue as ``b``?

    We recognise identical ``Identifier`` names and identical
    ``MemberAccess`` chains. Anything else is treated as "not the
    same" even if a deeper structural match might succeed, because
    rewriting a non-lvalue to a compound assignment could change
    evaluation order."""
    if isinstance(a, N.Identifier) and isinstance(b, N.Identifier):
        return a.name == b.name
    if isinstance(a, N.MemberAccess) and isinstance(b, N.MemberAccess):
        return a.name == b.name and _same_lvalue(a.target, b.target)
    return False


class _TernaryFromIf(_Transform):
    """``if (c) { t = x } else { t = y }`` → ``t = c ? x : y`` (as an
    ``ExpressionStmt``)."""

    def visit_IfStmt(self, node: N.IfStmt) -> N.Node:
        cond = self.visit(node.cond)
        then_body = self.visit(node.then_body)
        else_body = self.visit(node.else_body) if node.else_body else None

        then_assign = _single_assign_in(then_body)
        else_assign = _single_assign_in(else_body) if else_body else None
        if (then_assign is not None and else_assign is not None
                and _same_lvalue(then_assign.target, else_assign.target)):
            ternary = N.TernaryOp(
                cond=cond,
                then_expr=then_assign.value,
                else_expr=else_assign.value,
            )
            return N.ExpressionStmt(N.AssignExpr(then_assign.target, ternary))

        if (cond is not node.cond or then_body is not node.then_body
                or else_body is not node.else_body):
            return N.IfStmt(cond, then_body, else_body)
        return node


def _single_assign_in(stmt: N.Node) -> N.AssignExpr | None:
    """If ``stmt`` is (or contains a single) ``ExpressionStmt`` wrapping
    an ``AssignExpr``, return the assignment."""
    if isinstance(stmt, N.BlockStmt) and len(stmt.statements) == 1:
        return _single_assign_in(stmt.statements[0])
    if isinstance(stmt, N.ExpressionStmt) and isinstance(
            stmt.expression, N.AssignExpr):
        return stmt.expression
    return None


class _InlineElseAfterReturn(_Transform):
    """``if (c) { ... return; } else { body }`` → ``if (c) { ... return; }
    body``.

    When the then-branch of an if ends in a ``ReturnStmt`` or
    ``ThrowStmt`` (or an unconditional ``BreakStmt``/``ContinueStmt``),
    control can't fall through into the merge — so an ``else`` block is
    redundant. Lift its statements up to the enclosing block so they
    run unconditionally after the if.

    Only fires when the enclosing ``BlockStmt`` can accept the lifted
    statements. Nested if/else chains (``else if``) are left alone —
    the rewrite would disturb their meaning.
    """

    def visit_BlockStmt(self, node: N.BlockStmt) -> N.Node:
        stmts = [self.visit(s) for s in node.statements]
        rewrote = False
        new_stmts: list[N.Statement] = []
        for stmt in stmts:
            if (isinstance(stmt, N.IfStmt)
                    and stmt.else_body is not None
                    and not isinstance(stmt.else_body, N.IfStmt)
                    and _body_never_falls_through(stmt.then_body)):
                new_stmts.append(N.IfStmt(stmt.cond, stmt.then_body, None))
                new_stmts.extend(_flatten_block(stmt.else_body))
                rewrote = True
            else:
                new_stmts.append(stmt)
        if rewrote or new_stmts != list(node.statements):
            return N.BlockStmt(new_stmts)
        return node


def _body_never_falls_through(stmt: N.Node) -> bool:
    """Does ``stmt`` (typically a BlockStmt) always exit — return,
    throw, break, or continue — so nothing after it can run?"""
    if isinstance(stmt, (N.ReturnStmt, N.ThrowStmt,
                         N.BreakStmt, N.ContinueStmt)):
        return True
    if isinstance(stmt, N.BlockStmt) and stmt.statements:
        return _body_never_falls_through(stmt.statements[-1])
    if isinstance(stmt, N.IfStmt) and stmt.else_body is not None:
        return (_body_never_falls_through(stmt.then_body)
                and _body_never_falls_through(stmt.else_body))
    return False


def _flatten_block(stmt: N.Node) -> list[N.Statement]:
    if isinstance(stmt, N.BlockStmt):
        return list(stmt.statements)
    return [stmt]


class _ForFromWhile(_Transform):
    """Detect ``init; while (cond) { ...body; step; }`` and rewrite as
    ``for (init; cond; step) { ...body }``.

    Only fires when:
    - ``init`` is a ``VarDeclStmt`` or ``ExpressionStmt`` immediately
      preceding the ``WhileStmt`` in the same block,
    - the while body ends with a ``step`` expression statement that is
      a ``CompoundAssignExpr`` or simple ``AssignExpr`` on the same
      lvalue referenced by ``cond``.
    """

    def visit_BlockStmt(self, node: N.BlockStmt) -> N.Node:
        new_stmts: list[N.Statement] = []
        i = 0
        stmts = [self.visit(s) for s in node.statements]
        while i < len(stmts):
            stmt = stmts[i]
            # Look for [init, while]
            if (i + 1 < len(stmts)
                    and isinstance(stmts[i + 1], N.WhileStmt)
                    and _is_for_init(stmt)):
                init = stmt
                wh: N.WhileStmt = stmts[i + 1]
                body = wh.body
                if isinstance(body, N.BlockStmt) and body.statements:
                    last = body.statements[-1]
                    if _is_for_step(last, wh.cond):
                        step_expr = _step_to_expr(last)
                        remaining = body.statements[:-1]
                        new_stmts.append(N.ForStmt(
                            init=init,
                            cond=wh.cond,
                            step=step_expr,
                            body=N.BlockStmt(remaining),
                        ))
                        i += 2
                        continue
            new_stmts.append(stmt)
            i += 1
        if new_stmts != stmts:
            return N.BlockStmt(new_stmts)
        return node


def _is_for_init(stmt: N.Node) -> bool:
    return isinstance(stmt, (N.VarDeclStmt, N.ExpressionStmt))


def _is_for_step(stmt: N.Node, cond: N.Node) -> bool:
    if not isinstance(stmt, N.ExpressionStmt):
        return False
    expr = stmt.expression
    if isinstance(expr, (N.CompoundAssignExpr, N.AssignExpr)):
        return _cond_references(cond, expr.target)
    if isinstance(expr, N.UnaryOp) and expr.op in ("++", "--"):
        return _cond_references(cond, expr.operand)
    return False


def _step_to_expr(stmt: N.Node) -> N.Node:
    """The step slot of ``for (...)`` is an expression, not a
    statement; unwrap the ``ExpressionStmt``."""
    assert isinstance(stmt, N.ExpressionStmt)
    return stmt.expression


def _cond_references(cond: N.Node, target: N.Node) -> bool:
    """Does ``cond`` mention the same lvalue as ``target``?"""
    if _same_lvalue(cond, target):
        return True
    if is_dataclass(cond):
        for f in fields(cond):
            val = getattr(cond, f.name)
            if isinstance(val, N.Node) and _cond_references(val, target):
                return True
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, N.Node) and _cond_references(item, target):
                        return True
    return False


