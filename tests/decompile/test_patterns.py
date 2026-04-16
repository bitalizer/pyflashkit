"""Tests for AST pattern-matching passes (idiom rewrites).

Each pass is a visitor that rewrites an AST into more idiomatic AS3:
- ``x = x + 1`` -> ``x += 1``
- ``if(c) t=x; else t=y;`` -> ``t = c ? x : y``
- ``while(c) { body; step; }`` with preceding init -> ``for (init; c; step) body``

Each pattern is individually testable with a hand-built AST input and
an expected AST output.
"""

from __future__ import annotations

from flashkit.decompile.ast.nodes import (
    AssignExpr, BinaryOp, BlockStmt, CompoundAssignExpr,
    ExpressionStmt, ForStmt, Identifier, IfStmt, Literal,
    ReturnStmt, TernaryOp, UnaryOp, VarDeclStmt, WhileStmt,
)
from flashkit.decompile.ast.printer import AstPrinter
from flashkit.decompile.patterns import apply_patterns


def _p(node) -> str:
    return AstPrinter().print(node)


# ── compound assignment ────────────────────────────────────────────────────


def test_self_plus_one_becomes_compound_assign():
    # x = x + 1  -> x += 1
    ast = BlockStmt([
        ExpressionStmt(AssignExpr(
            Identifier("x"),
            BinaryOp("+", Identifier("x"), Literal(1)),
        )),
    ])

    rewritten = apply_patterns(ast)

    assert _p(rewritten) == (
        "{\n"
        "    x += 1;\n"
        "}"
    )


def test_self_minus_two_becomes_compound_assign():
    ast = BlockStmt([
        ExpressionStmt(AssignExpr(
            Identifier("x"),
            BinaryOp("-", Identifier("x"), Literal(2)),
        )),
    ])
    rewritten = apply_patterns(ast)
    assert _p(rewritten) == (
        "{\n"
        "    x -= 2;\n"
        "}"
    )


def test_self_multiply_becomes_compound_assign():
    ast = BlockStmt([
        ExpressionStmt(AssignExpr(
            Identifier("y"),
            BinaryOp("*", Identifier("y"), Identifier("z")),
        )),
    ])
    rewritten = apply_patterns(ast)
    assert _p(rewritten) == (
        "{\n"
        "    y *= z;\n"
        "}"
    )


def test_non_self_assign_not_rewritten():
    # x = y + 1 stays as-is
    ast = BlockStmt([
        ExpressionStmt(AssignExpr(
            Identifier("x"),
            BinaryOp("+", Identifier("y"), Literal(1)),
        )),
    ])
    rewritten = apply_patterns(ast)
    assert _p(rewritten) == (
        "{\n"
        "    x = y + 1;\n"
        "}"
    )


# ── double-negation collapse ──────────────────────────────────────────────


def test_double_not_collapses():
    # !!cond  ->  cond   (after coerce semantics: AS3 !! yields Boolean;
    # but in control-flow contexts we rewrite to cond since the outer
    # truthiness is what matters)
    ast = BlockStmt([
        IfStmt(
            UnaryOp("!", UnaryOp("!", Identifier("c"))),
            BlockStmt([ReturnStmt(None)]),
            None,
        ),
    ])
    rewritten = apply_patterns(ast)
    assert _p(rewritten) == (
        "{\n"
        "    if (c) {\n"
        "        return;\n"
        "    }\n"
        "}"
    )


# ── ternary from if/else ──────────────────────────────────────────────────


def test_if_assign_else_assign_becomes_ternary():
    # if (c) { t = x } else { t = y }   ->   t = c ? x : y
    ast = BlockStmt([
        IfStmt(
            Identifier("c"),
            BlockStmt([ExpressionStmt(AssignExpr(Identifier("t"),
                                                 Identifier("x")))]),
            BlockStmt([ExpressionStmt(AssignExpr(Identifier("t"),
                                                 Identifier("y")))]),
        ),
    ])

    rewritten = apply_patterns(ast)

    assert _p(rewritten) == (
        "{\n"
        "    t = c ? x : y;\n"
        "}"
    )


def test_if_different_targets_not_rewritten_as_ternary():
    # if (c) { t = x } else { u = y }  stays as if/else
    ast = BlockStmt([
        IfStmt(
            Identifier("c"),
            BlockStmt([ExpressionStmt(AssignExpr(Identifier("t"),
                                                 Identifier("x")))]),
            BlockStmt([ExpressionStmt(AssignExpr(Identifier("u"),
                                                 Identifier("y")))]),
        ),
    ])
    rewritten = apply_patterns(ast)
    assert _p(rewritten) == (
        "{\n"
        "    if (c) {\n"
        "        t = x;\n"
        "    } else {\n"
        "        u = y;\n"
        "    }\n"
        "}"
    )


# ── for loop detection ─────────────────────────────────────────────────────


