"""
ABC bytecode parser and LEB128 codec.

Parses raw ABC (ActionScript Byte Code) binary data into an ``AbcFile``
structure. Also provides the LEB128 variable-length integer encoding
functions used throughout AVM2 bytecode.

Usage::

    from flashkit.abc.parser import parse_abc
    abc = parse_abc(raw_bytes)
    print(f"Classes: {len(abc.instances)}")
    print(f"Strings: {len(abc.string_pool)}")

The LEB128 functions (``read_u30``, ``write_u30``, etc.) are also public
and useful for manual bytecode manipulation.

Reference: Adobe AVM2 Overview, Chapter 4 (abc file format).
"""

from __future__ import annotations

import struct

from ..errors import ABCParseError
from .types import (
    AbcFile, NamespaceInfo, NsSetInfo, MultinameInfo,
    MethodInfo, MetadataInfo, TraitInfo, InstanceInfo,
    ClassInfo, ScriptInfo, ExceptionInfo, MethodBodyInfo,
)
from .constants import (
    CONSTANT_QName, CONSTANT_QNameA,
    CONSTANT_RTQName, CONSTANT_RTQNameA,
    CONSTANT_RTQNameL, CONSTANT_RTQNameLA,
    CONSTANT_Multiname, CONSTANT_MultinameA,
    CONSTANT_MultinameL, CONSTANT_MultinameLA,
    CONSTANT_TypeName,
    TRAIT_Slot, TRAIT_Const, TRAIT_Method, TRAIT_Getter, TRAIT_Setter,
    TRAIT_Class, TRAIT_Function,
    ATTR_Metadata,
    METHOD_HasOptional, METHOD_HasParamNames,
    INSTANCE_ProtectedNs,
)


# ── LEB128 encoding/decoding ───────────────────────────────────────────────

def read_u30(data: bytes, offset: int) -> tuple[int, int]:
    """Read a u30 (unsigned LEB128, max 30 bits).

    Returns:
        Tuple of (value, new_offset).
    """
    result = 0
    shift = 0
    for _ in range(5):
        b = data[offset]
        offset += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
    return result, offset


def read_s32(data: bytes, offset: int) -> tuple[int, int]:
    """Read an s32 (signed LEB128).

    Returns:
        Tuple of (value, new_offset).
    """
    result = 0
    shift = 0
    for _ in range(5):
        b = data[offset]
        offset += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if (b & 0x80) == 0:
            break
    # Sign extend
    if shift < 32 and (b & 0x40):
        result |= -(1 << shift)
    return result, offset


def write_u30(value: int) -> bytes:
    """Encode a u30 value as unsigned LEB128 bytes."""
    value &= 0x3FFFFFFF  # 30-bit unsigned
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        result.append(byte)
        if not value:
            break
    return bytes(result)


def write_s32(value: int) -> bytes:
    """Encode an s32 value as signed LEB128 bytes."""
    result = bytearray()
    more = True
    while more:
        byte = value & 0x7F
        value >>= 7
        if (value == 0 and (byte & 0x40) == 0) or (value == -1 and (byte & 0x40)):
            more = False
        else:
            byte |= 0x80
        result.append(byte)
    return bytes(result)


def s24(value: int) -> bytes:
    """Encode a signed 24-bit offset (little-endian).

    Used for branch instruction offsets in AVM2 bytecode.
    """
    if value < 0:
        value = value + (1 << 24)
    return bytes([value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF])


def read_u8(data: bytes, offset: int) -> tuple[int, int]:
    """Read a single unsigned byte."""
    return data[offset], offset + 1


def read_u16(data: bytes, offset: int) -> tuple[int, int]:
    """Read a 16-bit unsigned integer (little-endian)."""
    return struct.unpack_from("<H", data, offset)[0], offset + 2


def read_u32(data: bytes, offset: int) -> tuple[int, int]:
    """Read a 32-bit unsigned integer (little-endian)."""
    return struct.unpack_from("<I", data, offset)[0], offset + 4


def read_d64(data: bytes, offset: int) -> tuple[float, int]:
    """Read a 64-bit IEEE 754 double (little-endian)."""
    return struct.unpack_from("<d", data, offset)[0], offset + 8


# ── Internal helpers ────────────────────────────────────────────────────────

