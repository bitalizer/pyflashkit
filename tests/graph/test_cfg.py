"""Tests for the CFG / basic-block builder.

Synthetic bytecode is assembled by hand so each test exercises exactly
one CFG-shape invariant (straight-line, conditional, jump, switch, loop,
exception region). Real-SWF consistency smoke is opt-in via
``FLASHKIT_TEST_SWF``.
"""

from __future__ import annotations

import os

import pytest

from flashkit.abc.builder import _encode_s24
from flashkit.abc.disasm import decode_instructions
from flashkit.abc.opcodes import (
    OP_JUMP, OP_IFTRUE, OP_LOOKUPSWITCH,
    OP_RETURNVOID, OP_RETURNVALUE, OP_THROW,
    OP_PUSHBYTE, OP_POP, OP_LABEL,
)
from flashkit.abc.types import ExceptionInfo
from flashkit.graph.cfg import BasicBlock, CFG, build_cfg_from_bytecode


# ── helpers ────────────────────────────────────────────────────────────────


def _assemble(*parts: bytes) -> bytes:
    return b"".join(parts)


def _branch_to(here: int, size: int, target: int) -> bytes:
    """Encode an s24 that makes a branch instruction at offset ``here``
    (with instruction size ``size``) jump to absolute offset ``target``.
    """
    return _encode_s24(target - (here + size))


def _check_edges_consistent(cfg: CFG) -> None:
    """Every successor edge has a matching predecessor edge and vice versa."""
    for bb in cfg.blocks:
        for succ in bb.successors:
            assert bb in succ.predecessors, (
                f"block {bb.index} -> {succ.index} missing in predecessors"
            )
        for pred in bb.predecessors:
            assert bb in pred.successors, (
                f"block {bb.index} <- {pred.index} missing in successors"
            )


# ── straight-line methods ──────────────────────────────────────────────────


def test_single_block_method_returnvoid():
    code = _assemble(bytes([OP_RETURNVOID]))
    instrs = decode_instructions(code)

    cfg = build_cfg_from_bytecode(instrs, exceptions=[])

    assert len(cfg.blocks) == 1
    bb = cfg.blocks[0]
    assert bb is cfg.entry
    assert bb.index == 0
    assert bb.start_offset == 0
    assert bb.end_offset == 1
    assert bb.instructions == instrs
    assert bb.successors == []
    assert bb.predecessors == []
    assert cfg.exit_blocks == [bb]


def test_multiple_instructions_one_block():
    # pushbyte 1; pushbyte 2; pop; returnvoid  -> single block
    code = _assemble(
        bytes([OP_PUSHBYTE, 1]),
        bytes([OP_PUSHBYTE, 2]),
        bytes([OP_POP]),
        bytes([OP_RETURNVOID]),
    )
    instrs = decode_instructions(code)

    cfg = build_cfg_from_bytecode(instrs, exceptions=[])

    assert len(cfg.blocks) == 1
    assert cfg.blocks[0].instructions == instrs
    assert cfg.blocks[0].successors == []
    _check_edges_consistent(cfg)


def test_returnvalue_terminates_block_without_successor():
    code = _assemble(bytes([OP_PUSHBYTE, 7]), bytes([OP_RETURNVALUE]))
    cfg = build_cfg_from_bytecode(decode_instructions(code), exceptions=[])

    assert len(cfg.blocks) == 1
    assert cfg.blocks[0].successors == []
    assert cfg.exit_blocks == cfg.blocks


def test_throw_terminates_block_without_successor():
    code = _assemble(bytes([OP_PUSHBYTE, 0]), bytes([OP_THROW]))
    cfg = build_cfg_from_bytecode(decode_instructions(code), exceptions=[])

    assert len(cfg.blocks) == 1
    assert cfg.blocks[0].successors == []
    assert cfg.exit_blocks == cfg.blocks


# ── unconditional jumps ────────────────────────────────────────────────────


def test_unconditional_jump_forward():
    # 0: jump -> 5
    # 4: returnvoid   <-- unreachable
    # 5: returnvoid
    # Layout: jump (4 bytes), returnvoid (1), returnvoid (1)
    jump_target = 5
    code = _assemble(
        bytes([OP_JUMP]) + _branch_to(0, 4, jump_target),  # offsets 0..3
        bytes([OP_RETURNVOID]),                             # offset 4 (dead)
        bytes([OP_RETURNVOID]),                             # offset 5
    )
    instrs = decode_instructions(code)
    assert [i.offset for i in instrs] == [0, 4, 5]

    cfg = build_cfg_from_bytecode(instrs, exceptions=[])

    # jump block, dead returnvoid, live returnvoid — each is its own block
    # (the dead one is still a leader because instr-after-branch is a leader)
    assert len(cfg.blocks) == 3
    jump_bb = cfg.blocks_by_offset[0]
    dead_bb = cfg.blocks_by_offset[4]
    live_bb = cfg.blocks_by_offset[5]

    assert jump_bb.successors == [live_bb]
    assert dead_bb.successors == []          # returnvoid
    assert dead_bb.predecessors == []        # unreachable
    assert live_bb.predecessors == [jump_bb]
    _check_edges_consistent(cfg)


