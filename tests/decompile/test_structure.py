"""Tests for the CFG-based structuring algorithm.

Each test builds a full decode -> CFG -> dominators -> loops -> stack
sim -> structure pipeline on a synthetic method body, then asserts the
printed source matches the expected AS3. This is the first phase that
produces end-to-end decompiled source; Phase 7 will add exception
regions and switches, Phase 8 will add idiom patterns (for-loops,
ternary, etc.), Phase 9 will wire it into the public API.
"""

from __future__ import annotations

import os

import pytest

from flashkit.abc.builder import _encode_s24
from flashkit.abc.disasm import decode_instructions
from flashkit.abc.opcodes import (
    OP_ADD, OP_EQUALS, OP_GETLOCAL_1, OP_GETLOCAL_2,
    OP_IFFALSE, OP_IFTRUE, OP_JUMP, OP_PUSHBYTE,
    OP_RETURNVALUE, OP_RETURNVOID, OP_SETLOCAL_1,
)
from flashkit.abc.types import AbcFile, MultinameInfo
from flashkit.decompile.ast.printer import AstPrinter
from flashkit.decompile.stack import BlockStackSim
from flashkit.decompile.structure import structure_method
from flashkit.graph.cfg import build_cfg_from_bytecode
from flashkit.graph.dominators import compute_idom, compute_ipostdom
from flashkit.graph.loops import find_loops


# ── helpers ────────────────────────────────────────────────────────────────


def _empty_abc() -> AbcFile:
    return AbcFile(
        major_version=46, minor_version=16,
        int_pool=[0], uint_pool=[0], double_pool=[0.0],
        string_pool=[""], namespace_pool=[], ns_set_pool=[],
        multiname_pool=[MultinameInfo(kind=0)],
        methods=[], metadata=[], instances=[], classes=[],
        scripts=[], method_bodies=[],
    )


def _pipeline(code: bytes, abc: AbcFile | None = None) -> str:
    """Run the full structuring pipeline on raw bytecode.

    Returns the printed AS3 source.
    """
    abc = abc or _empty_abc()
    instrs = decode_instructions(code)
    cfg = build_cfg_from_bytecode(instrs, exceptions=[])
    idom = compute_idom(cfg)
    ipostdom = compute_ipostdom(cfg)
    loops = find_loops(cfg, idom)
    sim = BlockStackSim(abc)
    block_results = {bb.index: sim.run(bb) for bb in cfg.blocks}

    root = structure_method(cfg, idom, ipostdom, loops, block_results)
    return AstPrinter().print(root)


def _br(here: int, size: int, target: int) -> bytes:
    return _encode_s24(target - (here + size))


# ── straight-line method ───────────────────────────────────────────────────


def test_structure_straight_line_returnvoid():
    # returnvoid
    src = _pipeline(bytes([OP_RETURNVOID]))
    assert src == (
        "{\n"
        "    return;\n"
        "}"
    )


def test_structure_straight_line_returnvalue():
    # pushbyte 1; returnvalue
    src = _pipeline(bytes([OP_PUSHBYTE, 1, OP_RETURNVALUE]))
    assert src == (
        "{\n"
        "    return 1;\n"
        "}"
    )


def test_structure_straight_line_with_setlocal():
    # pushbyte 7; setlocal_1; returnvoid
    src = _pipeline(bytes([OP_PUSHBYTE, 7, OP_SETLOCAL_1, OP_RETURNVOID]))
    assert src == (
        "{\n"
        "    _loc1_ = 7;\n"
        "    return;\n"
        "}"
    )


# ── if/else ────────────────────────────────────────────────────────────────


def test_structure_if_only():
    # if (a == b) { return 1; }
    # return 0;
    #
    # Layout:
    #   0: getlocal_1              (1)
    #   1: getlocal_2              (1)
    #   2: equals                  (1)
    #   3: iffalse -> skip (1+3)   (4)
    #   7: pushbyte 1              (2)
    #   9: returnvalue             (1)
    #  10: pushbyte 0              (2)   <- skip target
    #  12: returnvalue             (1)
    #
    # iffalse jumps when condition is falsy, so the taken branch is the
    # skip-past code. Fall-through (offset 7) is the if-body.
    skip_target = 10
    code = (
        bytes([OP_GETLOCAL_1, OP_GETLOCAL_2, OP_EQUALS])
        + bytes([OP_IFFALSE]) + _br(3, 4, skip_target)
        + bytes([OP_PUSHBYTE, 1, OP_RETURNVALUE])
        + bytes([OP_PUSHBYTE, 0, OP_RETURNVALUE])
    )

    src = _pipeline(code)

    # Both arms return, so there is no merge point (ipostdom = -1). The
    # structurer emits both arms as an if/else. Phase 8 or a later
    # simplification pass can collapse ``if(c) { return x } else {
    # return y }`` to an early-return idiom — for now the if/else form
    # is exactly what ffdec also emits.
    assert src == (
        "{\n"
        "    if (_loc1_ == _loc2_) {\n"
        "        return 1;\n"
        "    } else {\n"
        "        return 0;\n"
        "    }\n"
        "}"
    )


