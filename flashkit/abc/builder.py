"""
Programmatic ABC (ActionScript Byte Code) builder.

Construct an ``AbcFile`` step-by-step: add strings, namespaces,
multinames, methods, classes, and method bodies through a high-level API.
The resulting ``AbcFile`` can be serialized with ``serialize_abc()``.

Usage::

    from flashkit.abc.builder import AbcBuilder
    from flashkit.abc.writer import serialize_abc

    b = AbcBuilder()

    # Build constant pools
    cls_str = b.string("MyClass")
    pkg_str = b.string("com.example")
    ns = b.package_namespace(pkg_str)
    cls_mn = b.qname(ns, cls_str)

    # Build a method
    ctor = b.method()
    b.method_body(ctor, code=b.asm(
        b.op_getlocal_0(),
        b.op_pushscope(),
        b.op_returnvoid(),
    ))

    # Build a class
    b.define_class(name=cls_mn, super_name=0, constructor=ctor)

    abc = b.build()
    raw = serialize_abc(abc)
"""

from __future__ import annotations

from .types import (
    AbcFile, NamespaceInfo, NsSetInfo, MultinameInfo,
    MethodInfo, MetadataInfo, TraitInfo, InstanceInfo,
    ClassInfo as AbcClassInfo, ScriptInfo, ExceptionInfo, MethodBodyInfo,
)
from .parser import write_u30
from .constants import (
    CONSTANT_QNAME, CONSTANT_QNAME_A,
    CONSTANT_RTQNAME, CONSTANT_RTQNAME_A,
    CONSTANT_MULTINAME, CONSTANT_MULTINAME_A,
    CONSTANT_MULTINAME_L, CONSTANT_MULTINAME_LA,
    CONSTANT_TYPENAME,
    CONSTANT_NAMESPACE, CONSTANT_PACKAGE_NAMESPACE, CONSTANT_PACKAGE_INTERNAL_NS,
    CONSTANT_PROTECTED_NAMESPACE, CONSTANT_EXPLICIT_NAMESPACE,
    CONSTANT_STATIC_PROTECTED_NS, CONSTANT_PRIVATE_NS,
    TRAIT_SLOT, TRAIT_METHOD, TRAIT_GETTER, TRAIT_SETTER,
    TRAIT_CLASS, TRAIT_FUNCTION, TRAIT_CONST,
    ATTR_FINAL, ATTR_OVERRIDE, ATTR_METADATA,
    METHOD_HAS_OPTIONAL, METHOD_HAS_PARAM_NAMES,
    METHOD_NEED_ARGUMENTS, METHOD_NEED_ACTIVATION, METHOD_NEED_REST,
    INSTANCE_SEALED, INSTANCE_FINAL, INSTANCE_INTERFACE, INSTANCE_PROTECTED_NS,
)
from .opcodes import (
    OP_GETLOCAL_0, OP_PUSHSCOPE, OP_RETURNVOID, OP_RETURNVALUE,
    OP_CONSTRUCTSUPER, OP_PUSHSTRING, OP_CALLPROPVOID, OP_CALLPROPERTY,
    OP_GETPROPERTY, OP_SETPROPERTY, OP_GETLEX, OP_FINDPROPSTRICT,
    OP_CONSTRUCTPROP, OP_NEWARRAY, OP_NEWCLASS, OP_COERCE,
    OP_POP, OP_DUP, OP_SWAP, OP_PUSHTRUE, OP_PUSHFALSE, OP_PUSHNULL,
    OP_PUSHUNDEFINED, OP_PUSHBYTE, OP_PUSHSHORT, OP_PUSHINT, OP_PUSHUINT,
    OP_PUSHDOUBLE, OP_CONVERT_I, OP_CONVERT_S, OP_CONVERT_D,
    OP_COERCE_A, OP_COERCE_S, OP_INITPROPERTY, OP_GETLOCAL,
    OP_SETLOCAL, OP_GETLOCAL_1, OP_GETLOCAL_2, OP_GETLOCAL_3,
    OP_SETLOCAL_0, OP_SETLOCAL_1, OP_SETLOCAL_2, OP_SETLOCAL_3,
    OP_NEWFUNCTION, OP_CALL, OP_CONSTRUCT,
    OP_JUMP, OP_IFTRUE, OP_IFFALSE,
    OP_ADD, OP_SUBTRACT, OP_MULTIPLY, OP_DIVIDE,
    OP_EQUALS, OP_STRICTEQUALS, OP_LESSTHAN, OP_GREATEREQUALS,
    OP_NOT, OP_NOP, OP_LABEL, OP_THROW, OP_DEBUGFILE, OP_DEBUGLINE,
)