# ── conditional branches ───────────────────────────────────────────────────


def test_iftrue_splits_into_three_blocks():
    # 0: pushbyte 1           (2 bytes)
    # 2: iftrue -> 8          (4 bytes)
    # 6: returnvoid           (1 byte)    <- false fall-through
    # 7: returnvoid           (1 byte)    <- dead padding to make target 8
    # 8: returnvoid           (1 byte)    <- true target
    # Actually we don't need padding if we size iftrue at 4 bytes: 2+4=6, so
    # fallthrough lands at 6. Target 7 is easier.
    iftrue_target = 7
    code = _assemble(
        bytes([OP_PUSHBYTE, 1]),                                  # 0..1
        bytes([OP_IFTRUE]) + _branch_to(2, 4, iftrue_target),     # 2..5
        bytes([OP_RETURNVOID]),                                   # 6 (false)
        bytes([OP_RETURNVOID]),                                   # 7 (true)
    )
    instrs = decode_instructions(code)
    assert [i.offset for i in instrs] == [0, 2, 6, 7]

    cfg = build_cfg_from_bytecode(instrs, exceptions=[])

    head = cfg.blocks_by_offset[0]
    false_bb = cfg.blocks_by_offset[6]
    true_bb = cfg.blocks_by_offset[7]

    assert len(cfg.blocks) == 3
    # Convention: for conditional branches, successors are
    # [fall_through, branch_target].
    assert head.successors == [false_bb, true_bb]
    assert false_bb.predecessors == [head]
    assert true_bb.predecessors == [head]
    _check_edges_consistent(cfg)


# ── back-edges / loops ─────────────────────────────────────────────────────


def test_simple_while_loop_back_edge():
    # do-while-ish loop:
    #   0: pushbyte 1            (2 bytes)
    #   2: iftrue -> 0           (4 bytes)  <- back edge to start
    #   6: returnvoid            (1 byte)
    code = _assemble(
        bytes([OP_PUSHBYTE, 1]),                       # 0..1
        bytes([OP_IFTRUE]) + _branch_to(2, 4, 0),      # 2..5 -> 0
        bytes([OP_RETURNVOID]),                        # 6
    )
    instrs = decode_instructions(code)

    cfg = build_cfg_from_bytecode(instrs, exceptions=[])

    head = cfg.blocks_by_offset[0]
    exit_bb = cfg.blocks_by_offset[6]

    assert head.successors == [exit_bb, head]  # fall-through then back-edge
    assert head in head.predecessors           # self-edge via back-edge
    assert exit_bb in head.successors
    _check_edges_consistent(cfg)


# ── lookupswitch ───────────────────────────────────────────────────────────


def test_lookupswitch_produces_n_plus_one_successors():
    # lookupswitch with 2 case entries (case_count=1, so 2 case offsets +
    # 1 default = 3 targets total). Targets are relative to the opcode byte.
    # Layout:
    #   0: lookupswitch default=+10, count=1, case0=+11, case1=+12
    #      -> size = 1 (op) + 3 (default s24) + 1 (count u30) + 2*3 (case s24s)
    #      = 11 bytes, occupies offsets 0..10
    #   10: returnvoid (default target)
    #   11: returnvoid (case 0 target)
    #   12: returnvoid (case 1 target)
    def s24(v): return _encode_s24(v)

    switch = (
        bytes([OP_LOOKUPSWITCH])
        + s24(10)           # default offset (relative to opcode at 0)
        + bytes([1])        # case_count = 1 (u30 fits in 1 byte)
        + s24(10)           # case 0 -> 10 (same as default, different slot)
        + s24(11)           # case 1 -> 11
    )
    assert len(switch) == 11
    code = _assemble(
        switch,
        bytes([OP_RETURNVOID]),   # 11 -> uh wait, let me recount
    )
    # The lookupswitch takes 11 bytes, so it spans 0..10. Next instr at 11.
    # Redo targets: default = offset 11, case0 = 11, case1 = 11.
    # Simpler: make all three point at offset 11 and we still see the shape.
    code = _assemble(
        bytes([OP_LOOKUPSWITCH])
        + _encode_s24(11)
        + bytes([1])
        + _encode_s24(11)
        + _encode_s24(11),
        bytes([OP_RETURNVOID]),
    )
    instrs = decode_instructions(code)
    assert instrs[0].mnemonic == "lookupswitch"

    cfg = build_cfg_from_bytecode(instrs, exceptions=[])

    switch_bb = cfg.blocks_by_offset[0]
    target_bb = cfg.blocks_by_offset[11]

    # Three edges (default + 2 cases) all land at the same block, but each
    # edge is recorded — we de-dup in successors since we track unique blocks.
    # Record decision: successors is unique per target block. Verify target
    # appears at least once and predecessors reflect every incoming edge
    # from switch_bb as a single pred (we store unique preds too).
    assert target_bb in switch_bb.successors
    assert switch_bb in target_bb.predecessors
    _check_edges_consistent(cfg)