def _read_traits(data: bytes, offset: int) -> tuple[list[TraitInfo], int]:
    """Read a traits_info array.

    Returns:
        Tuple of (list of TraitInfo, new_offset).
    """
    count, offset = read_u30(data, offset)
    traits = []
    for _ in range(count):
        start = offset
        name, offset = read_u30(data, offset)
        kind_byte, offset = read_u8(data, offset)
        kind = kind_byte & 0x0F
        attr = (kind_byte >> 4) & 0x0F

        if kind in (TRAIT_Slot, TRAIT_Const):
            _slot_id, offset = read_u30(data, offset)
            _type_name, offset = read_u30(data, offset)
            vindex, offset = read_u30(data, offset)
            if vindex:
                _vkind, offset = read_u8(data, offset)
        elif kind in (TRAIT_Method, TRAIT_Getter, TRAIT_Setter):
            _disp_id, offset = read_u30(data, offset)
            _method_idx, offset = read_u30(data, offset)
        elif kind == TRAIT_Class:
            _slot_id, offset = read_u30(data, offset)
            _class_idx, offset = read_u30(data, offset)
        elif kind == TRAIT_Function:
            _slot_id, offset = read_u30(data, offset)
            _func_idx, offset = read_u30(data, offset)

        if attr & ATTR_Metadata:
            md_count, offset = read_u30(data, offset)
            for _ in range(md_count):
                _, offset = read_u30(data, offset)

        raw = data[start:offset]
        traits.append(TraitInfo(name=name, kind=kind, data=raw))

    return traits, offset


# ── Main parser ─────────────────────────────────────────────────────────────

def parse_abc(data: bytes) -> AbcFile:
    """Parse raw ABC bytecode into an AbcFile structure.

    This is the primary entry point for loading ABC data. The returned
    ``AbcFile`` can be inspected, modified, and serialized back to bytes
    with ``flashkit.abc.writer.serialize_abc()``.

    Args:
        data: Raw ABC bytecode bytes.

    Returns:
        Parsed AbcFile with all constant pools, methods, classes, and bodies.

    Raises:
        ABCParseError: If the data is not valid ABC bytecode.
    """
    if not data:
        raise ABCParseError("ABC data is empty")
    if len(data) < 4:
        raise ABCParseError(
            f"ABC data too short ({len(data)} bytes, minimum 4)")

    try:
        return _parse_abc_inner(data)
    except ABCParseError:
        raise
    except (IndexError, struct.error, ValueError, OverflowError) as e:
        raise ABCParseError(f"Corrupted ABC data: {e}") from e


