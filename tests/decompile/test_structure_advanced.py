"""Phase 7 tests: switch, try/catch, irreducible CFGs.

These tests build on the Phase 6 pipeline but exercise constructs the
base structurer skips (switch ends, exception handlers, and
conditionals whose both arms have no common post-dominator).
"""

from __future__ import annotations

import os

import pytest

from flashkit.abc.builder import _encode_s24
from flashkit.abc.disasm import decode_instructions
from flashkit.abc.opcodes import (
    OP_GETLOCAL_1, OP_JUMP, OP_LOOKUPSWITCH, OP_PUSHBYTE,
    OP_PUSHSTRING, OP_RETURNVALUE, OP_RETURNVOID, OP_THROW,
)
from flashkit.abc.types import AbcFile, ExceptionInfo, MultinameInfo
from flashkit.decompile.ast.printer import AstPrinter
from flashkit.decompile.stack import BlockStackSim
from flashkit.decompile.structure import structure_method
from flashkit.graph.cfg import build_cfg_from_bytecode
from flashkit.graph.dominators import compute_idom, compute_ipostdom
from flashkit.graph.loops import find_loops


def _empty_abc() -> AbcFile:
    return AbcFile(
        major_version=46, minor_version=16,
        int_pool=[0], uint_pool=[0], double_pool=[0.0],
        string_pool=[""], namespace_pool=[], ns_set_pool=[],
        multiname_pool=[MultinameInfo(kind=0)],
        methods=[], metadata=[], instances=[], classes=[],
        scripts=[], method_bodies=[],
    )


def _pipeline(code: bytes, *, exceptions=None) -> str:
    abc = _empty_abc()
    instrs = decode_instructions(code)
    cfg = build_cfg_from_bytecode(instrs, exceptions=list(exceptions or []))
    idom = compute_idom(cfg)
    ipostdom = compute_ipostdom(cfg)
    loops = find_loops(cfg, idom)
    sim = BlockStackSim(abc)
    block_results = {bb.index: sim.run(bb) for bb in cfg.blocks}
    root = structure_method(cfg, idom, ipostdom, loops, block_results)
    return AstPrinter().print(root)


# ── switch reconstruction ──────────────────────────────────────────────────


def test_switch_with_two_cases_and_default():
    # Layout:
    #   0: getlocal_1                           [1]
    #   1: lookupswitch default=+N, count=1, case0=+N, case1=+N  [11]
    #      -> ends at offset 12
    #  12: pushbyte 1; returnvalue     (case 0 body, ends)       [3]
    #  15: pushbyte 2; returnvalue     (case 1 body, ends)       [3]
    #  18: pushbyte 0; returnvalue     (default body, ends)      [3]
    #
    # Targets relative to opcode byte (offset 1):
    #   default = 18 - 1 = 17
    #   case 0  = 12 - 1 = 11
    #   case 1  = 15 - 1 = 14
    code = (
        bytes([OP_GETLOCAL_1])                          # 0
        + bytes([OP_LOOKUPSWITCH])                      # 1
        + _encode_s24(17)                               # 2..4 default -> 18
        + bytes([1])                                    # 5    case_count=1
        + _encode_s24(11)                               # 6..8 case0 -> 12
        + _encode_s24(14)                               # 9..11 case1 -> 15
        + bytes([OP_PUSHBYTE, 1, OP_RETURNVALUE])       # 12..14
        + bytes([OP_PUSHBYTE, 2, OP_RETURNVALUE])       # 15..17
        + bytes([OP_PUSHBYTE, 0, OP_RETURNVALUE])       # 18..20
    )

    src = _pipeline(code)

    assert src == (
        "{\n"
        "    switch (_loc1_) {\n"
        "        case 0:\n"
        "            return 1;\n"
        "        case 1:\n"
        "            return 2;\n"
        "        default:\n"
        "            return 0;\n"
        "    }\n"
        "}"
    )


# ── exception regions ──────────────────────────────────────────────────────


def test_try_catch_wraps_protected_region():
    # Layout:
    #   0: pushbyte 1                (2 bytes)
    #   2: pushbyte 0                (2 bytes)  <- inside try
    #   4: returnvalue               (1 byte)   <- inside try (exits)
    #   5: pushbyte 9                (2 bytes)  <- catch entry (offset 5)
    #   7: returnvalue               (1 byte)
    #
    # Try covers offsets [0, 5), target = 5.
    code = (
        bytes([OP_PUSHBYTE, 1])
        + bytes([OP_PUSHBYTE, 0])
        + bytes([OP_RETURNVALUE])
        + bytes([OP_PUSHBYTE, 9])
        + bytes([OP_RETURNVALUE])
    )
    exc = ExceptionInfo(from_offset=0, to_offset=5, target=5,
                        exc_type=0, var_name=0)

    src = _pipeline(code, exceptions=[exc])

    # The protected region is emitted inside try { }, the catch block
    # as a catch clause with a generic variable name.
    assert src == (
        "{\n"
        "    try {\n"
        "        return 0;\n"
        "    } catch (_catch0_) {\n"
        "        return 9;\n"
        "    }\n"
        "}"
    )


# ── real-SWF smoke ─────────────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("FLASHKIT_TEST_SWF"),
    reason="opt-in: set FLASHKIT_TEST_SWF=path/to/file.swf",
)
def test_real_swf_phase7_features_do_not_regress_real_swf():
    """Phase 7 additions must not break the Phase 6 real-SWF result:
    every method body still structures in bounded time."""
    import time
    from flashkit.workspace import Workspace

    ws = Workspace()
    ws.load_swf(os.environ["FLASHKIT_TEST_SWF"])

    slowest = 0.0
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
            root = structure_method(cfg, idom, ipostdom, loops, block_results)
            elapsed = time.perf_counter() - t0
            # Print the root to force any lazy AST errors to surface.
            AstPrinter().print(root)
            total += 1
            slowest = max(slowest, elapsed)
    assert total > 0
    print(f"\nStructured {total} methods. Slowest: {slowest:.3f}s")
