"""
Internal ABC adapter for the decompiler.

The ported decompiler code was written against an ABC schema that differs
slightly from flashkit's :class:`~flashkit.abc.types.AbcFile`:

- Pool attribute names (``strings`` vs ``string_pool``, ``multinames`` vs
  ``multiname_pool``, etc.)
- Compact helper method names (``mn_full`` / ``ns_kind`` vs
  ``multiname_full`` / ``namespace_kind``)
- Trait field name (``name_idx`` vs ``name``) and instance fields
  (``name_idx``/``super_idx`` vs ``name``/``super_name``)
- ``method_bodies`` lookup: dict keyed by method index vs. list

Rather than renaming ~1000 call sites inside the decompiler, the adapter
presents flashkit's ``AbcFile`` with the shape the decompiler expects.
This keeps the decompiler code faithful to the well-tested original
algorithm while letting flashkit keep its preferred public API.

Nothing in this module is part of flashkit's public surface. It is
implementation detail of the decompiler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

from ..abc.types import (
    AbcFile, TraitInfo, InstanceInfo, MethodBodyInfo, ExceptionInfo,
    MultinameInfo, NamespaceInfo, MethodInfo,
)
from ..abc.parser import read_u30
from ..abc.constants import (
    CONSTANT_QNAME, CONSTANT_QNAME_A,
    CONSTANT_RTQNAME, CONSTANT_RTQNAME_A,
    CONSTANT_RTQNAME_L, CONSTANT_RTQNAME_LA,
    CONSTANT_MULTINAME, CONSTANT_MULTINAME_A,
    CONSTANT_MULTINAME_L, CONSTANT_MULTINAME_LA,
    CONSTANT_TYPENAME,
)

if TYPE_CHECKING:
    from ..abc.types import AbcFile as _AbcFile


class _TraitView:
    """View of a TraitInfo with source-decompiler-compatible field names."""
    __slots__ = ("_t",)

    def __init__(self, trait: TraitInfo) -> None:
        self._t = trait

    # Source expects name_idx; flashkit stores it as name.
    @property
    def name_idx(self) -> int:
        return self._t.name

    # These fields have the same names on both sides, just forward.
    @property
    def kind(self) -> int:
        return self._t.kind

    @property
    def attr(self) -> int:
        return self._t.attr

    @property
    def slot_id(self) -> int:
        return self._t.slot_id

    @property
    def type_name(self) -> int:
        return self._t.type_name

    @property
    def vindex(self) -> int:
        return self._t.vindex

    @property
    def vkind(self) -> int:
        return self._t.vkind

    @property
    def method_idx(self) -> int:
        return self._t.method_idx

    @property
    def disp_id(self) -> int:
        return self._t.disp_id

    @property
    def class_idx(self) -> int:
        return self._t.class_idx

    @property
    def function_idx(self) -> int:
        return self._t.function_idx

    @property
    def metadata(self) -> list[int]:
        return self._t.metadata


class _InstanceView:
    """View of InstanceInfo with ``name_idx``/``super_idx`` names."""
    __slots__ = ("_inst",)

    def __init__(self, inst: InstanceInfo) -> None:
        self._inst = inst

    @property
    def name_idx(self) -> int:
        return self._inst.name

    @property
    def super_idx(self) -> int:
        return self._inst.super_name

    @property
    def flags(self) -> int:
        return self._inst.flags

    @property
    def protected_ns(self) -> int:
        return self._inst.protectedNs

    @property
    def interfaces(self) -> list[int]:
        return self._inst.interfaces

    @property
    def iinit(self) -> int:
        return self._inst.iinit

    @property
    def traits(self) -> list[_TraitView]:
        return [_TraitView(t) for t in self._inst.traits]


class _ClassView:
    """View of ClassInfo with a ``traits`` field wrapping trait views."""
    __slots__ = ("_cls",)

    def __init__(self, cls) -> None:
        self._cls = cls

    @property
    def cinit(self) -> int:
        return self._cls.cinit

    @property
    def traits(self) -> list[_TraitView]:
        return [_TraitView(t) for t in self._cls.traits]


class _ScriptView:
    """View of ScriptInfo. Source code refers to ``sinit``; flashkit ``init``."""
    __slots__ = ("_s",)

    def __init__(self, script) -> None:
        self._s = script

    @property
    def sinit(self) -> int:
        return self._s.init

    @property
    def init(self) -> int:          # keep alias both ways
        return self._s.init

    @property
    def traits(self) -> list[_TraitView]:
        return [_TraitView(t) for t in self._s.traits]


class _ExceptionView:
    """View of ExceptionInfo. Source names offsets ``from_pos``/``to_pos``;
    flashkit uses ``from_offset``/``to_offset``."""
    __slots__ = ("_e",)

    def __init__(self, e: ExceptionInfo) -> None:
        self._e = e

    @property
    def from_pos(self) -> int:
        return self._e.from_offset

    @property
    def to_pos(self) -> int:
        return self._e.to_offset

    @property
    def target(self) -> int:
        return self._e.target

    @property
    def exc_type(self) -> int:
        return self._e.exc_type

    @property
    def var_name(self) -> int:
        return self._e.var_name


class _MethodInfoView:
    """View of MethodInfo exposing ``optional_values`` in place of ``options``
    and ``name_idx`` in place of ``name``. Everything else forwards."""
    __slots__ = ("_m",)

    def __init__(self, m: MethodInfo) -> None:
        self._m = m

    @property
    def param_count(self) -> int:
        return self._m.param_count

    @property
    def return_type(self) -> int:
        return self._m.return_type

    @property
    def param_types(self) -> list[int]:
        return self._m.param_types

    @property
    def name_idx(self) -> int:
        return self._m.name

    @property
    def name(self) -> int:
        return self._m.name

    @property
    def flags(self) -> int:
        return self._m.flags

    @property
    def optional_values(self) -> list:
        return self._m.options

    @property
    def options(self) -> list:
        return self._m.options

    @property
    def param_names(self) -> list[int]:
        return self._m.param_names


class _MethodBodyView:
    """View of MethodBodyInfo with traits wrapped."""
    __slots__ = ("_b",)

    def __init__(self, body: MethodBodyInfo) -> None:
        self._b = body

    @property
    def method(self) -> int:
        return self._b.method

    @property
    def method_idx(self) -> int:
        return self._b.method

    @property
    def max_stack(self) -> int:
        return self._b.max_stack

    @property
    def local_count(self) -> int:
        return self._b.local_count

    @property
    def init_scope_depth(self) -> int:
        return self._b.init_scope_depth

    @property
    def max_scope_depth(self) -> int:
        return self._b.max_scope_depth

    @property
    def code(self) -> bytes:
        return self._b.code

    @code.setter
    def code(self, value: bytes) -> None:
        self._b.code = value

    @property
    def exceptions(self) -> list[_ExceptionView]:
        return [_ExceptionView(e) for e in self._b.exceptions]

    @property
    def traits(self) -> list[_TraitView]:
        return [_TraitView(t) for t in self._b.traits]


class _MethodBodyMap:
    """Dict-like view: ``body_map[method_idx]`` returns a body view.

    flashkit stores bodies as a list indexed by body index; callers want
    to index by method_idx. We build a once-computed mapping.
    """
    __slots__ = ("_idx_to_body",)

    def __init__(self, abc: AbcFile) -> None:
        self._idx_to_body: dict[int, MethodBodyInfo] = {}
        for body in abc.method_bodies:
            self._idx_to_body[body.method] = body

    def get(self, method_idx: int, default=None):
        body = self._idx_to_body.get(method_idx)
        return _MethodBodyView(body) if body is not None else default

    def __contains__(self, method_idx: int) -> bool:
        return method_idx in self._idx_to_body

    def __getitem__(self, method_idx: int) -> _MethodBodyView:
        return _MethodBodyView(self._idx_to_body[method_idx])

    def __iter__(self) -> Iterator[int]:
        return iter(self._idx_to_body)

    def values(self):
        return (_MethodBodyView(b) for b in self._idx_to_body.values())


def _multiname_as_tuple(mn: MultinameInfo) -> tuple:
    """Convert a flashkit MultinameInfo dataclass into the legacy tuple shape.

    The ported decompiler expects multinames as ``(kind, payload_tuple)``
    where ``payload_tuple``'s shape depends on ``kind``:
      QName/QNameA:                    (ns, name)
      RTQName/RTQNameA:                (name,)
      RTQNameL/RTQNameLA:              ()
      Multiname/MultinameA:            (name, ns_set)
      MultinameL/MultinameLA:          (ns_set,)
      TypeName:                        (base_qn, (param_mn, ...))
    """
    k = mn.kind
    if k in (CONSTANT_QNAME, CONSTANT_QNAME_A):
        return (k, (mn.ns, mn.name))
    if k in (CONSTANT_RTQNAME, CONSTANT_RTQNAME_A):
        return (k, (mn.name,))
    if k in (CONSTANT_RTQNAME_L, CONSTANT_RTQNAME_LA):
        return (k, ())
    if k in (CONSTANT_MULTINAME, CONSTANT_MULTINAME_A):
        return (k, (mn.name, mn.ns_set))
    if k in (CONSTANT_MULTINAME_L, CONSTANT_MULTINAME_LA):
        return (k, (mn.ns_set,))
    if k == CONSTANT_TYPENAME:
        # data is packed u30 param indices; mn.name = param count,
        # mn.ns = base type multiname index.
        params: list[int] = []
        off = 0
        for _ in range(mn.name):
            if off >= len(mn.data):
                break
            idx, off = read_u30(mn.data, off)
            params.append(idx)
        return (k, (mn.ns, tuple(params)))
    return (k, ())


def _namespace_as_tuple(ns: NamespaceInfo) -> tuple:
    """Convert a NamespaceInfo to ``(kind, name_string_index)`` tuple."""
    return (ns.kind, ns.name)


class _MultinamePoolView:
    """List-like view over flashkit's multiname_pool that yields legacy tuples."""
    __slots__ = ("_mns",)

    def __init__(self, multiname_pool: list[MultinameInfo]) -> None:
        self._mns = multiname_pool

    def __getitem__(self, idx: int) -> tuple:
        return _multiname_as_tuple(self._mns[idx])

    def __len__(self) -> int:
        return len(self._mns)

    def __iter__(self):
        return (_multiname_as_tuple(mn) for mn in self._mns)


