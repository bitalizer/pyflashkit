"""Tests for BlockStackSim — per-basic-block stack simulation.

The simulator walks the instructions of a single basic block,
maintaining an expression stack, and produces:
  - a list of AST statements emitted by side-effecting opcodes (calls
    marked as void, assignments, returns),
  - the final stack state (expressions that live past the block),
  - a terminator record that carries branch-condition expressions for
    the structurer to consume later.

These tests build synthetic method bodies of one basic block each and
compare the emitted statements / stack / terminator against hand-
computed expectations.
"""

from __future__ import annotations

import os

import pytest

from flashkit.abc.builder import _encode_s24
from flashkit.abc.disasm import decode_instructions
from flashkit.abc.opcodes import (
    OP_ADD, OP_BITAND, OP_BITNOT, OP_BITOR, OP_BITXOR,
    OP_CONSTRUCTPROP, OP_CALLPROPERTY, OP_CALLPROPVOID,
    OP_CONVERT_B, OP_CONVERT_I, OP_CONVERT_S,
    OP_DIVIDE, OP_DUP,
    OP_EQUALS, OP_FINDPROPSTRICT, OP_GETLEX, OP_GETLOCAL,
    OP_GETLOCAL_0, OP_GETLOCAL_1, OP_GETLOCAL_2, OP_GETPROPERTY,
    OP_IFFALSE, OP_IFTRUE, OP_JUMP,
    OP_LESSTHAN, OP_LESSEQUALS, OP_MODULO, OP_MULTIPLY,
    OP_NEGATE, OP_NEWARRAY, OP_NEWOBJECT, OP_NOT,
    OP_POP, OP_PUSHBYTE, OP_PUSHFALSE, OP_PUSHINT, OP_PUSHNULL,
    OP_PUSHSHORT, OP_PUSHSTRING, OP_PUSHTRUE,
    OP_RETURNVALUE, OP_RETURNVOID,
    OP_SETLOCAL, OP_SETLOCAL_1, OP_SETLOCAL_2, OP_SETPROPERTY,
    OP_STRICTEQUALS, OP_SUBTRACT, OP_THROW,
)
from flashkit.abc.types import AbcFile
from flashkit.decompile.ast.nodes import (
    ArrayLiteral, AssignExpr, BinaryOp, ExpressionStmt, Identifier,
    Literal, MemberAccess, MethodCall, NewExpr, ObjectLiteral,
    ObjectProperty, ReturnStmt, ThrowStmt, UnaryOp, VarDeclStmt,
)
from flashkit.decompile.ast.printer import AstPrinter
from flashkit.decompile.stack import BlockStackSim, BlockSimResult
from flashkit.graph.cfg import BasicBlock


# ── fixtures / helpers ─────────────────────────────────────────────────────


def _mk_abc(strings: list[str] | None = None,
            ints: list[int] | None = None,
            multinames: list[str] | None = None) -> AbcFile:
    """Build a minimal AbcFile with just enough pools for tests.

    The simulator reaches into ``abc.string_pool`` / ``abc.int_pool`` /
    ``abc.multiname_pool`` via the safe accessors (see abc/types.py).
    We construct a real AbcFile and wire up the pools directly.
    """
    from flashkit.abc.types import AbcFile as _AbcFile, MultinameInfo
    from flashkit.abc.constants import CONSTANT_QNAME

    abc = _AbcFile(
        major_version=46, minor_version=16,
        int_pool=[0] + (ints or []),
        uint_pool=[0],
        double_pool=[0.0],
        string_pool=[""] + (strings or []),
        namespace_pool=[],
        ns_set_pool=[],
        multiname_pool=[],
        methods=[],
        metadata=[],
        instances=[],
        classes=[],
        scripts=[],
        method_bodies=[],
    )
    # multinames: index 0 is reserved; simple QNames with empty namespace
    abc.multiname_pool.append(MultinameInfo(kind=0))  # sentinel
    for name in (multinames or []):
        s_idx = len(abc.string_pool)
        abc.string_pool.append(name)
        abc.multiname_pool.append(MultinameInfo(
            kind=CONSTANT_QNAME, ns=0, name=s_idx,
        ))
    return abc


