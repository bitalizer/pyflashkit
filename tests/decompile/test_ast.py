"""Tests for AST node construction and the AS3 printer.

Each test builds a tiny AST by hand and prints it, verifying the
printer produces the expected AS3 source text. Together these tests
cover every AST node type (statements and expressions) at least once.
"""

from __future__ import annotations

import pytest

from flashkit.decompile.ast.nodes import (
    # statements
    BlockStmt, IfStmt, WhileStmt, DoWhileStmt, ForStmt, ForInStmt,
    ForEachStmt, SwitchStmt, SwitchCase, TryStmt, CatchClause,
    ReturnStmt, ThrowStmt, BreakStmt, ContinueStmt, LabeledStmt,
    ExpressionStmt, VarDeclStmt,
    # expressions
    Literal, Identifier, MemberAccess, MethodCall, NewExpr,
    BinaryOp, UnaryOp, TernaryOp, AssignExpr, CompoundAssignExpr,
    IndexAccess, CastExpr, IsExpr, AsExpr, FunctionExpr,
    ArrayLiteral, ObjectLiteral, ObjectProperty,
    TypeofExpr, DeleteExpr, InExpr,
)
from flashkit.decompile.ast.printer import AstPrinter


def p(node) -> str:
    """Shortcut: print one node."""
    return AstPrinter().print(node)


# ── literals ───────────────────────────────────────────────────────────────


def test_literal_int():
    assert p(Literal(42)) == "42"


def test_literal_negative_int():
    assert p(Literal(-1)) == "-1"


def test_literal_float():
    assert p(Literal(3.14)) == "3.14"


def test_literal_nan():
    import math
    assert p(Literal(math.nan)) == "NaN"


def test_literal_infinity():
    import math
    assert p(Literal(math.inf)) == "Infinity"
    assert p(Literal(-math.inf)) == "-Infinity"


def test_literal_string_escapes():
    assert p(Literal('hi "you"\n')) == r'"hi \"you\"\n"'


def test_literal_bool():
    assert p(Literal(True)) == "true"
    assert p(Literal(False)) == "false"


def test_literal_null():
    assert p(Literal(None)) == "null"


# ── identifiers and member access ─────────────────────────────────────────


def test_identifier():
    assert p(Identifier("x")) == "x"


def test_member_access():
    assert p(MemberAccess(Identifier("a"), "b")) == "a.b"


def test_index_access():
    assert p(IndexAccess(Identifier("a"), Literal(0))) == "a[0]"


# ── binary/unary/ternary ───────────────────────────────────────────────────


def test_binary_op_no_unneeded_parens():
    # (a + b) * c  -> parens needed on left
    ast = BinaryOp("*", BinaryOp("+", Identifier("a"), Identifier("b")),
                   Identifier("c"))
    assert p(ast) == "(a + b) * c"


def test_binary_op_same_precedence_omits_parens():
    # a + b + c  -> left-assoc, no parens
    ast = BinaryOp("+", BinaryOp("+", Identifier("a"), Identifier("b")),
                   Identifier("c"))
    assert p(ast) == "a + b + c"


def test_unary_prefix():
    assert p(UnaryOp("!", Identifier("x"))) == "!x"


def test_unary_negation_on_literal():
    assert p(UnaryOp("-", Literal(5))) == "-5"


def test_ternary():
    ast = TernaryOp(Identifier("c"), Identifier("x"), Identifier("y"))
    assert p(ast) == "c ? x : y"


def test_assign():
    ast = AssignExpr(Identifier("x"), Literal(1))
    assert p(ast) == "x = 1"


def test_compound_assign():
    ast = CompoundAssignExpr("+=", Identifier("x"), Literal(1))
    assert p(ast) == "x += 1"


# ── calls / new ────────────────────────────────────────────────────────────


def test_method_call_no_args():
    ast = MethodCall(Identifier("f"), args=[])
    assert p(ast) == "f()"


def test_method_call_with_args():
    ast = MethodCall(
        MemberAccess(Identifier("a"), "b"),
        args=[Literal(1), Identifier("x")],
    )
    assert p(ast) == "a.b(1, x)"


def test_new_expr():
    ast = NewExpr(Identifier("Foo"), args=[Literal(1)])
    assert p(ast) == "new Foo(1)"


# ── casts / typeof / delete / in / is / as ────────────────────────────────


def test_cast_expr():
    ast = CastExpr("int", Identifier("x"))
    assert p(ast) == "int(x)"


