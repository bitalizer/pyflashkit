"""Decompiler utility helpers used by the class-level decompiler and the
AS3 printer.

Scope is narrow: formatting + namespace inspection + bytecode operand
skipping. No stateful decompilation logic lives here. A larger
string-manipulation toolkit that fed the pre-CFG pipeline used to live
in this module but has been removed — the CFG-based decompiler
(``method.py`` / ``structure.py`` / ``ast/printer.py``) operates on
typed AST nodes, not strings, and those helpers had no remaining
callers.
"""

from __future__ import annotations

import struct

from ..abc.parser import read_u30
from ..abc.constants import (
    CONSTANT_PRIVATE_NS,
    CONSTANT_PROTECTED_NAMESPACE,
    CONSTANT_STATIC_PROTECTED_NS,
    CONSTANT_PACKAGE_INTERNAL_NS,
    CONSTANT_PACKAGE_NAMESPACE,
    CONSTANT_QNAME, CONSTANT_QNAME_A,
    CONSTANT_MULTINAME, CONSTANT_MULTINAME_A,
    CONSTANT_MULTINAME_L, CONSTANT_MULTINAME_LA,
    CONSTANT_TYPENAME,
)
from ..abc.opcodes import (
    OP_PUSHBYTE, OP_PUSHSHORT, OP_PUSHSTRING, OP_PUSHINT, OP_PUSHUINT,
    OP_PUSHDOUBLE, OP_PUSHNAMESPACE,
    OP_GETSUPER, OP_SETSUPER, OP_DXNS, OP_KILL,
    OP_NEWFUNCTION, OP_NEWCLASS, OP_NEWCATCH,
    OP_FINDPROPSTRICT, OP_FINDPROPERTY, OP_FINDDEF, OP_GETLEX,
    OP_SETPROPERTY, OP_GETLOCAL, OP_SETLOCAL,
    OP_GETSCOPEOBJECT, OP_GETPROPERTY, OP_INITPROPERTY,
    OP_DELETEPROPERTY, OP_GETSLOT, OP_SETSLOT,
    OP_GETGLOBALSLOT, OP_SETGLOBALSLOT,
    OP_COERCE, OP_ASTYPE, OP_ISTYPE,
    OP_INCLOCAL, OP_DECLOCAL, OP_INCLOCAL_I, OP_DECLOCAL_I,
    OP_GETDESCENDANTS,
    OP_DEBUGLINE, OP_DEBUGFILE, OP_DEBUG,
    OP_CALL, OP_CONSTRUCT, OP_APPLYTYPE,
    OP_NEWOBJECT, OP_NEWARRAY, OP_CONSTRUCTSUPER,
    OP_CALLMETHOD, OP_CALLSTATIC, OP_CALLSUPER,
    OP_CALLPROPERTY, OP_CONSTRUCTPROP, OP_CALLPROPLEX,
    OP_CALLSUPERVOID, OP_CALLPROPVOID,
    OP_HASNEXT2,
)


# ── Indentation ─────────────────────────────────────────────────────────────

INDENT_UNIT = "    "
"""Indent unit used throughout AS3 output. 4 spaces by default."""


# ── Numeric / string formatting ─────────────────────────────────────────────


def fmt_hex_const(v: int) -> str:
    """Format ``v`` as ``0xNNNN`` for constant declarations (min 4 digits)."""
    h = f"{v:X}"
    if len(h) < 4:
        h = h.zfill(4)
    return f"0x{h}"


def escape_str(s: str) -> str:
    """Escape special characters for an AS3 string literal.

    Handles backslash, double-quote, newline, carriage return, tab, NUL,
    form-feed, Unicode line separators (U+2028/2029), and any other
    control character (< 0x20 or 0x7F).
    """
    out: list[str] = []
    for ch in s:
        cp = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif cp == 0:
            out.append("\\0")
        elif ch == "\f":
            out.append("\\f")
        elif cp == 0x2028:
            out.append("\\u2028")
        elif cp == 0x2029:
            out.append("\\u2029")
        elif cp < 0x20 or cp == 0x7F:
            out.append(f"\\x{cp:02X}")
        else:
            out.append(ch)
    return "".join(out)