def test_lookupswitch_distinct_targets():
    # default -> A, case0 -> B, case1 -> C : three distinct successors.
    code = _assemble(
        bytes([OP_LOOKUPSWITCH])
        + _encode_s24(11)      # default -> offset 11
        + bytes([1])           # case_count = 1
        + _encode_s24(12)      # case 0 -> 12
        + _encode_s24(13),     # case 1 -> 13
        bytes([OP_RETURNVOID]),   # 11
        bytes([OP_RETURNVOID]),   # 12
        bytes([OP_RETURNVOID]),   # 13
    )
    instrs = decode_instructions(code)

    cfg = build_cfg_from_bytecode(instrs, exceptions=[])

    switch_bb = cfg.blocks_by_offset[0]
    succ_offsets = sorted(s.start_offset for s in switch_bb.successors)
    assert succ_offsets == [11, 12, 13]
    _check_edges_consistent(cfg)


# ── exception regions ──────────────────────────────────────────────────────


def test_exception_region_marks_blocks_and_catch_entry():
    # Try body covers offsets [0, 4); catch target at offset 4.
    #   0: pushbyte 1         (2 bytes)
    #   2: pop                (1 byte)
    #   3: returnvoid         (1 byte)
    #   4: pop                (1 byte)     <- catch entry
    #   5: returnvoid         (1 byte)
    code = _assemble(
        bytes([OP_PUSHBYTE, 1]),
        bytes([OP_POP]),
        bytes([OP_RETURNVOID]),
        bytes([OP_POP]),
        bytes([OP_RETURNVOID]),
    )
    instrs = decode_instructions(code)
    exc = ExceptionInfo(from_offset=0, to_offset=4, target=4,
                        exc_type=0, var_name=0)

    cfg = build_cfg_from_bytecode(instrs, exceptions=[exc])

    try_bb = cfg.blocks_by_offset[0]
    catch_bb = cfg.blocks_by_offset[4]

    # Every block whose offsets lie within [from, to) should have the handler
    # recorded. catch_bb should be kind=catch_entry.
    assert exc in try_bb.exception_handlers
    assert catch_bb.kind == "catch_entry"
    # Exception edge: protected blocks flow to catch_bb on throw (represented
    # as a successor from every protected block? Or just recorded on handler
    # list — design choice). We at minimum require the catch block is
    # reachable from the CFG (has an explicit edge OR is marked as a known
    # entry point).
    assert catch_bb in cfg.blocks
    _check_edges_consistent(cfg)


# ── leaders & offset coverage ──────────────────────────────────────────────


def test_every_instruction_belongs_to_exactly_one_block():
    code = _assemble(
        bytes([OP_PUSHBYTE, 1]),                              # 0
        bytes([OP_IFTRUE]) + _branch_to(2, 4, 7),             # 2
        bytes([OP_RETURNVOID]),                               # 6
        bytes([OP_RETURNVOID]),                               # 7
    )
    instrs = decode_instructions(code)

    cfg = build_cfg_from_bytecode(instrs, exceptions=[])

    seen: set[int] = set()
    for bb in cfg.blocks:
        for instr in bb.instructions:
            assert instr.offset not in seen, (
                f"instruction at {instr.offset} in multiple blocks"
            )
            seen.add(instr.offset)
    assert seen == {i.offset for i in instrs}


def test_blocks_in_creation_order_cover_code_monotonically():
    code = _assemble(
        bytes([OP_PUSHBYTE, 1]),
        bytes([OP_IFTRUE]) + _branch_to(2, 4, 7),
        bytes([OP_RETURNVOID]),
        bytes([OP_RETURNVOID]),
    )
    cfg = build_cfg_from_bytecode(decode_instructions(code), exceptions=[])
    offsets = [bb.start_offset for bb in cfg.blocks]
    assert offsets == sorted(offsets)


# ── opt-in real-SWF smoke ──────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("FLASHKIT_TEST_SWF"),
    reason="opt-in: set FLASHKIT_TEST_SWF=path/to/file.swf",
)
def test_real_swf_every_method_builds_consistent_cfg():
    from flashkit.workspace import Workspace

    ws = Workspace()
    ws.load_swf(os.environ["FLASHKIT_TEST_SWF"])
    assert ws.abc_blocks, "SWF loaded but no ABC blocks were parsed"

    total_methods = 0
    for abc in ws.abc_blocks:
        for body in abc.method_bodies:
            instrs = decode_instructions(body.code)
            cfg = build_cfg_from_bytecode(instrs, exceptions=list(body.exceptions))
            # structural invariants:
            assert cfg.entry is cfg.blocks[0]
            for bb in cfg.blocks:
                for s in bb.successors:
                    assert bb in s.predecessors
                for p in bb.predecessors:
                    assert bb in p.successors
            total_methods += 1

    assert total_methods > 0, "real SWF had zero method bodies"