def test_is_expr():
    ast = IsExpr(Identifier("x"), Identifier("Foo"))
    assert p(ast) == "x is Foo"


def test_as_expr():
    ast = AsExpr(Identifier("x"), Identifier("Foo"))
    assert p(ast) == "x as Foo"


def test_typeof():
    assert p(TypeofExpr(Identifier("x"))) == "typeof x"


def test_delete():
    assert p(DeleteExpr(MemberAccess(Identifier("obj"), "field"))) == \
        "delete obj.field"


def test_in_expr():
    ast = InExpr(Literal("k"), Identifier("obj"))
    assert p(ast) == '"k" in obj'


# ── literals: array / object / function ────────────────────────────────────


def test_array_literal():
    ast = ArrayLiteral([Literal(1), Literal(2), Literal(3)])
    assert p(ast) == "[1, 2, 3]"


def test_object_literal():
    ast = ObjectLiteral([
        ObjectProperty("a", Literal(1)),
        ObjectProperty("b", Literal(2)),
    ])
    assert p(ast) == "{a: 1, b: 2}"


def test_function_expr_anonymous():
    body = BlockStmt([ReturnStmt(Identifier("x"))])
    ast = FunctionExpr(name=None, params=[("x", "int")], return_type="int",
                       body=body)
    assert p(ast) == (
        "function(x:int):int {\n"
        "    return x;\n"
        "}"
    )


# ── statements ─────────────────────────────────────────────────────────────


def test_expression_statement():
    ast = ExpressionStmt(MethodCall(Identifier("f"), []))
    assert p(ast) == "f();"


def test_return_stmt_with_value():
    assert p(ReturnStmt(Literal(1))) == "return 1;"


def test_return_stmt_void():
    assert p(ReturnStmt(None)) == "return;"


def test_throw_stmt():
    assert p(ThrowStmt(NewExpr(Identifier("Error"), [Literal("oops")]))) == \
        'throw new Error("oops");'


def test_break_and_continue():
    assert p(BreakStmt(None)) == "break;"
    assert p(BreakStmt("outer")) == "break outer;"
    assert p(ContinueStmt(None)) == "continue;"
    assert p(ContinueStmt("loop")) == "continue loop;"


def test_var_decl_with_init():
    ast = VarDeclStmt("x", "int", Literal(1))
    assert p(ast) == "var x:int = 1;"


def test_var_decl_without_init():
    ast = VarDeclStmt("y", "String", None)
    assert p(ast) == "var y:String;"


def test_var_decl_untyped():
    ast = VarDeclStmt("z", None, Literal(True))
    assert p(ast) == "var z = true;"


def test_labeled_stmt():
    inner = BlockStmt([BreakStmt("outer")])
    ast = LabeledStmt("outer", WhileStmt(Literal(True), inner))
    # Expected:
    #   outer: while (true) {
    #       break outer;
    #   }
    assert p(ast) == (
        "outer: while (true) {\n"
        "    break outer;\n"
        "}"
    )


# ── block, if, while, do-while, for, for-in, for-each ─────────────────────


def test_block_stmt_indents_children():
    ast = BlockStmt([
        ExpressionStmt(MethodCall(Identifier("f"), [])),
        ReturnStmt(None),
    ])
    # A bare BlockStmt at the top level still emits its braces.
    assert p(ast) == (
        "{\n"
        "    f();\n"
        "    return;\n"
        "}"
    )


def test_if_stmt_no_else():
    ast = IfStmt(
        Identifier("c"),
        BlockStmt([ReturnStmt(None)]),
        None,
    )
    assert p(ast) == (
        "if (c) {\n"
        "    return;\n"
        "}"
    )


def test_if_stmt_with_else():
    ast = IfStmt(
        Identifier("c"),
        BlockStmt([ExpressionStmt(Identifier("x"))]),
        BlockStmt([ExpressionStmt(Identifier("y"))]),
    )
    assert p(ast) == (
        "if (c) {\n"
        "    x;\n"
        "} else {\n"
        "    y;\n"
        "}"
    )


def test_if_else_if_chain():
    # if (a) x; else if (b) y; else z;
    ast = IfStmt(
        Identifier("a"),
        BlockStmt([ExpressionStmt(Identifier("x"))]),
        IfStmt(
            Identifier("b"),
            BlockStmt([ExpressionStmt(Identifier("y"))]),
            BlockStmt([ExpressionStmt(Identifier("z"))]),
        ),
    )
    assert p(ast) == (
        "if (a) {\n"
        "    x;\n"
        "} else if (b) {\n"
        "    y;\n"
        "} else {\n"
        "    z;\n"
        "}"
    )