class _NamespacePoolView:
    """List-like view over flashkit's namespace_pool that yields ``(kind, name)`` tuples."""
    __slots__ = ("_nss",)

    def __init__(self, namespace_pool: list[NamespaceInfo]) -> None:
        self._nss = namespace_pool

    def __getitem__(self, idx: int) -> tuple:
        return _namespace_as_tuple(self._nss[idx])

    def __len__(self) -> int:
        return len(self._nss)

    def __iter__(self):
        return (_namespace_as_tuple(ns) for ns in self._nss)


class _NsSetPoolView:
    """List-like view: ``ns_sets[i]`` yields a ``list[int]`` of namespace indices."""
    __slots__ = ("_sets",)

    def __init__(self, ns_set_pool) -> None:
        self._sets = ns_set_pool

    def __getitem__(self, idx: int) -> list[int]:
        return self._sets[idx].namespaces

    def __len__(self) -> int:
        return len(self._sets)

    def __iter__(self):
        return (s.namespaces for s in self._sets)


class AbcView:
    """Wraps a flashkit :class:`AbcFile` to match the decompiler's expected API.

    Attribute renames:
        string_pool       -> strings
        int_pool          -> integers
        uint_pool         -> uintegers
        double_pool       -> doubles
        namespace_pool    -> namespaces
        ns_set_pool       -> ns_sets
        multiname_pool    -> multinames
        metadata          -> metadata_entries

    Method aliases (compact spec names):
        mn_full(idx)   -> multiname_full(idx)
        mn_name(idx)   -> multiname_name(idx)
        mn_ns(idx)     -> multiname_namespace(idx)
        ns_name(idx)   -> namespace_name(idx)
        ns_kind(idx)   -> namespace_kind(idx)
        type_name(idx) -> multiname_type(idx)
        mn_is_attr(idx)     -> multiname_is_attr(idx)
        mn_needs_rt_name/ns(idx) -> multiname_is_runtime(idx)

    Collection views:
        method_bodies: dict-like lookup by method_idx (vs flashkit's list)
        instances, classes, scripts: wrapped with _*_View to expose the
                                     renamed fields (name_idx, super_idx, etc.)
    """

    def __init__(self, abc: AbcFile) -> None:
        self._abc = abc

        # Pool aliases. Scalar pools are shared lists; structured pools are
        # wrapped in views that yield the legacy tuple shape.
        self.strings = abc.string_pool
        self.integers = abc.int_pool
        self.uintegers = abc.uint_pool
        self.doubles = abc.double_pool
        self.namespaces = _NamespacePoolView(abc.namespace_pool)
        self.ns_sets = _NsSetPoolView(abc.ns_set_pool)
        self.multinames = _MultinamePoolView(abc.multiname_pool)
        self.methods = [_MethodInfoView(m) for m in abc.methods]
        self.metadata_entries = abc.metadata

        # Wrapped views
        self.instances = [_InstanceView(i) for i in abc.instances]
        self.classes = [_ClassView(c) for c in abc.classes]
        self.scripts = [_ScriptView(s) for s in abc.scripts]
        self.method_bodies = _MethodBodyMap(abc)

    # ── Resolution helper aliases ──────────────────────────────────────

    def mn_full(self, idx: int) -> str:
        return self._abc.multiname_full(idx)

    def mn_name(self, idx: int) -> str:
        return self._abc.multiname_name(idx)

    def mn_ns(self, idx: int) -> str:
        return self._abc.multiname_namespace(idx)

    def ns_name(self, idx: int) -> str:
        return self._abc.namespace_name(idx)

    def ns_kind(self, idx: int) -> int:
        return self._abc.namespace_kind(idx)

    def type_name(self, idx: int) -> str:
        return self._abc.multiname_type(idx)

    def mn_is_attr(self, idx: int) -> bool:
        return self._abc.multiname_is_attr(idx)

    def mn_needs_rt_name(self, idx: int) -> bool:
        # Flashkit collapses needs_rt_name and needs_rt_ns into one helper;
        # the decompiler only ever checks one at a time, so aliasing both to
        # the combined helper is safe for all call sites that just want to
        # know "is this a runtime-resolved multiname".
        return self._abc.multiname_is_runtime(idx)

    def mn_needs_rt_ns(self, idx: int) -> bool:
        return self._abc.multiname_is_runtime(idx)

    def mn_ns_kind(self, idx: int) -> int:
        """Namespace kind of the namespace referenced by a QName multiname."""
        if not (0 < idx < len(self._abc.multiname_pool)):
            return 0
        mn = self._abc.multiname_pool[idx]
        from ..abc.constants import CONSTANT_QNAME, CONSTANT_QNAME_A
        if mn.kind in (CONSTANT_QNAME, CONSTANT_QNAME_A):
            return self._abc.namespace_kind(mn.ns)
        return 0

    def default_value_str(self, vkind: int, vindex: int) -> str:
        """Format a default parameter value from (vkind, vindex) pair."""
        import math
        from ..abc.constants import (
            CONSTANT_NAMESPACE, CONSTANT_PACKAGE_NAMESPACE,
            CONSTANT_PACKAGE_INTERNAL_NS, CONSTANT_PROTECTED_NAMESPACE,
            CONSTANT_EXPLICIT_NAMESPACE, CONSTANT_STATIC_PROTECTED_NS,
            CONSTANT_PRIVATE_NS,
        )
        # AVM2 spec constant kinds for literal values used in default args.
        CONSTANT_INT = 0x03
        CONSTANT_UINT = 0x04
        CONSTANT_DOUBLE = 0x06
        CONSTANT_UTF8 = 0x01
        CONSTANT_TRUE = 0x0B
        CONSTANT_FALSE = 0x0A
        CONSTANT_NULL = 0x0C
        CONSTANT_UNDEFINED = 0x00

        abc = self._abc
        if vkind == CONSTANT_INT:
            return str(abc.integer(vindex))
        if vkind == CONSTANT_UINT:
            return str(abc.uinteger(vindex))
        if vkind == CONSTANT_DOUBLE:
            v = abc.double(vindex)
            if math.isnan(v):
                return "NaN"
            if math.isinf(v):
                return "Infinity" if v > 0 else "-Infinity"
            if v == int(v) and abs(v) < 1e15:
                return f"{int(v)}.0"
            return f"{v:.15g}"
        if vkind == CONSTANT_UTF8:
            return f'"{abc.string(vindex)}"'
        if vkind == CONSTANT_TRUE:
            return "true"
        if vkind == CONSTANT_FALSE:
            return "false"
        if vkind == CONSTANT_NULL:
            return "null"
        if vkind == CONSTANT_UNDEFINED or (vkind == 0 and vindex == 0):
            return "undefined"
        if vkind in (CONSTANT_NAMESPACE, CONSTANT_PACKAGE_NAMESPACE,
                     CONSTANT_PACKAGE_INTERNAL_NS, CONSTANT_PROTECTED_NAMESPACE,
                     CONSTANT_EXPLICIT_NAMESPACE, CONSTANT_STATIC_PROTECTED_NS,
                     CONSTANT_PRIVATE_NS):
            return abc.namespace_name(vindex) or "null"
        return "undefined"
