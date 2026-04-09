"""
ABC bytecode serializer.

Serializes an ``AbcFile`` structure back to raw ABC binary data.
The output is byte-for-byte identical to the original input when
no modifications have been made (round-trip fidelity).

Usage::

    from flashkit.abc.parser import parse_abc
    from flashkit.abc.writer import serialize_abc

    abc = parse_abc(raw_bytes)
    # ... modify abc ...
    output = serialize_abc(abc)

Reference: Adobe AVM2 Overview, Chapter 4 (abc file format).
"""

from __future__ import annotations

import struct

from ..errors import SerializeError
from .types import AbcFile, TraitInfo
from .parser import write_u30, write_s32
from .constants import (
    CONSTANT_QName, CONSTANT_QNameA,
    CONSTANT_RTQName, CONSTANT_RTQNameA,
    CONSTANT_RTQNameL, CONSTANT_RTQNameLA,
    CONSTANT_Multiname, CONSTANT_MultinameA,
    CONSTANT_MultinameL, CONSTANT_MultinameLA,
    CONSTANT_TypeName,
    METHOD_HasOptional, METHOD_HasParamNames,
    INSTANCE_ProtectedNs,
)


def _write_traits(traits: list[TraitInfo]) -> bytes:
    """Serialize a trait list using the raw binary data stored during parse."""
    out = write_u30(len(traits))
    for t in traits:
        out += t.data
    return out


def serialize_abc(abc: AbcFile) -> bytes:
    """Serialize an AbcFile back to raw ABC bytecode.

    Args:
        abc: The AbcFile to serialize.

    Returns:
        Raw ABC bytecode bytes ready to embed in a DoABC/DoABC2 tag.

    Raises:
        SerializeError: If the AbcFile structure is invalid.
    """
    try:
        return _serialize_abc_inner(abc)
    except SerializeError:
        raise
    except (IndexError, struct.error, ValueError, TypeError,
            AttributeError) as e:
        raise SerializeError(f"Failed to serialize ABC: {e}") from e