def test_while_stmt():
    ast = WhileStmt(
        Identifier("c"),
        BlockStmt([ExpressionStmt(Identifier("x"))]),
    )
    assert p(ast) == (
        "while (c) {\n"
        "    x;\n"
        "}"
    )


def test_do_while_stmt():
    ast = DoWhileStmt(
        BlockStmt([ExpressionStmt(Identifier("x"))]),
        Identifier("c"),
    )
    assert p(ast) == (
        "do {\n"
        "    x;\n"
        "} while (c);"
    )


def test_for_stmt():
    ast = ForStmt(
        init=VarDeclStmt("i", "int", Literal(0)),
        cond=BinaryOp("<", Identifier("i"), Literal(10)),
        step=CompoundAssignExpr("+=", Identifier("i"), Literal(1)),
        body=BlockStmt([]),
    )
    # Note: init is a VarDeclStmt — emitted without trailing ';' inside for(...)
    assert p(ast) == (
        "for (var i:int = 0; i < 10; i += 1) {\n"
        "}"
    )


def test_for_in_stmt():
    ast = ForInStmt(
        var="k", var_type=None,
        iterable=Identifier("obj"),
        body=BlockStmt([ExpressionStmt(Identifier("k"))]),
    )
    assert p(ast) == (
        "for (var k in obj) {\n"
        "    k;\n"
        "}"
    )


def test_for_each_stmt():
    ast = ForEachStmt(
        var="v", var_type="String",
        iterable=Identifier("arr"),
        body=BlockStmt([]),
    )
    assert p(ast) == (
        "for each (var v:String in arr) {\n"
        "}"
    )


# ── switch, try/catch ──────────────────────────────────────────────────────


def test_switch_stmt():
    ast = SwitchStmt(
        Identifier("x"),
        cases=[
            SwitchCase(
                label=Literal(1),
                body=[
                    ExpressionStmt(MethodCall(Identifier("a"), [])),
                    BreakStmt(None),
                ],
            ),
            SwitchCase(
                label=None,   # default
                body=[ExpressionStmt(MethodCall(Identifier("b"), []))],
            ),
        ],
    )
    assert p(ast) == (
        "switch (x) {\n"
        "    case 1:\n"
        "        a();\n"
        "        break;\n"
        "    default:\n"
        "        b();\n"
        "}"
    )


def test_try_catch_finally():
    ast = TryStmt(
        try_body=BlockStmt([ExpressionStmt(Identifier("x"))]),
        catches=[
            CatchClause(
                var="e", var_type="Error",
                body=BlockStmt([ExpressionStmt(Identifier("log"))]),
            ),
        ],
        finally_body=BlockStmt([ExpressionStmt(Identifier("cleanup"))]),
    )
    assert p(ast) == (
        "try {\n"
        "    x;\n"
        "} catch (e:Error) {\n"
        "    log;\n"
        "} finally {\n"
        "    cleanup;\n"
        "}"
    )


def test_try_catch_no_finally():
    ast = TryStmt(
        try_body=BlockStmt([ExpressionStmt(Identifier("x"))]),
        catches=[
            CatchClause(
                var="e", var_type=None,
                body=BlockStmt([]),
            ),
        ],
        finally_body=None,
    )
    assert p(ast) == (
        "try {\n"
        "    x;\n"
        "} catch (e) {\n"
        "}"
    )


# ── precedence / parens ────────────────────────────────────────────────────


def test_binary_and_ternary_precedence():
    # a + (b ? c : d)  -> ternary needs parens inside +
    ast = BinaryOp("+", Identifier("a"),
                   TernaryOp(Identifier("b"), Identifier("c"),
                             Identifier("d")))
    assert p(ast) == "a + (b ? c : d)"


def test_unary_inside_binary_no_parens():
    # !a && b  -> no parens
    ast = BinaryOp("&&", UnaryOp("!", Identifier("a")), Identifier("b"))
    assert p(ast) == "!a && b"


def test_assign_inside_binary_needs_parens():
    # (x = 1) + 2
    ast = BinaryOp("+",
                   AssignExpr(Identifier("x"), Literal(1)),
                   Literal(2))
    assert p(ast) == "(x = 1) + 2"


def test_deeply_nested_member_access():
    ast = MethodCall(
        MemberAccess(
            MemberAccess(Identifier("a"), "b"),
            "c"),
        args=[Literal(1)],
    )
    assert p(ast) == "a.b.c(1)"