# ── Namespace / access modifier helpers ─────────────────────────────────────


def access_modifier(ns_kind: int) -> str:
    """Map an AVM2 namespace kind byte to its AS3 access modifier keyword."""
    if ns_kind == CONSTANT_PRIVATE_NS:
        return "private"
    if ns_kind in (CONSTANT_PROTECTED_NAMESPACE, CONSTANT_STATIC_PROTECTED_NS):
        return "protected"
    if ns_kind == CONSTANT_PACKAGE_INTERNAL_NS:
        return "internal"
    return "public"


# ── Bytecode operand skipping ───────────────────────────────────────────────
# Used by analysis passes that need to iterate instructions without fully
# decoding them. If the bytecode is malformed the return equals ``len(code)``
# (graceful degradation — caller's loop terminates).

_OPS_ONE_U30 = frozenset({
    OP_PUSHSHORT, OP_PUSHSTRING, OP_PUSHINT, OP_PUSHUINT,
    OP_PUSHDOUBLE, OP_PUSHNAMESPACE,
    OP_GETSUPER, OP_SETSUPER, OP_DXNS, OP_KILL,
    OP_NEWFUNCTION, OP_NEWCLASS, OP_NEWCATCH,
    OP_FINDPROPSTRICT, OP_FINDPROPERTY, OP_FINDDEF, OP_GETLEX,
    OP_SETPROPERTY, OP_GETLOCAL, OP_SETLOCAL,
    OP_GETSCOPEOBJECT, OP_GETPROPERTY, OP_INITPROPERTY,
    OP_DELETEPROPERTY, OP_GETSLOT, OP_SETSLOT,
    OP_GETGLOBALSLOT, OP_SETGLOBALSLOT,
    OP_COERCE, OP_ASTYPE, OP_ISTYPE,
    OP_INCLOCAL, OP_DECLOCAL, OP_INCLOCAL_I, OP_DECLOCAL_I,
    OP_GETDESCENDANTS,
    OP_DEBUGLINE, OP_DEBUGFILE,
    OP_CALL, OP_CONSTRUCT, OP_APPLYTYPE,
    OP_NEWOBJECT, OP_NEWARRAY, OP_CONSTRUCTSUPER,
})

_OPS_TWO_U30 = frozenset({
    OP_CALLMETHOD, OP_CALLSTATIC, OP_CALLSUPER,
    OP_CALLPROPERTY, OP_CONSTRUCTPROP, OP_CALLPROPLEX,
    OP_CALLSUPERVOID, OP_CALLPROPVOID,
    OP_HASNEXT2,
})


def skip_operands(op: int, code: bytes, p: int) -> int:
    """Advance past an instruction's operands, returning the new offset.

    ``p`` is the offset *after* the opcode byte. Returns ``len(code)`` on
    malformed bytecode so the caller's iteration loop terminates safely.
    """
    try:
        if op == OP_PUSHBYTE:
            return p + 1
        if op in _OPS_ONE_U30:
            _, p = read_u30(code, p)
            return p
        if op in _OPS_TWO_U30:
            _, p = read_u30(code, p)
            _, p = read_u30(code, p)
            return p
        if op == OP_DEBUG:
            p += 1                    # debug_type u8
            _, p = read_u30(code, p)  # name string idx
            p += 1                    # register u8
            _, p = read_u30(code, p)  # extra u30
            return p
        return p
    except (IndexError, struct.error, ValueError):
        return len(code)


# ── Wildcard-import harvesting ──────────────────────────────────────────────
#
# These helpers feed ``class_.py``'s import-collection pass, which scans for
# multinames with an NS-set and promotes any package-kind namespace to a
# wildcard ``import pkg.*``.
#
# The name-case guard is a known heuristic — "identifier starts with an
# uppercase letter, probably a class" — that fails on obfuscated SWFs.
# Preserved for now because removing it changes visible import output;
# schedule for replacement with a structural check (trait kind) in a
# follow-up.


