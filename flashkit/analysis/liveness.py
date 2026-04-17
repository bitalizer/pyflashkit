"""Per-method register liveness.

For each method body, records which local registers are read and which
are written, along with the first/last offset of each kind of access.
Useful for deobfuscation passes that rename synthetic ``_loc3_`` names
based on how the register is actually used — e.g. a register that is
written once and read many times is likely a cached property.

This is a pure pass over the decoded instruction stream, not a
full-fledged dataflow liveness analysis (which would track live-in /
live-out sets per basic block). The simpler "used at all" view is
enough to drive 90% of practical rename heuristics and stays in O(N)
of instructions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..abc.disasm import decode_instructions
from ..abc.opcodes import (
    OP_GETLOCAL, OP_SETLOCAL,
    OP_GETLOCAL_0, OP_GETLOCAL_1, OP_GETLOCAL_2, OP_GETLOCAL_3,
    OP_SETLOCAL_0, OP_SETLOCAL_1, OP_SETLOCAL_2, OP_SETLOCAL_3,
    OP_KILL, OP_INCLOCAL, OP_DECLOCAL,
    OP_INCLOCAL_I, OP_DECLOCAL_I,
    OP_HASNEXT2,
)
from ..abc.types import AbcFile, MethodBodyInfo
from ..errors import ABCParseError


__all__ = ["LocalLiveness", "method_liveness"]


log = logging.getLogger(__name__)


_GET_SHORT = {
    OP_GETLOCAL_0: 0, OP_GETLOCAL_1: 1,
    OP_GETLOCAL_2: 2, OP_GETLOCAL_3: 3,
}
_SET_SHORT = {
    OP_SETLOCAL_0: 0, OP_SETLOCAL_1: 1,
    OP_SETLOCAL_2: 2, OP_SETLOCAL_3: 3,
}
# inclocal / declocal both read AND write; kill writes.
_RW_ONE = frozenset({OP_INCLOCAL, OP_DECLOCAL, OP_INCLOCAL_I, OP_DECLOCAL_I})


@dataclass(frozen=True, slots=True)
class LocalLiveness:
    """Liveness summary for one method body.

    Attributes:
        method_index: The method whose body this describes.
        local_count: ``local_count`` declared on the method body —
            this is the upper bound on valid register indices.
        reads: Sorted tuple of register indices that are ever read.
        writes: Sorted tuple of register indices that are ever written.
        read_counts: Register → number of read sites. A register with
            count 1 that's written once is a likely rename candidate.
        write_counts: Register → number of write sites.
        first_write: Register → earliest bytecode offset at which it's
            written, or -1 if never written.
        last_read: Register → latest bytecode offset at which it's
            read, or -1 if never read.
    """
    method_index: int
    local_count: int
    reads: tuple[int, ...] = ()
    writes: tuple[int, ...] = ()
    read_counts: dict[int, int] = field(default_factory=dict)
    write_counts: dict[int, int] = field(default_factory=dict)
    first_write: dict[int, int] = field(default_factory=dict)
    last_read: dict[int, int] = field(default_factory=dict)

    def is_unused(self, reg: int) -> bool:
        """A register is unused if it's never read *and* never written."""
        return reg not in self.read_counts and reg not in self.write_counts

    def is_write_only(self, reg: int) -> bool:
        """Likely dead store — written but never read."""
        return (reg in self.write_counts
                and reg not in self.read_counts)

    def is_read_only(self, reg: int) -> bool:
        """Read but never assigned. Usually a parameter register."""
        return (reg in self.read_counts
                and reg not in self.write_counts)


def method_liveness(abc: AbcFile,
                    body: MethodBodyInfo) -> LocalLiveness | None:
    """Scan one method body and return its liveness summary.

    Returns ``None`` if the body can't be decoded. Uses ``scan`` over
    the decoded instruction stream; pool lookups happen only on the
    opcodes that carry a register operand, so a noisy method with a
    thousand unrelated instructions still runs fast.
    """
    try:
        instrs = decode_instructions(body.code)
    except (ABCParseError, IndexError, ValueError) as exc:
        log.debug("liveness: decode failed for method=%d: %s",
                  body.method, exc)
        return None

    read_counts: dict[int, int] = {}
    write_counts: dict[int, int] = {}
    first_write: dict[int, int] = {}
    last_read: dict[int, int] = {}

    def mark_read(reg: int, off: int) -> None:
        read_counts[reg] = read_counts.get(reg, 0) + 1
        last_read[reg] = off

    def mark_write(reg: int, off: int) -> None:
        write_counts[reg] = write_counts.get(reg, 0) + 1
        if reg not in first_write:
            first_write[reg] = off

    for instr in instrs:
        op = instr.opcode
        off = instr.offset

        if op in _GET_SHORT:
            mark_read(_GET_SHORT[op], off)
        elif op in _SET_SHORT:
            mark_write(_SET_SHORT[op], off)
        elif op == OP_GETLOCAL:
            mark_read(instr.operands[0], off)
        elif op == OP_SETLOCAL:
            mark_write(instr.operands[0], off)
        elif op == OP_KILL:
            mark_write(instr.operands[0], off)
        elif op in _RW_ONE:
            # inclocal / declocal: single register that is read and written.
            reg = instr.operands[0]
            mark_read(reg, off)
            mark_write(reg, off)
        elif op == OP_HASNEXT2:
            # hasnext2 takes two u30 register operands and updates both.
            if len(instr.operands) >= 2:
                for reg in (instr.operands[0], instr.operands[1]):
                    mark_read(reg, off)
                    mark_write(reg, off)

    return LocalLiveness(
        method_index=body.method,
        local_count=body.local_count,
        reads=tuple(sorted(read_counts)),
        writes=tuple(sorted(write_counts)),
        read_counts=read_counts,
        write_counts=write_counts,
        first_write=first_write,
        last_read=last_read,
    )
