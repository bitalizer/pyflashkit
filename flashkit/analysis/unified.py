"""
Unified single-pass index builder.

Decodes every method body exactly once and populates StringIndex,
ReferenceIndex, and FieldAccessIndex simultaneously. This avoids the
3x redundant ``decode_instructions`` overhead of building each index
independently.

Usage::

    from flashkit.analysis.unified import build_all_indexes

    string_idx, ref_idx, field_idx = build_all_indexes(workspace)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..workspace.workspace import Workspace

from ..abc.types import AbcFile
from ..abc.disasm import scan_relevant_opcodes
from ..abc.constants import (
    OP_pushstring, OP_debugfile,
    OP_constructprop, OP_callproperty, OP_callpropvoid,
    OP_getlex, OP_coerce, OP_newclass,
    OP_getproperty, OP_setproperty, OP_initproperty,
)
from ..info.member_info import resolve_multiname
from ..info.class_info import ClassInfo

from .strings import StringIndex, StringUsage
from .references import ReferenceIndex, Reference
from .field_access import FieldAccessIndex, FieldAccess


def _build_method_maps(
    abc: AbcFile, classes: list[ClassInfo]
) -> tuple[dict[int, str], dict[int, str]]:
    """Build method_index → owner class and method_index → method name maps."""
    owner: dict[int, str] = {}
    name_map: dict[int, str] = {}
    for ci in classes:
        owner[ci.constructor_index] = ci.qualified_name
        owner[ci.static_init_index] = ci.qualified_name
        name_map[ci.constructor_index] = "<init>"
        name_map[ci.static_init_index] = "<cinit>"
        for m in ci.all_methods:
            owner[m.method_index] = ci.qualified_name
            name_map[m.method_index] = m.name
    return owner, name_map


# Opcodes relevant to ReferenceIndex
_REF_OPCODES = frozenset({
    OP_constructprop, OP_callproperty, OP_callpropvoid,
    OP_getlex, OP_coerce, OP_pushstring,
})

# Opcode → ref_kind mapping
_REF_KIND = {
    OP_constructprop: "instantiation",
    OP_callproperty: "call",
    OP_callpropvoid: "call",
    OP_getlex: "class_ref",
    OP_coerce: "coerce",
}

# Opcodes relevant to FieldAccessIndex
_FIELD_OPS = {
    OP_getproperty: "read",
    OP_setproperty: "write",
    OP_initproperty: "init",
}

# Opcodes relevant to StringIndex
_STRING_OPS = frozenset({OP_pushstring, OP_debugfile})

# All opcodes the unified scanner needs to capture
_ALL_RELEVANT_OPS = frozenset(
    _STRING_OPS | frozenset(_FIELD_OPS) | frozenset(_REF_KIND) | {OP_pushstring}
)


def build_all_indexes(
    workspace: Workspace,
) -> tuple[StringIndex, ReferenceIndex, FieldAccessIndex]:
    """Build all three bytecode indexes in a single pass.

    Decodes each method body once and populates StringIndex,
    ReferenceIndex, and FieldAccessIndex simultaneously.

    Args:
        workspace: A Workspace instance.

    Returns:
        Tuple of (StringIndex, ReferenceIndex, FieldAccessIndex).
    """
    ws = workspace

    str_idx = StringIndex()
    ref_idx = ReferenceIndex()
    field_idx = FieldAccessIndex()

    # Collect pool strings for StringIndex
    for abc in ws.abc_blocks:
        for s in abc.string_pool:
            if s:
                str_idx.pool_strings.add(s)

    # Index class traits for ReferenceIndex (no bytecode decoding needed)
    for ci in ws.classes:
        ref_idx._index_class_traits(ci)

    # Single-pass bytecode scan using the lightweight scanner
    for abc in ws.abc_blocks:
        owner_map, name_map = _build_method_maps(abc, ws.classes)
        string_pool = abc.string_pool
        string_pool_len = len(string_pool)

        for body in abc.method_bodies:
            owner_class = owner_map.get(body.method, "")
            method_name = name_map.get(
                body.method, f"method_{body.method}")

            try:
                hits = scan_relevant_opcodes(body.code, _ALL_RELEVANT_OPS)
            except Exception:
                continue

            for offset, op, operand in hits:
                # StringIndex: OP_pushstring, OP_debugfile
                if op in _STRING_OPS:
                    if 0 < operand < string_pool_len:
                        str_idx._add(StringUsage(
                            string=string_pool[operand],
                            class_name=owner_class,
                            method_name=method_name,
                            method_index=body.method,
                            offset=offset,
                            opcode=op,
                        ))

                # FieldAccessIndex: get/set/initproperty
                if op in _FIELD_OPS:
                    target = resolve_multiname(abc, operand)
                    if target != "*" and not target.startswith("multiname["):
                        field_idx._add(FieldAccess(
                            class_name=owner_class,
                            method_name=method_name,
                            method_index=body.method,
                            field_name=target,
                            access_type=_FIELD_OPS[op],
                            offset=offset,
                        ))

                # ReferenceIndex: various opcodes
                if op in _REF_KIND:
                    target = resolve_multiname(abc, operand)
                    if target != "*" and not target.startswith("multiname["):
                        ref_idx._add(Reference(
                            source_class=owner_class,
                            source_member=method_name,
                            target=target,
                            ref_kind=_REF_KIND[op],
                            method_index=body.method,
                            offset=offset,
                        ))
                elif op == OP_pushstring:
                    if 0 < operand < string_pool_len:
                        ref_idx._add(Reference(
                            source_class=owner_class,
                            source_member=method_name,
                            target=string_pool[operand],
                            ref_kind="string_use",
                            method_index=body.method,
                            offset=offset,
                        ))

    return str_idx, ref_idx, field_idx