def test_structure_if_else():
    # if (c) { return 1; } else { return 2; }
    #
    # Layout (iftrue jumps to the 'then' arm):
    #   0: getlocal_1                        (1)
    #   1: iftrue -> then_target (1+3)       (4)
    #   5: pushbyte 2                        (2)   <- fall-through (else)
    #   7: returnvalue                       (1)
    #   8: pushbyte 1                        (2)   <- then_target
    #  10: returnvalue                       (1)
    then_target = 8
    code = (
        bytes([OP_GETLOCAL_1])
        + bytes([OP_IFTRUE]) + _br(1, 4, then_target)
        + bytes([OP_PUSHBYTE, 2, OP_RETURNVALUE])
        + bytes([OP_PUSHBYTE, 1, OP_RETURNVALUE])
    )

    src = _pipeline(code)

    assert src == (
        "{\n"
        "    if (_loc1_) {\n"
        "        return 1;\n"
        "    } else {\n"
        "        return 2;\n"
        "    }\n"
        "}"
    )


# ── while loop ─────────────────────────────────────────────────────────────


def test_structure_simple_while_loop():
    # var i = 0;
    # while (i == 0) { i = i + 1; }
    # return i;
    #
    # AVM2 compiles a `while` as:
    #
    #   pushbyte 0; setlocal_1         ;; i = 0
    # loop_header:
    #   getlocal_1; pushbyte 0; equals
    #   iffalse -> after_loop
    #   getlocal_1; pushbyte 1; add
    #   setlocal_1
    #   jump -> loop_header
    # after_loop:
    #   getlocal_1; returnvalue
    #
    # We manually lay these out so offsets are easy to compute.
    #
    # Offsets (bytes per instr shown in []):
    #   0: pushbyte 0           [2]
    #   2: setlocal_1           [1]
    #   3: getlocal_1           [1]  <- loop_header (offset 3)
    #   4: pushbyte 0           [2]
    #   6: equals               [1]
    #   7: iffalse (s24)        [4] -> after_loop (22)
    #  11: getlocal_1           [1]
    #  12: pushbyte 1           [2]
    #  14: add                  [1]
    #  15: setlocal_1           [1]
    #  16: jump (s24)           [4] -> loop_header (3)
    #  20: (unreachable)  — actually 22 is after_loop.
    #  Wait, 16 + 4 = 20; after_loop must be at 20 so iffalse target
    #  = 20.
    #
    # Re-number: after_loop = 20, loop_header = 3.
    loop_header = 3
    after_loop = 20
    code = (
        bytes([OP_PUSHBYTE, 0, OP_SETLOCAL_1])                        # 0..2
        + bytes([OP_GETLOCAL_1, OP_PUSHBYTE, 0, OP_EQUALS])           # 3..6
        + bytes([OP_IFFALSE]) + _br(7, 4, after_loop)                 # 7..10
        + bytes([OP_GETLOCAL_1, OP_PUSHBYTE, 1, OP_ADD])              # 11..14
        + bytes([OP_SETLOCAL_1])                                       # 15
        + bytes([OP_JUMP]) + _br(16, 4, loop_header)                  # 16..19
        + bytes([OP_GETLOCAL_1, OP_RETURNVALUE])                      # 20..21
    )

    src = _pipeline(code)

    assert src == (
        "{\n"
        "    _loc1_ = 0;\n"
        "    while (_loc1_ == 0) {\n"
        "        _loc1_ = _loc1_ + 1;\n"
        "    }\n"
        "    return _loc1_;\n"
        "}"
    )


# ── real-SWF smoke ─────────────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("FLASHKIT_TEST_SWF"),
    reason="opt-in: set FLASHKIT_TEST_SWF=path/to/file.swf",
)
def test_real_swf_structure_method_terminates_on_every_method():
    """Every method body in a real SWF structures without crashing,
    in bounded time."""
    import time
    from flashkit.workspace import Workspace

    ws = Workspace()
    ws.load_swf(os.environ["FLASHKIT_TEST_SWF"])

    slowest = 0.0
    slowest_method: int | None = None
    total = 0
    for abc in ws.abc_blocks:
        for body in abc.method_bodies:
            cfg = build_cfg_from_bytecode(
                decode_instructions(body.code), list(body.exceptions),
            )
            if not cfg.blocks:
                continue
            idom = compute_idom(cfg)
            ipostdom = compute_ipostdom(cfg)
            loops = find_loops(cfg, idom)
            sim = BlockStackSim(abc)
            block_results = {bb.index: sim.run(bb) for bb in cfg.blocks}

            t0 = time.perf_counter()
            structure_method(cfg, idom, ipostdom, loops, block_results)
            elapsed = time.perf_counter() - t0
            total += 1
            if elapsed > slowest:
                slowest = elapsed
                slowest_method = body.method

    assert total > 0
    # We don't enforce a hard budget because method size varies, but we
    # surface the worst case so regressions are visible in CI output.
    print(f"\nStructured {total} methods. Slowest: {slowest:.3f}s "
          f"(method #{slowest_method})")