def _block(code: bytes) -> tuple[BasicBlock, list]:
    """Decode ``code`` and wrap it in a single BasicBlock."""
    instrs = decode_instructions(code)
    last = instrs[-1]
    bb = BasicBlock(
        index=0, start_offset=0, end_offset=last.offset + last.size,
        instructions=instrs,
    )
    return bb, instrs


def _sim(abc: AbcFile, bb: BasicBlock) -> BlockSimResult:
    return BlockStackSim(abc).run(bb)


def _p(node) -> str:
    return AstPrinter().print(node)


# ── push opcodes ───────────────────────────────────────────────────────────


def test_pushbyte_leaves_literal_on_stack():
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_PUSHBYTE, 42]))

    result = _sim(abc, bb)

    assert result.statements == []
    assert len(result.stack) == 1
    assert _p(result.stack[0]) == "42"


def test_pushshort_signed_decoding():
    # pushshort: one u30 (sic — spec calls it s32 but encodes as u30)
    # positive small value
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_PUSHSHORT, 100]))
    result = _sim(abc, bb)
    assert _p(result.stack[0]) == "100"


def test_pushtrue_pushfalse_pushnull():
    abc = _mk_abc()
    for op, expected in [(OP_PUSHTRUE, "true"),
                         (OP_PUSHFALSE, "false"),
                         (OP_PUSHNULL, "null")]:
        bb, _ = _block(bytes([op]))
        result = _sim(abc, bb)
        assert _p(result.stack[0]) == expected


def test_pushstring_resolves_string_pool():
    abc = _mk_abc(strings=["hello"])  # string_pool index 1
    bb, _ = _block(bytes([OP_PUSHSTRING, 1]))

    result = _sim(abc, bb)

    assert _p(result.stack[0]) == '"hello"'


def test_pushint_resolves_int_pool():
    abc = _mk_abc(ints=[1000])  # int_pool index 1
    bb, _ = _block(bytes([OP_PUSHINT, 1]))

    result = _sim(abc, bb)

    assert _p(result.stack[0]) == "1000"


# ── locals ─────────────────────────────────────────────────────────────────


def test_getlocal_0_pushes_this_identifier():
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_GETLOCAL_0]))

    result = _sim(abc, bb)

    # Local 0 is conventionally ``this``.
    assert _p(result.stack[0]) == "this"


def test_getlocal_n_pushes_local_identifier():
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_GETLOCAL_1]))

    result = _sim(abc, bb)

    assert _p(result.stack[0]) == "_loc1_"


def test_getlocal_within_param_count_uses_arg_name():
    # A method with 2 parameters: locals 1..2 are the parameters
    # (_arg_1, _arg_2); local 3+ is a real local (_loc3_).
    abc = _mk_abc()
    sim = BlockStackSim(abc, param_count=2)

    bb, _ = _block(bytes([OP_GETLOCAL_1]))
    assert _p(sim.run(bb).stack[0]) == "_arg_1"

    bb2, _ = _block(bytes([OP_GETLOCAL_2]))
    assert _p(sim.run(bb2).stack[0]) == "_arg_2"

    # getlocal reg=3 is past the parameter range — stays as _loc3_.
    from flashkit.abc.opcodes import OP_GETLOCAL as _GL
    bb3, _ = _block(bytes([_GL, 3]))
    assert _p(sim.run(bb3).stack[0]) == "_loc3_"


def test_local0_name_override_for_static_methods():
    # Static methods have the class object in local 0, not `this`.
    abc = _mk_abc()
    sim = BlockStackSim(abc, local0_name="MyClass")
    bb, _ = _block(bytes([OP_GETLOCAL_0]))
    assert _p(sim.run(bb).stack[0]) == "MyClass"


def test_setlocal_uses_arg_name_when_in_param_range():
    abc = _mk_abc()
    sim = BlockStackSim(abc, param_count=1)
    # pushbyte 5; setlocal_1  -> _arg_1 = 5;
    bb, _ = _block(bytes([OP_PUSHBYTE, 5, OP_SETLOCAL_1]))
    result = sim.run(bb)
    assert len(result.statements) == 1
    assert _p(result.statements[0]) == "_arg_1 = 5;"