def test_init_while_step_becomes_for_loop():
    # var i:int = 0;
    # while (i < 10) { ...body; i += 1; }
    #   ->
    # for (var i:int = 0; i < 10; i += 1) { ...body }
    init = VarDeclStmt("i", "int", Literal(0))
    cond = BinaryOp("<", Identifier("i"), Literal(10))
    step = ExpressionStmt(CompoundAssignExpr(
        "+=", Identifier("i"), Literal(1),
    ))
    body_core = ExpressionStmt(AssignExpr(
        Identifier("x"), Identifier("i"),
    ))
    ast = BlockStmt([
        init,
        WhileStmt(cond, BlockStmt([body_core, step])),
    ])

    rewritten = apply_patterns(ast)

    assert _p(rewritten) == (
        "{\n"
        "    for (var i:int = 0; i < 10; i += 1) {\n"
        "        x = i;\n"
        "    }\n"
        "}"
    )


def test_while_without_step_stays_while():
    # No trailing step -> stays a while loop.
    ast = BlockStmt([
        VarDeclStmt("i", "int", Literal(0)),
        WhileStmt(
            BinaryOp("<", Identifier("i"), Literal(10)),
            BlockStmt([ExpressionStmt(Identifier("body"))]),
        ),
    ])
    rewritten = apply_patterns(ast)
    # var i stays; while stays.
    assert "for (" not in _p(rewritten)
    assert "while (i < 10)" in _p(rewritten)


# ── else-of-returning-if collapse ─────────────────────────────────────────


def test_if_return_else_inlines_the_else():
    # if (c) { return 1 } else { return 0 }  -> if (c) { return 1 } return 0
    ast = BlockStmt([
        IfStmt(
            Identifier("c"),
            BlockStmt([ReturnStmt(Literal(1))]),
            BlockStmt([ReturnStmt(Literal(0))]),
        ),
    ])

    rewritten = apply_patterns(ast)

    assert _p(rewritten) == (
        "{\n"
        "    if (c) {\n"
        "        return 1;\n"
        "    }\n"
        "    return 0;\n"
        "}"
    )


def test_if_throw_else_inlines_the_else():
    ast = BlockStmt([
        IfStmt(
            Identifier("c"),
            BlockStmt([ReturnStmt(None)]),
            BlockStmt([ExpressionStmt(Identifier("cleanup"))]),
        ),
    ])
    rewritten = apply_patterns(ast)
    assert _p(rewritten) == (
        "{\n"
        "    if (c) {\n"
        "        return;\n"
        "    }\n"
        "    cleanup;\n"
        "}"
    )


def test_trailing_bare_return_stripped():
    # A method body that ends with ``return;`` has the trailing return
    # elided — AS3 adds an implicit void return at the end of every
    # function.
    ast = BlockStmt([
        ExpressionStmt(Identifier("x")),
        ReturnStmt(None),
    ])
    rewritten = apply_patterns(ast)
    assert _p(rewritten) == (
        "{\n"
        "    x;\n"
        "}"
    )


def test_trailing_return_with_value_kept():
    # Only a BARE return (no value) is trailing-implicit. ``return x;``
    # stays.
    ast = BlockStmt([
        ReturnStmt(Identifier("x")),
    ])
    rewritten = apply_patterns(ast)
    assert "return x" in _p(rewritten)


def test_only_statement_is_bare_return_body_becomes_empty():
    ast = BlockStmt([ReturnStmt(None)])
    rewritten = apply_patterns(ast)
    assert _p(rewritten) == "{\n}"


def test_if_non_terminating_else_kept():
    # Then branch doesn't end in return/throw -> keep the else.
    ast = BlockStmt([
        IfStmt(
            Identifier("c"),
            BlockStmt([ExpressionStmt(Identifier("x"))]),
            BlockStmt([ExpressionStmt(Identifier("y"))]),
        ),
    ])
    rewritten = apply_patterns(ast)
    assert _p(rewritten) == (
        "{\n"
        "    if (c) {\n"
        "        x;\n"
        "    } else {\n"
        "        y;\n"
        "    }\n"
        "}"
    )


# ── idempotence ───────────────────────────────────────────────────────────


def test_applying_patterns_twice_is_idempotent():
    ast = BlockStmt([
        ExpressionStmt(AssignExpr(
            Identifier("x"),
            BinaryOp("+", Identifier("x"), Literal(1)),
        )),
        IfStmt(
            Identifier("c"),
            BlockStmt([ExpressionStmt(AssignExpr(Identifier("t"),
                                                 Identifier("a")))]),
            BlockStmt([ExpressionStmt(AssignExpr(Identifier("t"),
                                                 Identifier("b")))]),
        ),
    ])
    once = apply_patterns(ast)
    twice = apply_patterns(once)
    assert _p(once) == _p(twice)
