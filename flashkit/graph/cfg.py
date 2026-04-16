"""Basic-block / control-flow graph builder for AVM2 bytecode.

Given a decoded instruction stream and an exception table, produces a
control-flow graph of basic blocks. Each block is a maximal run of
straight-line instructions ending in a terminator (branch, return,
throw) or at a leader boundary.

The algorithm is linear in the number of instructions:
  1. Collect leader offsets: method entry, every branch/switch target,
     every instruction immediately after a branch or terminator, and
     every exception region boundary (``from_offset``, ``to_offset``,
     ``target``).
  2. Slice the instruction list at leader boundaries into blocks.
  3. Wire up successors from each block's terminator.
  4. Invert to fill predecessors.

Exception edges are represented by attaching every ``ExceptionInfo``
whose protected range covers a block to that block's
``exception_handlers`` list. The catch-entry block is marked with
``kind="catch_entry"`` and is always a leader so it appears as its own
block even though no ordinary edge reaches it.

Out of scope for Phase 1: dominators, reducibility, loop detection.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Literal

from ..abc.disasm import Instruction
from ..abc.opcodes import (
    OP_JUMP, OP_IFTRUE, OP_IFFALSE, OP_IFEQ, OP_IFNE,
    OP_IFLT, OP_IFLE, OP_IFGT, OP_IFGE,
    OP_IFSTRICTEQ, OP_IFSTRICTNE,
    OP_IFNLT, OP_IFNLE, OP_IFNGT, OP_IFNGE,
    OP_LOOKUPSWITCH,
    OP_RETURNVOID, OP_RETURNVALUE, OP_THROW,
)
from ..abc.types import ExceptionInfo


BlockKind = Literal[
    "normal", "loop_header", "switch", "try_start", "try_end", "catch_entry",
]


# Conditional branches: one s24 operand, two successors (fall-through, target).
_CONDITIONAL_BRANCHES = frozenset({
    OP_IFTRUE, OP_IFFALSE, OP_IFEQ, OP_IFNE,
    OP_IFLT, OP_IFLE, OP_IFGT, OP_IFGE,
    OP_IFSTRICTEQ, OP_IFSTRICTNE,
    OP_IFNLT, OP_IFNLE, OP_IFNGT, OP_IFNGE,
})

# Terminators with no successor.
_NO_SUCCESSOR_TERMINATORS = frozenset({
    OP_RETURNVOID, OP_RETURNVALUE, OP_THROW,
})


@dataclass(eq=False)
class BasicBlock:
    """A maximal straight-line instruction run.

    Equality/hashing is by identity (``eq=False``). Block order within a
    ``CFG`` is stable: blocks are numbered in ascending ``start_offset``
    order, which coincides with creation order.

    Attributes:
        index: Zero-based block id, unique within one CFG.
        start_offset: Bytecode offset of the first instruction.
        end_offset: Bytecode offset one past the last instruction
            (half-open, matches ``ExceptionInfo`` convention).
        instructions: Decoded instructions belonging to this block.
        successors: Outgoing edges in canonical order —
            ``[fall_through, branch_target]`` for conditional branches,
            ``[target]`` for unconditional jumps, default-then-cases for
            ``lookupswitch``, ``[next]`` for straight-line blocks.
        predecessors: Incoming edges, de-duplicated by block identity.
        exception_handlers: Every ``ExceptionInfo`` whose protected
            range covers this block (``from_offset <= start_offset`` and
            ``end_offset <= to_offset``).
        kind: One of ``normal``, ``loop_header``, ``switch``,
            ``try_start``, ``try_end``, ``catch_entry``. Only
            ``normal``, ``switch``, and ``catch_entry`` are set in
            Phase 1; the rest are reserved for later phases.
    """
    index: int
    start_offset: int
    end_offset: int
    instructions: list[Instruction] = field(default_factory=list)
    successors: list["BasicBlock"] = field(default_factory=list)
    predecessors: list["BasicBlock"] = field(default_factory=list)
    exception_handlers: list[ExceptionInfo] = field(default_factory=list)
    kind: BlockKind = "normal"

    def __repr__(self) -> str:
        return (f"BasicBlock(index={self.index}, "
                f"[{self.start_offset:#x}..{self.end_offset:#x}), "
                f"kind={self.kind!r})")


@dataclass
class CFG:
    """A method's control-flow graph.

    Attributes:
        entry: Entry block (always the block at offset 0).
        blocks: All blocks, sorted by ``start_offset``.
        exit_blocks: Blocks with no outgoing successors (``return*`` /
            ``throw``).
        blocks_by_offset: Lookup from ``start_offset`` to block, for
            tests and downstream phases that need random access.
    """
    entry: "BasicBlock"
    blocks: list["BasicBlock"]
    exit_blocks: list["BasicBlock"]
    blocks_by_offset: dict[int, "BasicBlock"]


# ── leader collection ──────────────────────────────────────────────────────


def _branch_targets(instr: Instruction) -> list[int]:
    """Return every control-flow target of an instruction, in canonical order.

    For conditional branches the order is ``[branch_target]`` (the
    fall-through is implied by the next instruction). For unconditional
    ``jump``, ``[target]``. For ``lookupswitch``, ``[default, case0, ...]``.
    All other instructions have no explicit targets.
    """
    op = instr.opcode
    if op == OP_JUMP or op in _CONDITIONAL_BRANCHES:
        # target = offset_after_instruction + s24_delta
        return [instr.offset + instr.size + instr.operands[0]]
    if op == OP_LOOKUPSWITCH:
        # operands = [default_s24, case_count, case0_s24, case1_s24, ...]
        # All offsets are relative to the opcode byte itself.
        base = instr.offset
        default_delta = instr.operands[0]
        case_count = instr.operands[1]
        out = [base + default_delta]
        for i in range(case_count + 1):
            out.append(base + instr.operands[2 + i])
        return out
    return []


def _collect_leaders(
    instructions: list[Instruction],
    exceptions: list[ExceptionInfo],
) -> set[int]:
    """Find every offset that starts a basic block."""
    if not instructions:
        return set()
    leaders: set[int] = {instructions[0].offset}
    valid_offsets = {i.offset for i in instructions}

    for idx, instr in enumerate(instructions):
        op = instr.opcode
        next_offset = instr.offset + instr.size

        targets = _branch_targets(instr)
        for t in targets:
            if t in valid_offsets:
                leaders.add(t)

        # Instruction after a branch/terminator begins a new block.
        is_branch = (
            op == OP_JUMP
            or op == OP_LOOKUPSWITCH
            or op in _CONDITIONAL_BRANCHES
            or op in _NO_SUCCESSOR_TERMINATORS
        )
        if is_branch and next_offset in valid_offsets:
            leaders.add(next_offset)

    for exc in exceptions:
        if exc.from_offset in valid_offsets:
            leaders.add(exc.from_offset)
        if exc.to_offset in valid_offsets:
            leaders.add(exc.to_offset)
        if exc.target in valid_offsets:
            leaders.add(exc.target)

    return leaders


# ── block assembly ─────────────────────────────────────────────────────────


def _slice_into_blocks(
    instructions: list[Instruction],
    leaders: set[int],
) -> list[BasicBlock]:
    """Cut the instruction list into blocks at leader boundaries."""
    offsets = [i.offset for i in instructions]
    leader_positions = sorted(
        i for i, off in enumerate(offsets) if off in leaders
    )

    blocks: list[BasicBlock] = []
    for idx, start_pos in enumerate(leader_positions):
        end_pos = (leader_positions[idx + 1]
                   if idx + 1 < len(leader_positions)
                   else len(instructions))
        block_instrs = instructions[start_pos:end_pos]
        last = block_instrs[-1]
        blocks.append(BasicBlock(
            index=idx,
            start_offset=block_instrs[0].offset,
            end_offset=last.offset + last.size,
            instructions=block_instrs,
        ))
    return blocks


def _wire_successors(
    blocks: list[BasicBlock],
    blocks_by_offset: dict[int, BasicBlock],
) -> None:
    """Populate ``successors`` from each block's terminator instruction."""
    for idx, bb in enumerate(blocks):
        last = bb.instructions[-1]
        op = last.opcode
        fall_through_offset = last.offset + last.size

        if op in _NO_SUCCESSOR_TERMINATORS:
            continue

        if op == OP_JUMP:
            targets = _branch_targets(last)
            succ = blocks_by_offset.get(targets[0])
            if succ is not None:
                bb.successors.append(succ)
            continue

        if op in _CONDITIONAL_BRANCHES:
            ft = blocks_by_offset.get(fall_through_offset)
            tgt = blocks_by_offset.get(_branch_targets(last)[0])
            if ft is not None:
                bb.successors.append(ft)
            if tgt is not None and tgt is not ft:
                bb.successors.append(tgt)
            continue

        if op == OP_LOOKUPSWITCH:
            bb.kind = "switch"
            seen: set[int] = set()
            for t in _branch_targets(last):
                succ = blocks_by_offset.get(t)
                if succ is None or succ.index in seen:
                    continue
                seen.add(succ.index)
                bb.successors.append(succ)
            continue

        # Straight-line block: fall through to the next block in layout.
        ft = blocks_by_offset.get(fall_through_offset)
        if ft is not None:
            bb.successors.append(ft)