def test_setlocal_pops_and_emits_assignment():
    # pushbyte 5; setlocal_2
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_PUSHBYTE, 5, OP_SETLOCAL_2]))

    result = _sim(abc, bb)

    assert len(result.statements) == 1
    assert len(result.stack) == 0
    assert _p(result.statements[0]) == "_loc2_ = 5;"


# ── binary arithmetic ──────────────────────────────────────────────────────


@pytest.mark.parametrize("op,expected", [
    (OP_ADD, "+"), (OP_SUBTRACT, "-"), (OP_MULTIPLY, "*"),
    (OP_DIVIDE, "/"), (OP_MODULO, "%"),
    (OP_BITAND, "&"), (OP_BITOR, "|"), (OP_BITXOR, "^"),
])
def test_binary_arithmetic_builds_binary_expr(op, expected):
    abc = _mk_abc()
    # pushbyte 2; pushbyte 3; <op>   -> 2 <op> 3 on stack
    bb, _ = _block(bytes([OP_PUSHBYTE, 2, OP_PUSHBYTE, 3, op]))

    result = _sim(abc, bb)

    assert len(result.stack) == 1
    assert _p(result.stack[0]) == f"2 {expected} 3"


@pytest.mark.parametrize("op,expected", [
    (OP_EQUALS, "=="), (OP_STRICTEQUALS, "==="),
    (OP_LESSTHAN, "<"), (OP_LESSEQUALS, "<="),
])
def test_comparison_ops_build_binary_expr(op, expected):
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_PUSHBYTE, 1, OP_PUSHBYTE, 2, op]))
    result = _sim(abc, bb)
    assert _p(result.stack[0]) == f"1 {expected} 2"


def test_not_pushes_unary_expr():
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_PUSHTRUE, OP_NOT]))
    result = _sim(abc, bb)
    assert _p(result.stack[0]) == "!true"


def test_negate_pushes_unary_minus():
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_PUSHBYTE, 5, OP_NEGATE]))
    result = _sim(abc, bb)
    assert _p(result.stack[0]) == "-5"


def test_bitnot_pushes_unary_tilde():
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_PUSHBYTE, 5, OP_BITNOT]))
    result = _sim(abc, bb)
    assert _p(result.stack[0]) == "~5"


# ── coercion / convert are pass-through for the AST ───────────────────────


def test_convert_i_is_pass_through():
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_PUSHBYTE, 5, OP_CONVERT_I]))

    result = _sim(abc, bb)

    # int coercion is preserved as a CastExpr so patterns can spot it
    # (needed for tracking value types) but the printed form is int(5).
    assert _p(result.stack[0]) == "int(5)"


def test_convert_b_builds_bool_cast():
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_PUSHBYTE, 5, OP_CONVERT_B]))
    result = _sim(abc, bb)
    assert _p(result.stack[0]) == "Boolean(5)"


def test_convert_s_builds_string_cast():
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_PUSHBYTE, 5, OP_CONVERT_S]))
    result = _sim(abc, bb)
    assert _p(result.stack[0]) == "String(5)"


# ── property access ────────────────────────────────────────────────────────


def test_getproperty_builds_member_access():
    abc = _mk_abc(multinames=["name"])
    # getlocal_0 (this); getproperty name
    bb, _ = _block(bytes([OP_GETLOCAL_0, OP_GETPROPERTY, 1]))

    result = _sim(abc, bb)

    assert _p(result.stack[0]) == "this.name"


def test_setproperty_emits_assignment_statement():
    abc = _mk_abc(multinames=["x"])
    # getlocal_0; pushbyte 5; setproperty x
    bb, _ = _block(bytes([OP_GETLOCAL_0, OP_PUSHBYTE, 5, OP_SETPROPERTY, 1]))

    result = _sim(abc, bb)

    assert len(result.statements) == 1
    assert _p(result.statements[0]) == "this.x = 5;"