def _serialize_abc_inner(abc: AbcFile) -> bytes:
    """Internal serializer (no error wrapping)."""
    out = bytearray()
    out += struct.pack("<HH", abc.minor_version, abc.major_version)

    # ── Constant pool ────────────────────────────────────────────────────

    # Integers (count 0 means empty pool — only the implicit default entry)
    # Use raw LEB128 bytes when available for round-trip fidelity, since
    # the AVM2 spec allows non-minimal s32 encodings.
    int_extra = abc.int_pool[1:]
    int_raw = abc._int_pool_raw[1:] if len(abc._int_pool_raw) > 1 else []
    out += write_u30(len(int_extra) + 1 if int_extra else 0)
    for i, v in enumerate(int_extra):
        if i < len(int_raw) and int_raw[i]:
            out += int_raw[i]
        else:
            out += write_s32(v)

    # Unsigned integers
    # Use raw bytes for round-trip fidelity (AVM2 uint values can exceed
    # 30 bits despite the spec calling the encoding "u30").
    uint_extra = abc.uint_pool[1:]
    uint_raw = abc._uint_pool_raw[1:] if len(abc._uint_pool_raw) > 1 else []
    out += write_u30(len(uint_extra) + 1 if uint_extra else 0)
    for i, v in enumerate(uint_extra):
        if i < len(uint_raw) and uint_raw[i]:
            out += uint_raw[i]
        else:
            out += write_u30(v)

    # Doubles
    dbl_extra = abc.double_pool[1:]
    out += write_u30(len(dbl_extra) + 1 if dbl_extra else 0)
    for v in dbl_extra:
        out += struct.pack("<d", v)

    # Strings
    str_extra = abc.string_pool[1:]
    out += write_u30(len(str_extra) + 1 if str_extra else 0)
    for s in str_extra:
        encoded = s.encode("utf-8")
        out += write_u30(len(encoded))
        out += encoded

    # Namespaces
    ns_extra = abc.namespace_pool[1:]
    out += write_u30(len(ns_extra) + 1 if ns_extra else 0)
    for ns in ns_extra:
        out += bytes([ns.kind])
        out += write_u30(ns.name)

    # Namespace sets
    nss_extra = abc.ns_set_pool[1:]
    out += write_u30(len(nss_extra) + 1 if nss_extra else 0)
    for nss in nss_extra:
        out += write_u30(len(nss.namespaces))
        for ns in nss.namespaces:
            out += write_u30(ns)

    # Multinames
    mn_extra = abc.multiname_pool[1:]
    out += write_u30(len(mn_extra) + 1 if mn_extra else 0)
    for mn in mn_extra:
        out += bytes([mn.kind])
        if mn.kind in (CONSTANT_QName, CONSTANT_QNameA):
            out += write_u30(mn.ns)
            out += write_u30(mn.name)
        elif mn.kind in (CONSTANT_RTQName, CONSTANT_RTQNameA):
            out += write_u30(mn.name)
        elif mn.kind in (CONSTANT_RTQNameL, CONSTANT_RTQNameLA):
            pass
        elif mn.kind in (CONSTANT_Multiname, CONSTANT_MultinameA):
            out += write_u30(mn.name)
            out += write_u30(mn.ns_set)
        elif mn.kind in (CONSTANT_MultinameL, CONSTANT_MultinameLA):
            out += write_u30(mn.ns_set)
        elif mn.kind == CONSTANT_TypeName:
            out += write_u30(mn.ns)    # base type multiname index
            out += write_u30(mn.name)  # parameter count
            out += mn.data             # pre-serialized parameter u30s
        else:
            raise SerializeError(
                f"Unknown multiname kind 0x{mn.kind:02X}")

    # ── Methods ──────────────────────────────────────────────────────────

    out += write_u30(len(abc.methods))
    for mi in abc.methods:
        out += write_u30(mi.param_count)
        out += write_u30(mi.return_type)
        for pt in mi.param_types:
            out += write_u30(pt)
        out += write_u30(mi.name)
        out += bytes([mi.flags])

        if mi.flags & METHOD_HasOptional:
            out += write_u30(len(mi.options))
            for val, vkind in mi.options:
                out += write_u30(val)
                out += bytes([vkind])

        if mi.flags & METHOD_HasParamNames:
            for pn in mi.param_names:
                out += write_u30(pn)

    # ── Metadata ─────────────────────────────────────────────────────────

    out += write_u30(len(abc.metadata))
    for md in abc.metadata:
        out += write_u30(md.name)
        out += write_u30(len(md.items))
        for k, v in md.items:
            out += write_u30(k)
            out += write_u30(v)

    # ── Instances + Classes ──────────────────────────────────────────────

    out += write_u30(len(abc.instances))
    for inst in abc.instances:
        out += write_u30(inst.name)
        out += write_u30(inst.super_name)
        out += bytes([inst.flags])
        if inst.flags & INSTANCE_ProtectedNs:
            out += write_u30(inst.protectedNs)
        out += write_u30(len(inst.interfaces))
        for ifc in inst.interfaces:
            out += write_u30(ifc)
        out += write_u30(inst.iinit)
        out += _write_traits(inst.traits)

    for ci in abc.classes:
        out += write_u30(ci.cinit)
        out += _write_traits(ci.traits)

    # ── Scripts ──────────────────────────────────────────────────────────

    out += write_u30(len(abc.scripts))
    for si in abc.scripts:
        out += write_u30(si.init)
        out += _write_traits(si.traits)

    # ── Method bodies ────────────────────────────────────────────────────

    out += write_u30(len(abc.method_bodies))
    for mb in abc.method_bodies:
        out += write_u30(mb.method)
        out += write_u30(mb.max_stack)
        out += write_u30(mb.local_count)
        out += write_u30(mb.init_scope_depth)
        out += write_u30(mb.max_scope_depth)
        out += write_u30(len(mb.code))
        out += mb.code
        out += write_u30(len(mb.exceptions))
        for ei in mb.exceptions:
            out += write_u30(ei.from_offset)
            out += write_u30(ei.to_offset)
            out += write_u30(ei.target)
            out += write_u30(ei.exc_type)
            out += write_u30(ei.var_name)
        out += _write_traits(mb.traits)

    return bytes(out)