def _fill_predecessors(blocks: list[BasicBlock]) -> None:
    """Invert successor edges to produce unique-by-identity predecessors."""
    for bb in blocks:
        seen: set[int] = set()
        for succ in bb.successors:
            if succ.index in seen:
                continue
            seen.add(succ.index)
            if bb not in succ.predecessors:
                succ.predecessors.append(bb)


# ── exception attachment ──────────────────────────────────────────────────


def _attach_exceptions(
    blocks: list[BasicBlock],
    blocks_by_offset: dict[int, BasicBlock],
    exceptions: list[ExceptionInfo],
) -> None:
    """Mark catch-entry blocks and populate ``exception_handlers`` lists.

    A handler protects a block iff the block is fully contained within
    ``[from_offset, to_offset)``. We use a sorted ``start_offset`` index
    plus ``bisect`` so the total work is O((B + H) log B) instead of
    O(B * H).
    """
    if not exceptions:
        return

    starts = [bb.start_offset for bb in blocks]  # ascending by construction

    for exc in exceptions:
        catch_bb = blocks_by_offset.get(exc.target)
        if catch_bb is not None:
            catch_bb.kind = "catch_entry"

        # Blocks with start_offset in [from, to) AND end_offset <= to.
        lo = bisect_right(starts, exc.from_offset - 1)
        hi = bisect_right(starts, exc.to_offset - 1)
        for i in range(lo, hi):
            bb = blocks[i]
            if bb.end_offset <= exc.to_offset:
                bb.exception_handlers.append(exc)