def check_typename_param(abc, mn_idx: int, result: list) -> None:
    """Walk a TypeName parameter and add any referenced package to
    ``result``. Handles nested TypeName and QName/Multiname params."""
    if mn_idx >= len(abc.multinames):
        return
    kind, data = abc.multinames[mn_idx]
    if kind == CONSTANT_TYPENAME and data:
        _qn, params = data
        for px in params:
            check_typename_param(abc, px, result)
        return
    if kind in (CONSTANT_QNAME, CONSTANT_QNAME_A) and data and len(data) >= 2:
        name_idx = data[1]
        name = abc.strings[name_idx] if name_idx < len(abc.strings) else ""
        if name and name[0].isupper():
            ns_idx = data[0]
            if ns_idx < len(abc.namespaces):
                if abc.ns_kind(ns_idx) == CONSTANT_PACKAGE_NAMESPACE:
                    ns = abc.ns_name(ns_idx)
                    if ns and ns not in result:
                        result.append(ns)
        return
    check_mn_ns_set_typed(abc, mn_idx, result)


def check_mn_ns_set_typed(abc, mn_idx: int, result: list) -> None:
    """Append each package-namespace referenced by ``mn_idx`` to
    ``result``, skipping multinames whose name isn't class-shaped.

    Guards against polluting the wildcard list with property and method
    access multinames whose NS-sets aren't actually type references.
    """
    if mn_idx >= len(abc.multinames):
        return
    kind, data = abc.multinames[mn_idx]
    if kind == CONSTANT_TYPENAME and data:
        _qn, params = data
        for px in params:
            check_typename_param(abc, px, result)
        return
    if kind in (CONSTANT_MULTINAME, CONSTANT_MULTINAME_A) and data and len(data) >= 2:
        name_idx = data[0]
        name = abc.strings[name_idx] if name_idx < len(abc.strings) else ""
        if not name or not name[0].isupper():
            return  # skip non-class names
        ns_set_idx = data[1]
    elif kind in (CONSTANT_MULTINAME_L, CONSTANT_MULTINAME_LA) and data:
        # Late-bound: can't check the name, include for safety.
        ns_set_idx = data[0]
    else:
        return
    if ns_set_idx and ns_set_idx < len(abc.ns_sets):
        for ns_idx in abc.ns_sets[ns_set_idx]:
            if abc.ns_kind(ns_idx) == CONSTANT_PACKAGE_NAMESPACE:
                ns = abc.ns_name(ns_idx)
                if ns and ns not in result:
                    result.append(ns)


def build_class_name_set(abc) -> set[int]:
    """Return the set of string-pool indices naming *actual class
    traits* across an ABC.

    The structural replacement for the ``name[0].isupper()`` heuristic.
    Walk every trait on every instance / class / script, and collect
    the name_idx of each trait whose kind is ``TRAIT_CLASS``. A
    downstream caller can then check ``string_name_idx in the set``
    instead of guessing from capitalisation — which misses obfuscated
    type names like ``#F`` and falsely includes uppercase-first
    property names.

    Consumers are expected to build this once per ABC (O(traits)),
    then reuse it across many ``check_mn_ns_set_typed`` calls.
    Wildcard-import harvesting currently still uses the
    capitalisation heuristic; this helper is exposed so that
    downstream deobfuscator passes can adopt the structural check
    incrementally.
    """
    from ..abc.constants import TRAIT_CLASS

    # ABC layer fields vary: the adapter exposes .strings / .multinames
    # while raw AbcFile uses .string_pool / .multiname_pool. Work with
    # whatever the caller passes in.
    instances = getattr(abc, "instances", [])
    classes = getattr(abc, "classes", [])
    scripts = getattr(abc, "scripts", [])

    out: set[int] = set()
    for bucket in (instances, classes, scripts):
        for entry in bucket:
            for t in getattr(entry, "traits", ()):
                # The adapter view uses name_idx, raw TraitInfo uses name.
                kind = getattr(t, "kind", None)
                if kind != TRAIT_CLASS:
                    continue
                name_idx = getattr(t, "name_idx",
                                   getattr(t, "name", 0))
                if name_idx:
                    out.add(name_idx)
    return out
