"""
AVM2 bytecode data structures.

These dataclasses mirror the structures defined in the AVM2 specification
(avm2overview.pdf). They represent the parsed contents of an ABC (ActionScript
Byte Code) block as found inside SWF DoABC/DoABC2 tags.

All pool indices (string, namespace, multiname, method) are zero-based.
Index 0 in each pool is the implicit default entry and is always present.

Reference: Adobe AVM2 Overview, Chapter 4 (abc file format).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class NamespaceInfo:
    """A namespace entry in the constant pool.

    Attributes:
        kind: Namespace kind constant (CONSTANT_NAMESPACE, CONSTANT_PACKAGE_NAMESPACE, etc.).
        name: Index into the string pool for the namespace name.
    """
    kind: int
    name: int


@dataclass(slots=True)
class NsSetInfo:
    """A namespace set — an unordered collection of namespaces.

    Used by Multiname and MultinameL to search across multiple namespaces.

    Attributes:
        namespaces: List of indices into the namespace pool.
    """
    namespaces: list[int]


@dataclass(slots=True)
class MultinameInfo:
    """A multiname entry in the constant pool.

    Multinames are the primary name-resolution mechanism in AVM2. The
    interpretation of fields depends on ``kind``:

    - QName/QNameA: ``ns`` = namespace index, ``name`` = string index.
    - RTQName/RTQNameA: ``name`` = string index (namespace from runtime stack).
    - RTQNameL/RTQNameLA: no fields (both name and namespace from stack).
    - Multiname/MultinameA: ``name`` = string index, ``ns_set`` = ns-set index.
    - MultinameL/MultinameLA: ``ns_set`` = ns-set index (name from stack).
    - TypeName: ``ns`` = base type multiname index (repurposed field),
      ``name`` = parameter count (repurposed), ``data`` = serialized
      parameter multiname indices as u30 bytes. This encoding is intentional
      for round-trip fidelity — a future version may add dedicated fields.

    Attributes:
        kind: Multiname kind constant (CONSTANT_QNAME, etc.).
        data: Raw serialized parameter bytes (TypeName only).
        ns:   Namespace index, or base type index for TypeName.
        name: String index, or parameter count for TypeName.
        ns_set: Namespace set index.
    """
    kind: int
    data: bytes = b""
    ns: int = 0
    name: int = 0
    ns_set: int = 0


@dataclass(slots=True)
class MethodInfo:
    """A method signature (not the body — see MethodBodyInfo).

    Attributes:
        param_count: Number of formal parameters.
        return_type: Multiname index of the return type (0 = any/void).
        param_types: List of multiname indices for each parameter type.
        name: String index for the method name (0 = anonymous).
        flags: Bitmask — 0x08 = HAS_OPTIONAL, 0x80 = HAS_PARAM_NAMES, etc.
        options: Default parameter values as (value_index, value_kind) pairs.
        param_names: String indices for parameter names (debug info).
    """
    param_count: int
    return_type: int
    param_types: list[int]
    name: int
    flags: int
    options: list[tuple] = field(default_factory=list)
    param_names: list[int] = field(default_factory=list)


@dataclass(slots=True)
class MetadataInfo:
    """Metadata attached to traits (e.g. [SWF(width=800)]).

    Attributes:
        name: String index for the metadata tag name.
        items: List of (key_string_index, value_string_index) pairs.
    """
    name: int
    items: list[tuple]


@dataclass(slots=True)
class TraitInfo:
    """A trait (field, method, getter, setter, class, or const) on a class or script.

    Fields beyond ``name`` and ``kind`` are populated according to the trait kind:

    - Slot/Const: ``slot_id``, ``type_name``, ``vindex``, ``vkind``.
      If ``vindex`` is 0 the trait has no default value and ``vkind`` is -1.
    - Method/Getter/Setter: ``disp_id``, ``method_idx``.
    - Class: ``slot_id``, ``class_idx``.
    - Function: ``slot_id``, ``function_idx``.

    The ``attr`` byte holds the ATTR_FINAL / ATTR_OVERRIDE / ATTR_METADATA bits.
    If ATTR_METADATA is set, ``metadata`` contains indices into ``AbcFile.metadata``.

    ``_raw`` caches the original bytes of this trait entry for round-trip
    fidelity. When the trait is unmodified the writer reuses it verbatim;
    mutated traits are re-serialized from the structured fields.

    Attributes:
        name: Multiname index for the trait name.
        kind: Trait kind (TRAIT_SLOT, TRAIT_METHOD, TRAIT_GETTER, etc.).
        attr: Trait attribute bits (upper nibble of the kind byte).
        slot_id: Slot/Const/Class/Function only. The slot id.
        type_name: Slot/Const only. Multiname index of the field type.
        vindex: Slot/Const only. Default value index (0 = no default).
        vkind: Slot/Const only. Default value kind byte (-1 = no default).
        method_idx: Method/Getter/Setter only. Index into AbcFile.methods.
        disp_id: Method/Getter/Setter only. Dispatch id.
        class_idx: Class only. Index into AbcFile.classes/instances.
        function_idx: Function only. Index into AbcFile.methods.
        metadata: Indices into AbcFile.metadata (empty unless ATTR_METADATA).
    """
    name: int
    kind: int
    attr: int = 0
    slot_id: int = 0
    type_name: int = 0
    vindex: int = 0
    vkind: int = -1
    method_idx: int = 0
    disp_id: int = 0
    class_idx: int = 0
    function_idx: int = 0
    metadata: list[int] = field(default_factory=list)
    _raw: bytes = b""


@dataclass(slots=True)
class InstanceInfo:
    """An instance (non-static side) of a class definition.

    Each InstanceInfo is paired with a ClassInfo at the same array index.

    Attributes:
        name: Multiname index for the class name.
        super_name: Multiname index for the superclass (0 = Object).
        flags: Bitmask — 0x01 = sealed, 0x02 = final, 0x04 = interface,
               0x08 = has protected namespace.
        protectedNs: Namespace index for the protected namespace (if flag 0x08 set).
        interfaces: List of multiname indices for implemented interfaces.
        iinit: Method index for the instance initializer (constructor).
        traits: Instance traits (fields, methods, getters, setters).
    """
    name: int
    super_name: int
    flags: int
    protectedNs: int = 0
    interfaces: list[int] = field(default_factory=list)
    iinit: int = 0
    traits: list[TraitInfo] = field(default_factory=list)


@dataclass(slots=True)
class ClassInfo:
    """The static side of a class definition.

    Paired with InstanceInfo at the same array index.

    Attributes:
        cinit: Method index for the static initializer.
        traits: Static traits (static fields, static methods).
    """
    cinit: int
    traits: list[TraitInfo] = field(default_factory=list)


@dataclass(slots=True)
class ScriptInfo:
    """A script entry point.

    Each ABC file has one or more scripts. The last script is the entry point.

    Attributes:
        init: Method index for the script initializer.
        traits: Script-level traits (top-level classes, functions, variables).
    """
    init: int
    traits: list[TraitInfo] = field(default_factory=list)


@dataclass(slots=True)
class ExceptionInfo:
    """An exception handler within a method body.

    Attributes:
        from_offset: Bytecode offset where the try block starts.
        to_offset: Bytecode offset where the try block ends.
        target: Bytecode offset of the catch handler.
        exc_type: Multiname index for the exception type (0 = catch-all).
        var_name: Multiname index for the catch variable name.
    """
    from_offset: int
    to_offset: int
    target: int
    exc_type: int
    var_name: int


@dataclass(slots=True)
class MethodBodyInfo:
    """The bytecode body of a method.

    Attributes:
        method: Index into the method array this body belongs to.
        max_stack: Maximum operand stack depth.
        local_count: Number of local registers (including 'this' at register 0).
        init_scope_depth: Initial scope stack depth.
        max_scope_depth: Maximum scope stack depth.
        code: Raw AVM2 bytecode bytes.
        exceptions: Exception handler table.
        traits: Activation traits (rare — used for method-level closures).
    """
    method: int
    max_stack: int
    local_count: int
    init_scope_depth: int
    max_scope_depth: int
    code: bytes
    exceptions: list[ExceptionInfo] = field(default_factory=list)
    traits: list[TraitInfo] = field(default_factory=list)


@dataclass(slots=True)
class AbcFile:
    """A complete ABC (ActionScript Byte Code) file.

    Contains the constant pools, method signatures, class definitions,
    scripts, and method bodies that make up one compilation unit.

    Constant pools always have an implicit entry at index 0:
    - int_pool[0] = 0
    - uint_pool[0] = 0
    - double_pool[0] = 0.0
    - string_pool[0] = ""
    - namespace_pool[0] = NamespaceInfo(0, 0)
    - ns_set_pool[0] = NsSetInfo([])
    - multiname_pool[0] = MultinameInfo(0)

    Attributes:
        minor_version: ABC minor version (typically 16).
        major_version: ABC major version (typically 46).
    """
    minor_version: int = 16
    major_version: int = 46

    # Constant pools (index 0 is always the implicit default)
    int_pool: list[int] = field(default_factory=lambda: [0])
    uint_pool: list[int] = field(default_factory=lambda: [0])

    # Raw LEB128 bytes for constant pool entries (for round-trip fidelity).
    # The AVM2 spec allows non-minimal LEB128 encodings (e.g. -1 encoded
    # as 4 bytes instead of 1) and uint values that exceed 30 bits.
    # We preserve the original encoding so serialize_abc() produces
    # byte-identical output.
    # Index 0 is empty (the implicit default). Populated by parse_abc().
    _int_pool_raw: list[bytes] = field(default_factory=lambda: [b""])
    _uint_pool_raw: list[bytes] = field(default_factory=lambda: [b""])
    double_pool: list[float] = field(default_factory=lambda: [0.0])
    string_pool: list[str] = field(default_factory=lambda: [""])
    namespace_pool: list[NamespaceInfo] = field(
        default_factory=lambda: [NamespaceInfo(0, 0)])
    ns_set_pool: list[NsSetInfo] = field(
        default_factory=lambda: [NsSetInfo([])])
    multiname_pool: list[MultinameInfo] = field(
        default_factory=lambda: [MultinameInfo(0)])

    # Definitions
    methods: list[MethodInfo] = field(default_factory=list)
    metadata: list[MetadataInfo] = field(default_factory=list)
    instances: list[InstanceInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    scripts: list[ScriptInfo] = field(default_factory=list)
    method_bodies: list[MethodBodyInfo] = field(default_factory=list)

    # ── Safe pool accessors ────────────────────────────────────────────────
    # These collapse the common "check bounds / fall back to sentinel" pattern
    # so decompilers and analyzers don't need to wrap every lookup in try/except.
    # The AVM2 spec treats index 0 as "any string / any name", so all accessors
    # return the spec-appropriate sentinel for idx 0 or out-of-range.

    def string(self, idx: int) -> str:
        """Return ``string_pool[idx]`` or ``""`` if idx is 0 or out of range.

        AVM2 treats string index 0 as "any string" sentinel; callers generally
        want an empty string in that case.
        """
        if 0 < idx < len(self.string_pool):
            return self.string_pool[idx]
        return ""

    def integer(self, idx: int) -> int:
        """Return ``int_pool[idx]`` or 0 if idx is 0 or out of range."""
        if 0 < idx < len(self.int_pool):
            return self.int_pool[idx]
        return 0

    def uinteger(self, idx: int) -> int:
        """Return ``uint_pool[idx]`` or 0 if idx is 0 or out of range."""
        if 0 < idx < len(self.uint_pool):
            return self.uint_pool[idx]
        return 0

    def double(self, idx: int) -> float:
        """Return ``double_pool[idx]`` or 0.0 if idx is 0 or out of range."""
        if 0 < idx < len(self.double_pool):
            return self.double_pool[idx]
        return 0.0

    # ── Namespace accessors ────────────────────────────────────────────────

    def namespace_name(self, idx: int) -> str:
        """Return the string name of a namespace, or ``""`` on idx 0 / out of range."""
        if 0 < idx < len(self.namespace_pool):
            return self.string(self.namespace_pool[idx].name)
        return ""

    def namespace_kind(self, idx: int) -> int:
        """Return the kind byte of a namespace, or 0 on idx 0 / out of range."""
        if 0 < idx < len(self.namespace_pool):
            return self.namespace_pool[idx].kind
        return 0

    # ── Multiname accessors ────────────────────────────────────────────────
    # These delegate to flashkit.info.member_info for the actual resolution
    # logic so name resolution stays in one place.

    def multiname_name(self, idx: int) -> str:
        """Return the unqualified name of a multiname, or ``"*"`` for idx 0.

        Handles parameterized types (``Vector.<int>``) by delegating to the
        full resolver.
        """
        from ..info.member_info import resolve_multiname
        return resolve_multiname(self, idx)

    def multiname_full(self, idx: int) -> str:
        """Return the fully qualified name ``"package.Name"``, or ``"*"`` for idx 0.

        Packages appear only for QName/QNameA multinames with a package namespace.
        Other multiname kinds fall back to the unqualified name.
        """
        from ..info.member_info import resolve_multiname_full
        package, name = resolve_multiname_full(self, idx)
        if package and name and name != "*":
            return f"{package}.{name}"
        return name

    def multiname_namespace(self, idx: int) -> str:
        """Return the package/namespace string of a multiname, or ``""``.

        For QName/QNameA this is the namespace's string name. For other kinds
        (RTQName, Multiname) the namespace is not statically known and ``""``
        is returned.
        """
        from ..info.member_info import resolve_multiname_full
        package, _ = resolve_multiname_full(self, idx)
        return package

    def multiname_type(self, idx: int) -> str:
        """Alias for :meth:`multiname_name` — returns a formatted type string.

        For TypeName multinames this includes the generic parameters, e.g.
        ``"Vector.<int>"``. Provided for readability at call sites that are
        resolving a trait type reference rather than an arbitrary multiname.
        """
        return self.multiname_name(idx)

    def multiname_is_attr(self, idx: int) -> bool:
        """Return True if the multiname is an XML attribute form (QNameA, etc.)."""
        if not (0 < idx < len(self.multiname_pool)):
            return False
        from .constants import (
            CONSTANT_QNAME_A, CONSTANT_RTQNAME_A, CONSTANT_RTQNAME_LA,
            CONSTANT_MULTINAME_A, CONSTANT_MULTINAME_LA,
        )
        return self.multiname_pool[idx].kind in (
            CONSTANT_QNAME_A, CONSTANT_RTQNAME_A, CONSTANT_RTQNAME_LA,
            CONSTANT_MULTINAME_A, CONSTANT_MULTINAME_LA,
        )

    def multiname_is_runtime(self, idx: int) -> bool:
        """Return True if the multiname needs runtime resolution of name and/or ns.

        RTQName/RTQNameL/MultinameL all pop their name and/or namespace off
        the AVM2 operand stack at runtime, so static lookup returns a
        placeholder. Decompilers use this to emit stack-sourced expressions
        instead of literal names.
        """
        if not (0 < idx < len(self.multiname_pool)):
            return False
        from .constants import (
            CONSTANT_RTQNAME, CONSTANT_RTQNAME_A,
            CONSTANT_RTQNAME_L, CONSTANT_RTQNAME_LA,
            CONSTANT_MULTINAME_L, CONSTANT_MULTINAME_LA,
        )
        return self.multiname_pool[idx].kind in (
            CONSTANT_RTQNAME, CONSTANT_RTQNAME_A,
            CONSTANT_RTQNAME_L, CONSTANT_RTQNAME_LA,
            CONSTANT_MULTINAME_L, CONSTANT_MULTINAME_LA,
        )