def test_findpropstrict_plus_setproperty_same_name_collapses():
    # findpropstrict foo; pushbyte 5; setproperty foo
    #   -> the findpropstrict "scope" push is the same identifier as
    #   the setproperty target, so this should print as ``foo = 5;``
    #   rather than ``foo.foo = 5;``.
    abc = _mk_abc(multinames=["foo"])
    bb, _ = _block(bytes([
        OP_FINDPROPSTRICT, 1,
        OP_PUSHBYTE, 5,
        OP_SETPROPERTY, 1,
    ]))

    result = _sim(abc, bb)

    assert len(result.statements) == 1
    assert _p(result.statements[0]) == "foo = 5;"


def test_getlex_builds_standalone_identifier():
    # getlex Math  -> pushes ``Math`` as a standalone identifier
    abc = _mk_abc(multinames=["Math"])
    bb, _ = _block(bytes([OP_GETLEX, 1]))

    result = _sim(abc, bb)

    assert _p(result.stack[0]) == "Math"


def test_findpropstrict_plus_callproperty_builds_function_call():
    # multiname index 1 == "trace"; string pool index 1 == "hi"
    abc = _mk_abc(strings=["hi"], multinames=["trace"])
    bb, _ = _block(bytes([
        OP_FINDPROPSTRICT, 1,
        OP_PUSHSTRING, 1,
        OP_CALLPROPERTY, 1, 1,      # callproperty mn=1, 1 arg
    ]))

    result = _sim(abc, bb)

    assert len(result.statements) == 0
    assert _p(result.stack[0]) == 'trace("hi")'


def test_callpropvoid_emits_expression_statement():
    abc = _mk_abc(strings=["hi"], multinames=["trace"])
    bb, _ = _block(bytes([
        OP_FINDPROPSTRICT, 1,
        OP_PUSHSTRING, 1,
        OP_CALLPROPVOID, 1, 1,
    ]))

    result = _sim(abc, bb)

    # callpropvoid doesn't leave a value on the stack; it emits the call
    # as a statement instead.
    assert len(result.stack) == 0
    assert len(result.statements) == 1
    assert _p(result.statements[0]) == 'trace("hi");'


def test_constructprop_builds_new_expression():
    abc = _mk_abc(strings=[], multinames=["Error"])
    # findpropstrict Error; constructprop Error, 0
    bb, _ = _block(bytes([
        OP_FINDPROPSTRICT, 1,
        OP_CONSTRUCTPROP, 1, 0,
    ]))

    result = _sim(abc, bb)

    assert _p(result.stack[0]) == "new Error()"


# ── new array / new object ────────────────────────────────────────────────


def test_newarray_collects_elements():
    abc = _mk_abc()
    # pushbyte 1; pushbyte 2; pushbyte 3; newarray 3
    bb, _ = _block(bytes([
        OP_PUSHBYTE, 1,
        OP_PUSHBYTE, 2,
        OP_PUSHBYTE, 3,
        OP_NEWARRAY, 3,
    ]))

    result = _sim(abc, bb)

    assert _p(result.stack[0]) == "[1, 2, 3]"


def test_newobject_collects_key_value_pairs():
    abc = _mk_abc(strings=["a", "b"])
    # pushstring "a"; pushbyte 1; pushstring "b"; pushbyte 2; newobject 2
    bb, _ = _block(bytes([
        OP_PUSHSTRING, 1, OP_PUSHBYTE, 1,
        OP_PUSHSTRING, 2, OP_PUSHBYTE, 2,
        OP_NEWOBJECT, 2,
    ]))

    result = _sim(abc, bb)

    assert _p(result.stack[0]) == "{a: 1, b: 2}"


# ── stack manipulation ────────────────────────────────────────────────────


def test_pop_discards_top_of_stack_as_statement():
    abc = _mk_abc(strings=["hi"], multinames=["trace"])
    # findpropstrict trace; pushstring hi; callproperty(1)  (value result);
    # pop   -> discard; emitted as expression statement
    bb, _ = _block(bytes([
        OP_FINDPROPSTRICT, 1,
        OP_PUSHSTRING, 1,
        OP_CALLPROPERTY, 1, 1,
        OP_POP,
    ]))

    result = _sim(abc, bb)

    assert len(result.stack) == 0
    # Side-effecting call discarded with pop becomes an ExpressionStmt.
    assert _p(result.statements[0]) == 'trace("hi");'