def _encode_s24(value: int) -> bytes:
    """Encode a signed 24-bit offset (little-endian)."""
    if value < 0:
        value += 1 << 24
    return bytes([value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF])


class AbcBuilder:
    """High-level builder for constructing an AbcFile programmatically.

    Pools are managed automatically — adding the same string twice
    returns the same index. Index 0 in each pool is reserved for
    the implicit default.
    """

    def __init__(self) -> None:
        self._int_pool: list[int] = [0]
        self._uint_pool: list[int] = [0]
        self._double_pool: list[float] = [0.0]
        self._string_pool: list[str] = [""]
        self._namespace_pool: list[NamespaceInfo] = [NamespaceInfo(0, 0)]
        self._ns_set_pool: list[NsSetInfo] = [NsSetInfo([])]
        self._multiname_pool: list[MultinameInfo] = [MultinameInfo(0)]

        self._methods: list[MethodInfo] = []
        self._metadata: list[MetadataInfo] = []
        self._instances: list[InstanceInfo] = []
        self._classes: list[AbcClassInfo] = []
        self._scripts: list[ScriptInfo] = []
        self._method_bodies: list[MethodBodyInfo] = []

        # Dedup caches
        self._string_cache: dict[str, int] = {"": 0}

    # ── Constant pool: strings ─────────────────────────────────────────

    def string(self, value: str) -> int:
        """Add a string to the pool (or return existing index).

        Args:
            value: The string value.

        Returns:
            Index into the string pool.
        """
        if value in self._string_cache:
            return self._string_cache[value]
        idx = len(self._string_pool)
        self._string_pool.append(value)
        self._string_cache[value] = idx
        return idx

    # ── Constant pool: integers / doubles ──────────────────────────────

    def integer(self, value: int) -> int:
        """Add a signed integer to the int pool.

        Returns:
            Index into the int pool.
        """
        # Check for existing (skip default at 0)
        for i in range(1, len(self._int_pool)):
            if self._int_pool[i] == value:
                return i
        idx = len(self._int_pool)
        self._int_pool.append(value)
        return idx

    def uint(self, value: int) -> int:
        """Add an unsigned integer to the uint pool.

        Returns:
            Index into the uint pool.
        """
        for i in range(1, len(self._uint_pool)):
            if self._uint_pool[i] == value:
                return i
        idx = len(self._uint_pool)
        self._uint_pool.append(value)
        return idx

    def double(self, value: float) -> int:
        """Add a double to the double pool.

        Returns:
            Index into the double pool.
        """
        for i in range(1, len(self._double_pool)):
            if self._double_pool[i] == value:
                return i
        idx = len(self._double_pool)
        self._double_pool.append(value)
        return idx

    # ── Constant pool: namespaces ──────────────────────────────────────

    def namespace(self, kind: int, name: int) -> int:
        """Add a namespace to the pool.

        Args:
            kind: Namespace kind constant (CONSTANT_NAMESPACE, etc.).
            name: String pool index for the namespace name.

        Returns:
            Index into the namespace pool.
        """
        for i in range(1, len(self._namespace_pool)):
            ns = self._namespace_pool[i]
            if ns.kind == kind and ns.name == name:
                return i
        idx = len(self._namespace_pool)
        self._namespace_pool.append(NamespaceInfo(kind, name))
        return idx

    def package_namespace(self, name: int | str) -> int:
        """Add a public package namespace.

        Args:
            name: String pool index, or a string (auto-added to pool).

        Returns:
            Namespace pool index.
        """
        if isinstance(name, str):
            name = self.string(name)
        return self.namespace(CONSTANT_PACKAGE_NAMESPACE, name)

    def private_namespace(self, name: int | str = 0) -> int:
        """Add a private namespace.

        Args:
            name: String pool index, or a string. Default 0 (empty).

        Returns:
            Namespace pool index.
        """
        if isinstance(name, str):
            name = self.string(name)
        return self.namespace(CONSTANT_PRIVATE_NS, name)

    def internal_namespace(self, name: int | str) -> int:
        """Add a package-internal namespace.

        Args:
            name: String pool index, or a string.

        Returns:
            Namespace pool index.
        """
        if isinstance(name, str):
            name = self.string(name)
        return self.namespace(CONSTANT_PACKAGE_INTERNAL_NS, name)

    def protected_namespace(self, name: int | str) -> int:
        """Add a protected namespace.

        Args:
            name: String pool index, or a string.

        Returns:
            Namespace pool index.
        """
        if isinstance(name, str):
            name = self.string(name)
        return self.namespace(CONSTANT_PROTECTED_NAMESPACE, name)

    # ── Constant pool: namespace sets ──────────────────────────────────

    def ns_set(self, namespaces: list[int]) -> int:
        """Add a namespace set to the pool.

        Args:
            namespaces: List of namespace pool indices.

        Returns:
            Index into the namespace set pool.
        """
        idx = len(self._ns_set_pool)
        self._ns_set_pool.append(NsSetInfo(list(namespaces)))
        return idx

    # ── Constant pool: multinames ──────────────────────────────────────

    def qname(self, ns: int, name: int | str) -> int:
        """Add a QName (qualified name) multiname.

        Args:
            ns: Namespace pool index.
            name: String pool index, or a string.

        Returns:
            Multiname pool index.
        """
        if isinstance(name, str):
            name = self.string(name)
        for i in range(1, len(self._multiname_pool)):
            mn = self._multiname_pool[i]
            if mn.kind == CONSTANT_QNAME and mn.ns == ns and mn.name == name:
                return i
        idx = len(self._multiname_pool)
        self._multiname_pool.append(MultinameInfo(
            kind=CONSTANT_QNAME, ns=ns, name=name))
        return idx

    def multiname(self, name: int | str, ns_set: int) -> int:
        """Add a Multiname (name + namespace set).

        Args:
            name: String pool index, or a string.
            ns_set: Namespace set pool index.

        Returns:
            Multiname pool index.
        """
        if isinstance(name, str):
            name = self.string(name)
        idx = len(self._multiname_pool)
        self._multiname_pool.append(MultinameInfo(
            kind=CONSTANT_MULTINAME, name=name, ns_set=ns_set))
        return idx

    def rtqname(self, name: int | str) -> int:
        """Add a runtime-qualified name (namespace from stack).

        Args:
            name: String pool index, or a string.

        Returns:
            Multiname pool index.
        """
        if isinstance(name, str):
            name = self.string(name)
        idx = len(self._multiname_pool)
        self._multiname_pool.append(MultinameInfo(
            kind=CONSTANT_RTQNAME, name=name))
        return idx

    def typename(self, base: int, params: list[int]) -> int:
        """Add a TypeName (parameterized type) multiname, e.g. Vector.<int>.

        Args:
            base: Multiname pool index for the base type (e.g. Vector).
            params: List of multiname pool indices for type parameters.

        Returns:
            Multiname pool index.
        """
        param_bytes = bytearray()
        for p in params:
            param_bytes += write_u30(p)
        idx = len(self._multiname_pool)
        self._multiname_pool.append(MultinameInfo(
            kind=CONSTANT_TYPENAME, ns=base, name=len(params),
            data=bytes(param_bytes)))
        return idx

    # ── Methods ────────────────────────────────────────────────────────

    def method(
        self,
        params: list[int] | None = None,
        return_type: int = 0,
        name: int | str = 0,
        flags: int = 0,
        param_names: list[int | str] | None = None,
        options: list[tuple[int, int]] | None = None,
    ) -> int:
        """Add a method signature.

        Args:
            params: List of multiname indices for parameter types.
            return_type: Multiname index for return type (0 = any).
            name: String pool index or string for method name.
            flags: Method flags bitmask.
            param_names: String pool indices or strings for debug param names.
            options: Default values as (value_index, value_kind) pairs.

        Returns:
            Method index.
        """
        params = params or []
        if isinstance(name, str):
            name = self.string(name) if name else 0

        resolved_flags = flags
        resolved_param_names: list[int] = []
        if param_names:
            resolved_flags |= METHOD_HAS_PARAM_NAMES
            for pn in param_names:
                if isinstance(pn, str):
                    resolved_param_names.append(self.string(pn))
                else:
                    resolved_param_names.append(pn)

        resolved_options: list[tuple[int, int]] = []
        if options:
            resolved_flags |= METHOD_HAS_OPTIONAL
            resolved_options = list(options)

        mi = MethodInfo(
            param_count=len(params),
            return_type=return_type,
            param_types=list(params),
            name=name,
            flags=resolved_flags,
            options=resolved_options,
            param_names=resolved_param_names,
        )
        idx = len(self._methods)
        self._methods.append(mi)
        return idx

    # ── Method bodies ──────────────────────────────────────────────────

    def method_body(
        self,
        method: int,
        code: bytes,
        max_stack: int = 2,
        local_count: int = 1,
        init_scope_depth: int = 0,
        max_scope_depth: int = 1,
        exceptions: list[ExceptionInfo] | None = None,
    ) -> int:
        """Add a method body (bytecode) for a method.

        Args:
            method: Method index this body belongs to.
            code: Raw AVM2 bytecode bytes (use asm() or op_*() to build).
            max_stack: Maximum operand stack depth.
            local_count: Number of local registers.
            init_scope_depth: Initial scope depth.
            max_scope_depth: Maximum scope depth.
            exceptions: Exception handler table.

        Returns:
            Index into the method bodies array.
        """
        mb = MethodBodyInfo(
            method=method,
            max_stack=max_stack,
            local_count=local_count,
            init_scope_depth=init_scope_depth,
            max_scope_depth=max_scope_depth,
            code=code,
            exceptions=exceptions or [],
        )
        idx = len(self._method_bodies)
        self._method_bodies.append(mb)
        return idx

    # ── Traits ─────────────────────────────────────────────────────────

    @staticmethod
    def trait_slot(
        name: int,
        type_mn: int = 0,
        slot_id: int = 0,
        default_value: int = 0,
        default_kind: int = 0,
        is_const: bool = False,
    ) -> TraitInfo:
        """Build a slot/const trait (field).

        Args:
            name: Multiname index for the field name.
            type_mn: Multiname index for the field type (0 = any).
            slot_id: Slot index.
            default_value: Default value pool index (0 = none).
            default_kind: Default value kind (only if default_value != 0).
            is_const: If True, TRAIT_CONST; else TRAIT_SLOT.

        Returns:
            TraitInfo ready to attach to an instance or class.
        """
        return TraitInfo(
            name=name,
            kind=TRAIT_CONST if is_const else TRAIT_SLOT,
            slot_id=slot_id,
            type_name=type_mn,
            vindex=default_value,
            vkind=default_kind if default_value else -1,
        )

    @staticmethod
    def trait_method(
        name: int,
        method: int,
        disp_id: int = 0,
        kind: int = TRAIT_METHOD,
        attrs: int = 0,
    ) -> TraitInfo:
        """Build a method/getter/setter trait.

        Args:
            name: Multiname index for the method name.
            method: Method index.
            disp_id: Dispatch ID (usually 0).
            kind: TRAIT_METHOD, TRAIT_GETTER, or TRAIT_SETTER.
            attrs: Attribute flags (ATTR_FINAL, ATTR_OVERRIDE).

        Returns:
            TraitInfo ready to attach.
        """
        return TraitInfo(
            name=name, kind=kind, attr=attrs,
            disp_id=disp_id, method_idx=method,
        )

    @staticmethod
    def trait_class(name: int, class_index: int, slot_id: int = 0) -> TraitInfo:
        """Build a class trait (for script-level class definitions).

        Args:
            name: Multiname index for the class name.
            class_index: Index into the class array.
            slot_id: Slot index.

        Returns:
            TraitInfo ready to attach to a script.
        """
        return TraitInfo(
            name=name, kind=TRAIT_CLASS,
            slot_id=slot_id, class_idx=class_index,
        )

    # ── Classes ────────────────────────────────────────────────────────

    def define_class(
        self,
        name: int,
        super_name: int = 0,
        constructor: int | None = None,
        static_init: int | None = None,
        flags: int = INSTANCE_SEALED,
        interfaces: list[int] | None = None,
        protected_ns: int = 0,
        instance_traits: list[TraitInfo] | None = None,
        static_traits: list[TraitInfo] | None = None,
    ) -> int:
        """Define a class (instance + static side).

        If constructor or static_init are not provided, empty methods
        are created automatically.

        Args:
            name: Multiname index for the class name.
            super_name: Multiname index for the superclass (0 = Object).
            constructor: Method index for the constructor. Auto-created if None.
            static_init: Method index for the static initializer. Auto-created if None.
            flags: Instance flags bitmask.
            interfaces: List of multiname indices for interfaces.
            protected_ns: Protected namespace index (set flag automatically).
            instance_traits: Instance-side traits (fields, methods).
            static_traits: Static-side traits.

        Returns:
            Class index (same index in both instances and classes arrays).
        """
        # Auto-create constructor if not provided
        if constructor is None:
            constructor = self.method()
            self.method_body(constructor, code=bytes([
                OP_GETLOCAL_0, OP_PUSHSCOPE,
                OP_GETLOCAL_0, OP_CONSTRUCTSUPER, 0x00,  # 0 args
                OP_RETURNVOID,
            ]), max_stack=1, local_count=1,
                init_scope_depth=0, max_scope_depth=1)

        # Auto-create static init if not provided
        if static_init is None:
            static_init = self.method()
            self.method_body(static_init, code=bytes([OP_RETURNVOID]),
                             max_stack=0, local_count=1,
                             init_scope_depth=0, max_scope_depth=1)

        inst_flags = flags
        if protected_ns:
            inst_flags |= INSTANCE_PROTECTED_NS

        inst = InstanceInfo(
            name=name,
            super_name=super_name,
            flags=inst_flags,
            protectedNs=protected_ns,
            interfaces=interfaces or [],
            iinit=constructor,
            traits=instance_traits or [],
        )

        cls = AbcClassInfo(
            cinit=static_init,
            traits=static_traits or [],
        )

        idx = len(self._instances)
        self._instances.append(inst)
        self._classes.append(cls)
        return idx

    # ── Scripts ────────────────────────────────────────────────────────

    def script(
        self,
        init: int | None = None,
        traits: list[TraitInfo] | None = None,
    ) -> int:
        """Add a script entry point.

        Args:
            init: Method index for the script initializer. Auto-created if None.
            traits: Script-level traits (class definitions, etc.).

        Returns:
            Script index.
        """
        if init is None:
            init = self.method()
            self.method_body(init, code=bytes([OP_RETURNVOID]),
                             max_stack=0, local_count=1)

        si = ScriptInfo(init=init, traits=traits or [])
        idx = len(self._scripts)
        self._scripts.append(si)
        return idx

    # ── Bytecode assembly helpers ──────────────────────────────────────

    @staticmethod
    def asm(*parts: bytes) -> bytes:
        """Concatenate bytecode fragments into a single code block.

        Args:
            *parts: Bytecode fragments from op_*() methods.

        Returns:
            Combined bytecode bytes.
        """
        return b"".join(parts)

    # Simple opcodes (no operands)
    @staticmethod
    def op_nop() -> bytes: return bytes([OP_NOP])
    @staticmethod
    def op_label() -> bytes: return bytes([OP_LABEL])
    @staticmethod
    def op_throw() -> bytes: return bytes([OP_THROW])
    @staticmethod
    def op_getlocal_0() -> bytes: return bytes([OP_GETLOCAL_0])
    @staticmethod
    def op_getlocal_1() -> bytes: return bytes([OP_GETLOCAL_1])
    @staticmethod
    def op_getlocal_2() -> bytes: return bytes([OP_GETLOCAL_2])
    @staticmethod
    def op_getlocal_3() -> bytes: return bytes([OP_GETLOCAL_3])
    @staticmethod
    def op_setlocal_0() -> bytes: return bytes([OP_SETLOCAL_0])
    @staticmethod
    def op_setlocal_1() -> bytes: return bytes([OP_SETLOCAL_1])
    @staticmethod
    def op_setlocal_2() -> bytes: return bytes([OP_SETLOCAL_2])
    @staticmethod
    def op_setlocal_3() -> bytes: return bytes([OP_SETLOCAL_3])
    @staticmethod
    def op_pushscope() -> bytes: return bytes([OP_PUSHSCOPE])
    @staticmethod
    def op_returnvoid() -> bytes: return bytes([OP_RETURNVOID])
    @staticmethod
    def op_returnvalue() -> bytes: return bytes([OP_RETURNVALUE])
    @staticmethod
    def op_pop() -> bytes: return bytes([OP_POP])
    @staticmethod
    def op_dup() -> bytes: return bytes([OP_DUP])
    @staticmethod
    def op_swap() -> bytes: return bytes([OP_SWAP])
    @staticmethod
    def op_pushnull() -> bytes: return bytes([OP_PUSHNULL])
    @staticmethod
    def op_pushundefined() -> bytes: return bytes([OP_PUSHUNDEFINED])
    @staticmethod
    def op_pushtrue() -> bytes: return bytes([OP_PUSHTRUE])
    @staticmethod
    def op_pushfalse() -> bytes: return bytes([OP_PUSHFALSE])
    @staticmethod
    def op_convert_i() -> bytes: return bytes([OP_CONVERT_I])
    @staticmethod
    def op_convert_s() -> bytes: return bytes([OP_CONVERT_S])
    @staticmethod
    def op_convert_d() -> bytes: return bytes([OP_CONVERT_D])
    @staticmethod
    def op_coerce_a() -> bytes: return bytes([OP_COERCE_A])
    @staticmethod
    def op_coerce_s() -> bytes: return bytes([OP_COERCE_S])
    @staticmethod
    def op_add() -> bytes: return bytes([OP_ADD])
    @staticmethod
    def op_subtract() -> bytes: return bytes([OP_SUBTRACT])
    @staticmethod
    def op_multiply() -> bytes: return bytes([OP_MULTIPLY])
    @staticmethod
    def op_divide() -> bytes: return bytes([OP_DIVIDE])
    @staticmethod
    def op_equals() -> bytes: return bytes([OP_EQUALS])
    @staticmethod
    def op_strictequals() -> bytes: return bytes([OP_STRICTEQUALS])
    @staticmethod
    def op_lessthan() -> bytes: return bytes([OP_LESSTHAN])
    @staticmethod
    def op_greaterequals() -> bytes: return bytes([OP_GREATEREQUALS])
    @staticmethod
    def op_not() -> bytes: return bytes([OP_NOT])

    # Opcodes with u30 operand
    @staticmethod
    def op_getlocal(reg: int) -> bytes:
        return bytes([OP_GETLOCAL]) + write_u30(reg)
    @staticmethod
    def op_setlocal(reg: int) -> bytes:
        return bytes([OP_SETLOCAL]) + write_u30(reg)
    @staticmethod
    def op_pushbyte(val: int) -> bytes:
        return bytes([OP_PUSHBYTE, val & 0xFF])
    @staticmethod
    def op_pushshort(val: int) -> bytes:
        return bytes([OP_PUSHSHORT]) + write_u30(val)
    @staticmethod
    def op_pushstring(index: int) -> bytes:
        return bytes([OP_PUSHSTRING]) + write_u30(index)
    @staticmethod
    def op_pushint(index: int) -> bytes:
        return bytes([OP_PUSHINT]) + write_u30(index)
    @staticmethod
    def op_pushuint(index: int) -> bytes:
        return bytes([OP_PUSHUINT]) + write_u30(index)
    @staticmethod
    def op_pushdouble(index: int) -> bytes:
        return bytes([OP_PUSHDOUBLE]) + write_u30(index)
    @staticmethod
    def op_getproperty(index: int) -> bytes:
        return bytes([OP_GETPROPERTY]) + write_u30(index)
    @staticmethod
    def op_setproperty(index: int) -> bytes:
        return bytes([OP_SETPROPERTY]) + write_u30(index)
    @staticmethod
    def op_initproperty(index: int) -> bytes:
        return bytes([OP_INITPROPERTY]) + write_u30(index)
    @staticmethod
    def op_getlex(index: int) -> bytes:
        return bytes([OP_GETLEX]) + write_u30(index)
    @staticmethod
    def op_findpropstrict(index: int) -> bytes:
        return bytes([OP_FINDPROPSTRICT]) + write_u30(index)
    @staticmethod
    def op_coerce(index: int) -> bytes:
        return bytes([OP_COERCE]) + write_u30(index)
    @staticmethod
    def op_constructsuper(arg_count: int) -> bytes:
        return bytes([OP_CONSTRUCTSUPER]) + write_u30(arg_count)
    @staticmethod
    def op_newarray(arg_count: int) -> bytes:
        return bytes([OP_NEWARRAY]) + write_u30(arg_count)
    @staticmethod
    def op_newclass(class_index: int) -> bytes:
        return bytes([OP_NEWCLASS]) + write_u30(class_index)
    @staticmethod
    def op_newfunction(method_index: int) -> bytes:
        return bytes([OP_NEWFUNCTION]) + write_u30(method_index)
    @staticmethod
    def op_call(arg_count: int) -> bytes:
        return bytes([OP_CALL]) + write_u30(arg_count)
    @staticmethod
    def op_construct(arg_count: int) -> bytes:
        return bytes([OP_CONSTRUCT]) + write_u30(arg_count)
    @staticmethod
    def op_debugfile(index: int) -> bytes:
        return bytes([OP_DEBUGFILE]) + write_u30(index)
    @staticmethod
    def op_debugline(line: int) -> bytes:
        return bytes([OP_DEBUGLINE]) + write_u30(line)

    # Opcodes with u30 u30 operands
    @staticmethod
    def op_callproperty(index: int, arg_count: int) -> bytes:
        return bytes([OP_CALLPROPERTY]) + write_u30(index) + write_u30(arg_count)
    @staticmethod
    def op_callpropvoid(index: int, arg_count: int) -> bytes:
        return bytes([OP_CALLPROPVOID]) + write_u30(index) + write_u30(arg_count)
    @staticmethod
    def op_constructprop(index: int, arg_count: int) -> bytes:
        return bytes([OP_CONSTRUCTPROP]) + write_u30(index) + write_u30(arg_count)

    # Branch opcodes (s24 operand)
    @staticmethod
    def op_jump(offset: int) -> bytes:
        return bytes([OP_JUMP]) + _encode_s24(offset)
    @staticmethod
    def op_iftrue(offset: int) -> bytes:
        return bytes([OP_IFTRUE]) + _encode_s24(offset)
    @staticmethod
    def op_iffalse(offset: int) -> bytes:
        return bytes([OP_IFFALSE]) + _encode_s24(offset)

    # ── Convenience ────────────────────────────────────────────────────

    def simple_class(
        self,
        name: str,
        package: str = "",
        super_name: str | None = "Object",
        fields: list[tuple[str, str]] | None = None,
        is_interface: bool = False,
    ) -> int:
        """Define a class with minimal boilerplate.

        Creates namespaces, multinames, and traits automatically from
        simple string arguments. For full control, use ``define_class()``.

        Args:
            name: Class name string.
            package: Package name string (empty for default package).
            super_name: Superclass name string, or None for no super.
            fields: List of (field_name, type_name) tuples for instance fields.
            is_interface: Whether this is an interface definition.

        Returns:
            Class index.
        """
        ns = self.package_namespace(package)
        pub = self.package_namespace("")
        priv = self.private_namespace()
        cls_mn = self.qname(ns, name)

        super_mn = 0
        if super_name:
            super_mn = self.qname(pub, super_name)

        instance_traits = []
        if fields:
            for i, (fname, ftype) in enumerate(fields):
                type_mn = self.qname(pub, ftype) if ftype else 0
                field_mn = self.qname(priv, fname)
                instance_traits.append(
                    self.trait_slot(field_mn, type_mn=type_mn,
                                   slot_id=i + 1))

        flags = INSTANCE_INTERFACE if is_interface else INSTANCE_SEALED

        return self.define_class(
            name=cls_mn, super_name=super_mn, flags=flags,
            instance_traits=instance_traits,
        )

    # ── Build ──────────────────────────────────────────────────────────

    def build(self) -> AbcFile:
        """Build the final AbcFile from all added components.

        If no scripts have been added, a default empty script is created.

        Returns:
            Complete AbcFile ready for serialization.
        """
        # Ensure at least one script exists
        if not self._scripts:
            self.script()

        abc = AbcFile()
        abc.int_pool = list(self._int_pool)
        abc.uint_pool = list(self._uint_pool)
        abc._int_pool_raw = [b""] * len(self._int_pool)
        abc._uint_pool_raw = [b""] * len(self._uint_pool)
        abc.double_pool = list(self._double_pool)
        abc.string_pool = list(self._string_pool)
        abc.namespace_pool = list(self._namespace_pool)
        abc.ns_set_pool = list(self._ns_set_pool)
        abc.multiname_pool = list(self._multiname_pool)
        abc.methods = list(self._methods)
        abc.metadata = list(self._metadata)
        abc.instances = list(self._instances)
        abc.classes = list(self._classes)
        abc.scripts = list(self._scripts)
        abc.method_bodies = list(self._method_bodies)
        return abc
