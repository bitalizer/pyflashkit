"""Call-site constant-argument inference.

For each call site in the ABC, looks at the instructions immediately
preceding the call and records any literal values that line up with
the call's argument slots. The usual deobfuscation win is spotting
that ``SetFlags(x)`` is always invoked with one of a small set of
literal values — a clear signal that ``x`` is a flag enum.

Intentionally cheap: we don't do real reverse stack simulation, we
just walk backwards from the call and accept an operand only if it
comes from an immediate ``push*`` opcode within a short window. A
full per-block stack sim would be more accurate but an order of
magnitude heavier; the simple rule catches the common case.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from ..abc.disasm import decode_instructions
from ..abc.opcodes import (
    OP_CALLPROPERTY, OP_CALLPROPVOID, OP_CALLPROPLEX,
    OP_CONSTRUCTPROP,
    OP_PUSHBYTE, OP_PUSHSHORT, OP_PUSHINT, OP_PUSHUINT,
    OP_PUSHDOUBLE, OP_PUSHSTRING,
    OP_PUSHTRUE, OP_PUSHFALSE, OP_PUSHNULL, OP_PUSHUNDEFINED,
)
from ..abc.types import AbcFile
from ..errors import ABCParseError
from ..info.member_info import resolve_multiname, build_method_body_map
from ..info.class_info import ClassInfo


__all__ = [
    "ConstArgObservation",
    "ConstArgIndex",
]


log = logging.getLogger(__name__)


_CALL_OPS = frozenset({
    OP_CALLPROPERTY, OP_CALLPROPVOID, OP_CALLPROPLEX, OP_CONSTRUCTPROP,
})


@dataclass(frozen=True, slots=True)
class ConstArgObservation:
    """One call site annotated with whichever literal arguments were
    directly pushed before it.

    ``args`` has length ``arg_count`` (the call's declared argument
    count); each slot is either a ``str`` / ``int`` / ``float`` /
    ``bool`` / ``None`` literal, or the sentinel ``ConstArgIndex.UNKNOWN``
    when the value wasn't a trivial immediate push.
    """
    source_class: str
    source_member: str
    offset: int
    target: str
    arg_count: int
    args: tuple


@dataclass
class ConstArgIndex:
    """Collected call-site observations indexed by target name.

    Use ``observations_for(target_name)`` to inspect every call site of
    a method / constructor and the literal values passed to it.
    """

    # Sentinel placed in ``args`` when a slot's value isn't a trivial
    # immediate push. Compared by identity so users can distinguish it
    # from a genuine string literal like ``"UNKNOWN"``.
    UNKNOWN: object = object()

    by_target: dict[str, list[ConstArgObservation]] = field(
        default_factory=lambda: defaultdict(list))

    def observations_for(self, target: str) -> list[ConstArgObservation]:
        return list(self.by_target.get(target, ()))

    def distinct_arg_values(self, target: str, slot: int) -> set:
        """All known literal values passed in argument ``slot`` to
        ``target``, excluding unknowns. Useful for enum detection."""
        out: set = set()
        for obs in self.by_target.get(target, ()):
            if slot >= obs.arg_count:
                continue
            val = obs.args[slot]
            if val is self.UNKNOWN:
                continue
            try:
                out.add(val)
            except TypeError:
                # Unhashable value (shouldn't happen with literals, but
                # keep the index total).
                pass
        return out

    @classmethod
    def from_workspace(cls, workspace) -> ConstArgIndex:
        idx = cls()
        for abc in workspace.abc_blocks:
            idx._index_abc(abc, workspace.classes)
        return idx

    @classmethod
    def from_abc(cls, abc: AbcFile,
                 classes: list[ClassInfo] | None = None) -> ConstArgIndex:
        idx = cls()
        idx._index_abc(abc, classes or [])
        return idx

    # ── indexing ────────────────────────────────────────────────────

    def _index_abc(self, abc: AbcFile, classes: list[ClassInfo]) -> None:
        method_name_map, method_owner_map = _method_maps(abc, classes)
        for body in abc.method_bodies:
            caller_class = method_owner_map.get(body.method, "")
            caller_member = method_name_map.get(
                body.method, f"method_{body.method}")
            try:
                instrs = decode_instructions(body.code)
            except (ABCParseError, IndexError, ValueError) as exc:
                log.debug("const_args: decode failed method=%d: %s",
                          body.method, exc)
                continue
            self._scan_calls(abc, instrs, caller_class, caller_member)

    def _scan_calls(self, abc: AbcFile, instrs, caller_class: str,
                    caller_member: str) -> None:
        for i, instr in enumerate(instrs):
            if instr.opcode not in _CALL_OPS:
                continue
            if len(instr.operands) < 2:
                continue
            name_idx, arg_count = instr.operands[0], instr.operands[1]
            target = resolve_multiname(abc, name_idx)
            if target.startswith("multiname["):
                continue
            args = self._collect_args(abc, instrs, i, arg_count)
            self.by_target[target].append(ConstArgObservation(
                source_class=caller_class,
                source_member=caller_member,
                offset=instr.offset,
                target=target,
                arg_count=arg_count,
                args=args,
            ))

    def _collect_args(self, abc: AbcFile, instrs,
                      call_idx: int, arg_count: int) -> tuple:
        """Walk backwards from ``call_idx``, matching the N instructions
        that pushed the call's arguments. Each position becomes a
        literal value or :data:`UNKNOWN`.
        """
        args: list = [self.UNKNOWN] * arg_count
        # The immediately-preceding instructions push args in order.
        # The last arg is pushed last — so walk backwards, filling from
        # the right.
        slot = arg_count - 1
        j = call_idx - 1
        while slot >= 0 and j >= 0:
            instr = instrs[j]
            op = instr.opcode
            val: object = self.UNKNOWN
            if op == OP_PUSHBYTE:
                v = instr.operands[0]
                # pushbyte is sign-extended.
                val = v - 0x100 if v >= 0x80 else v
            elif op == OP_PUSHSHORT:
                val = instr.operands[0]
            elif op == OP_PUSHINT:
                val = _pool_lookup(abc, "int_pool", instr.operands[0],
                                   self.UNKNOWN)
            elif op == OP_PUSHUINT:
                val = _pool_lookup(abc, "uint_pool", instr.operands[0],
                                   self.UNKNOWN)
            elif op == OP_PUSHDOUBLE:
                val = _pool_lookup(abc, "double_pool", instr.operands[0],
                                   self.UNKNOWN)
            elif op == OP_PUSHSTRING:
                val = _pool_lookup(abc, "string_pool", instr.operands[0],
                                   self.UNKNOWN)
            elif op == OP_PUSHTRUE:
                val = True
            elif op == OP_PUSHFALSE:
                val = False
            elif op == OP_PUSHNULL:
                val = None
            elif op == OP_PUSHUNDEFINED:
                val = self.UNKNOWN
            else:
                # Not a trivial push — stop matching; everything to the
                # left of this slot stays UNKNOWN.
                break
            args[slot] = val
            slot -= 1
            j -= 1
        return tuple(args)


def _pool_lookup(abc: AbcFile, attr: str, idx: int, fallback):
    pool = getattr(abc, attr, None)
    if pool is None or not (0 < idx < len(pool)):
        return fallback
    return pool[idx]


def _method_maps(abc: AbcFile,
                 classes: list[ClassInfo]) -> tuple[dict[int, str], dict[int, str]]:
    """Build (method_index → ``Class.method`` display name,
    method_index → qualified class name) maps for every class method."""
    names: dict[int, str] = {}
    owners: dict[int, str] = {}
    body_map = build_method_body_map(abc)
    for ci in classes:
        for m in ci.all_methods:
            names[m.method_index] = f"{ci.qualified_name}.{m.name}"
            owners[m.method_index] = ci.qualified_name
        names[ci.constructor_index] = f"{ci.qualified_name}.<init>"
        owners[ci.constructor_index] = ci.qualified_name
        names[ci.static_init_index] = f"{ci.qualified_name}.<cinit>"
        owners[ci.static_init_index] = ci.qualified_name
    return names, owners