def _parse_abc_inner(data: bytes) -> AbcFile:
    """Internal ABC parser (no error wrapping)."""
    abc = AbcFile()
    off = 0

    abc.minor_version, off = read_u16(data, off)
    abc.major_version, off = read_u16(data, off)

    # ── Constant pool ────────────────────────────────────────────────────

    # Integers
    count, off = read_u30(data, off)
    abc.int_pool = [0]
    abc._int_pool_raw = [b""]
    for _ in range(max(0, count - 1)):
        raw_start = off
        val, off = read_s32(data, off)
        abc.int_pool.append(val)
        abc._int_pool_raw.append(data[raw_start:off])

    # Unsigned integers
    count, off = read_u30(data, off)
    abc.uint_pool = [0]
    abc._uint_pool_raw = [b""]
    for _ in range(max(0, count - 1)):
        raw_start = off
        val, off = read_u30(data, off)
        abc.uint_pool.append(val)
        abc._uint_pool_raw.append(data[raw_start:off])

    # Doubles
    count, off = read_u30(data, off)
    abc.double_pool = [0.0]
    for _ in range(max(0, count - 1)):
        val, off = read_d64(data, off)
        abc.double_pool.append(val)

    # Strings
    count, off = read_u30(data, off)
    abc.string_pool = [""]
    for _ in range(max(0, count - 1)):
        slen, off = read_u30(data, off)
        s = data[off:off + slen].decode("utf-8", errors="replace")
        off += slen
        abc.string_pool.append(s)

    # Namespaces
    count, off = read_u30(data, off)
    abc.namespace_pool = [NamespaceInfo(0, 0)]
    for _ in range(max(0, count - 1)):
        kind, off = read_u8(data, off)
        name, off = read_u30(data, off)
        abc.namespace_pool.append(NamespaceInfo(kind, name))

    # Namespace sets
    count, off = read_u30(data, off)
    abc.ns_set_pool = [NsSetInfo([])]
    for _ in range(max(0, count - 1)):
        ns_count, off = read_u30(data, off)
        nss = []
        for __ in range(ns_count):
            ns, off = read_u30(data, off)
            nss.append(ns)
        abc.ns_set_pool.append(NsSetInfo(nss))

    # Multinames
    count, off = read_u30(data, off)
    abc.multiname_pool = [MultinameInfo(0)]
    for _ in range(max(0, count - 1)):
        kind, off = read_u8(data, off)
        mn = MultinameInfo(kind=kind)
        if kind in (CONSTANT_QName, CONSTANT_QNameA):
            mn.ns, off = read_u30(data, off)
            mn.name, off = read_u30(data, off)
        elif kind in (CONSTANT_RTQName, CONSTANT_RTQNameA):
            mn.name, off = read_u30(data, off)
        elif kind in (CONSTANT_RTQNameL, CONSTANT_RTQNameLA):
            pass
        elif kind in (CONSTANT_Multiname, CONSTANT_MultinameA):
            mn.name, off = read_u30(data, off)
            mn.ns_set, off = read_u30(data, off)
        elif kind in (CONSTANT_MultinameL, CONSTANT_MultinameLA):
            mn.ns_set, off = read_u30(data, off)
        elif kind == CONSTANT_TypeName:
            mn.ns, off = read_u30(data, off)  # base type multiname index
            param_count, off = read_u30(data, off)
            params = []
            for __ in range(param_count):
                p, off = read_u30(data, off)
                params.append(p)
            # Store params as serialized u30 bytes for round-trip fidelity
            param_bytes = bytearray()
            for p in params:
                param_bytes += write_u30(p)
            mn.data = bytes(param_bytes)
            mn.name = param_count  # stash param count in name field
        else:
            raise ABCParseError(
                f"Unknown multiname kind: 0x{kind:02X} at offset {off}")
        abc.multiname_pool.append(mn)

    # ── Methods ──────────────────────────────────────────────────────────

    count, off = read_u30(data, off)
    for _ in range(count):
        param_count, off = read_u30(data, off)
        return_type, off = read_u30(data, off)
        param_types = []
        for __ in range(param_count):
            pt, off = read_u30(data, off)
            param_types.append(pt)
        name, off = read_u30(data, off)
        flags, off = read_u8(data, off)

        mi = MethodInfo(
            param_count=param_count, return_type=return_type,
            param_types=param_types, name=name, flags=flags)

        if flags & METHOD_HasOptional:
            opt_count, off = read_u30(data, off)
            for __ in range(opt_count):
                val, off = read_u30(data, off)
                vkind, off = read_u8(data, off)
                mi.options.append((val, vkind))

        if flags & METHOD_HasParamNames:
            for __ in range(param_count):
                pn, off = read_u30(data, off)
                mi.param_names.append(pn)

        abc.methods.append(mi)

    # ── Metadata ─────────────────────────────────────────────────────────

    count, off = read_u30(data, off)
    for _ in range(count):
        name, off = read_u30(data, off)
        item_count, off = read_u30(data, off)
        items = []
        for __ in range(item_count):
            k, off = read_u30(data, off)
            v, off = read_u30(data, off)
            items.append((k, v))
        abc.metadata.append(MetadataInfo(name=name, items=items))

    # ── Instances + Classes ──────────────────────────────────────────────

    count, off = read_u30(data, off)
    for _ in range(count):
        inst = InstanceInfo(name=0, super_name=0, flags=0)
        inst.name, off = read_u30(data, off)
        inst.super_name, off = read_u30(data, off)
        inst.flags, off = read_u8(data, off)

        if inst.flags & INSTANCE_ProtectedNs:
            inst.protectedNs, off = read_u30(data, off)

        iface_count, off = read_u30(data, off)
        for __ in range(iface_count):
            ifc, off = read_u30(data, off)
            inst.interfaces.append(ifc)

        inst.iinit, off = read_u30(data, off)
        inst.traits, off = _read_traits(data, off)
        abc.instances.append(inst)

    for _ in range(count):
        ci = ClassInfo(cinit=0)
        ci.cinit, off = read_u30(data, off)
        ci.traits, off = _read_traits(data, off)
        abc.classes.append(ci)

    # ── Scripts ──────────────────────────────────────────────────────────

    count, off = read_u30(data, off)
    for _ in range(count):
        si = ScriptInfo(init=0)
        si.init, off = read_u30(data, off)
        si.traits, off = _read_traits(data, off)
        abc.scripts.append(si)

    # ── Method bodies ────────────────────────────────────────────────────

    count, off = read_u30(data, off)
    for _ in range(count):
        mb = MethodBodyInfo(
            method=0, max_stack=0, local_count=0,
            init_scope_depth=0, max_scope_depth=0, code=b"")
        mb.method, off = read_u30(data, off)
        mb.max_stack, off = read_u30(data, off)
        mb.local_count, off = read_u30(data, off)
        mb.init_scope_depth, off = read_u30(data, off)
        mb.max_scope_depth, off = read_u30(data, off)
        code_len, off = read_u30(data, off)
        mb.code = data[off:off + code_len]
        off += code_len

        # Exceptions
        exc_count, off = read_u30(data, off)
        for __ in range(exc_count):
            ei = ExceptionInfo(0, 0, 0, 0, 0)
            ei.from_offset, off = read_u30(data, off)
            ei.to_offset, off = read_u30(data, off)
            ei.target, off = read_u30(data, off)
            ei.exc_type, off = read_u30(data, off)
            ei.var_name, off = read_u30(data, off)
            mb.exceptions.append(ei)

        mb.traits, off = _read_traits(data, off)
        abc.method_bodies.append(mb)

    return abc