# ── public entry point ────────────────────────────────────────────────────


def build_cfg_from_bytecode(
    instructions: list[Instruction],
    exceptions: list[ExceptionInfo],
) -> CFG:
    """Build a control-flow graph from decoded bytecode.

    Args:
        instructions: Output of ``decode_instructions(body.code)``.
        exceptions: The method body's exception table.

    Returns:
        A ``CFG`` with blocks in ascending-offset order, successors
        wired, predecessors inverted, and exception handlers attached.

    Notes:
        For empty bytecode the returned CFG has no blocks; the ``entry``
        field is ``None`` in that case. Well-formed method bodies always
        contain at least a terminator, so callers that pass a real
        method body never encounter this.
    """
    if not instructions:
        return CFG(entry=None, blocks=[], exit_blocks=[], blocks_by_offset={})

    leaders = _collect_leaders(instructions, exceptions)
    blocks = _slice_into_blocks(instructions, leaders)
    blocks_by_offset = {bb.start_offset: bb for bb in blocks}

    _wire_successors(blocks, blocks_by_offset)
    _fill_predecessors(blocks)
    _attach_exceptions(blocks, blocks_by_offset, exceptions)

    exit_blocks = [bb for bb in blocks if not bb.successors]

    return CFG(
        entry=blocks[0],
        blocks=blocks,
        exit_blocks=exit_blocks,
        blocks_by_offset=blocks_by_offset,
    )