def test_pop_of_pure_value_is_dropped_silently():
    # pushbyte 5; pop -> no side effect; nothing emitted
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_PUSHBYTE, 5, OP_POP]))

    result = _sim(abc, bb)

    assert result.statements == []
    assert result.stack == []


def test_dup_duplicates_top_of_stack():
    abc = _mk_abc()
    # pushbyte 5; dup -> two copies of 5 on stack
    bb, _ = _block(bytes([OP_PUSHBYTE, 5, OP_DUP]))
    result = _sim(abc, bb)
    assert len(result.stack) == 2
    assert _p(result.stack[0]) == "5"
    assert _p(result.stack[1]) == "5"


# ── control-flow terminators ──────────────────────────────────────────────


def test_returnvalue_emits_return_statement():
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_PUSHBYTE, 5, OP_RETURNVALUE]))

    result = _sim(abc, bb)

    assert len(result.statements) == 1
    assert _p(result.statements[0]) == "return 5;"
    assert result.terminator == "return"


def test_returnvoid_emits_bare_return():
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_RETURNVOID]))
    result = _sim(abc, bb)
    assert _p(result.statements[0]) == "return;"
    assert result.terminator == "return"


def test_throw_emits_throw_statement():
    abc = _mk_abc(multinames=["Error"])
    bb, _ = _block(bytes([
        OP_FINDPROPSTRICT, 1,
        OP_CONSTRUCTPROP, 1, 0,
        OP_THROW,
    ]))

    result = _sim(abc, bb)

    assert len(result.statements) == 1
    assert _p(result.statements[0]) == "throw new Error();"
    assert result.terminator == "throw"


def test_jump_records_unconditional_terminator_no_condition():
    abc = _mk_abc()
    bb, _ = _block(bytes([OP_JUMP]) + _encode_s24(0))
    result = _sim(abc, bb)
    assert result.terminator == "jump"
    assert result.branch_condition is None


def test_iftrue_records_condition_expression():
    abc = _mk_abc()
    # pushbyte 1; pushbyte 2; equals; iftrue +0
    bb, _ = _block(
        bytes([OP_PUSHBYTE, 1, OP_PUSHBYTE, 2, OP_EQUALS])
        + bytes([OP_IFTRUE]) + _encode_s24(0)
    )
    result = _sim(abc, bb)
    assert result.terminator == "if"
    # Branch taken when condition is truthy — condition is ``1 == 2``
    assert _p(result.branch_condition) == "1 == 2"
    # No value left on the stack after iftrue consumes it.
    assert result.stack == []


def test_iffalse_inverts_the_condition():
    abc = _mk_abc()
    # pushbyte 1; pushbyte 2; equals; iffalse +0
    # iffalse branches when the condition is falsy -> structurer sees
    # the inverted condition.
    bb, _ = _block(
        bytes([OP_PUSHBYTE, 1, OP_PUSHBYTE, 2, OP_EQUALS])
        + bytes([OP_IFFALSE]) + _encode_s24(0)
    )
    result = _sim(abc, bb)
    assert result.terminator == "if"
    assert _p(result.branch_condition) == "!(1 == 2)"


# ── real-SWF smoke ─────────────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("FLASHKIT_TEST_SWF"),
    reason="opt-in: set FLASHKIT_TEST_SWF=path/to/file.swf",
)
def test_real_swf_stack_simulator_processes_every_block():
    from flashkit.graph.cfg import build_cfg_from_bytecode
    from flashkit.workspace import Workspace

    ws = Workspace()
    ws.load_swf(os.environ["FLASHKIT_TEST_SWF"])

    total_blocks = 0
    for abc in ws.abc_blocks:
        for body in abc.method_bodies:
            cfg = build_cfg_from_bytecode(
                decode_instructions(body.code), list(body.exceptions),
            )
            sim = BlockStackSim(abc)
            for bb in cfg.blocks:
                # The simulator is allowed to leave expressions on the
                # stack (values that will be consumed in a successor
                # block, or that the next block's phi would bind). It
                # must not crash — that's all we validate here.
                sim.run(bb)
                total_blocks += 1
    assert total_blocks > 0
