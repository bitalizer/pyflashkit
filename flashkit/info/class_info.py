"""
Resolved class information.

``ClassInfo`` wraps an ABC InstanceInfo + ClassInfo pair with all names
resolved from the constant pool. Consumers get direct string access to
class names, superclass names, interface names, and fully resolved
field/method lists.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..abc.types import AbcFile
from ..abc.constants import INSTANCE_Interface
from .member_info import (
    FieldInfo, MethodInfoResolved,
    resolve_multiname, resolve_multiname_full, resolve_traits,
    build_method_body_map,
)


@dataclass
class ClassInfo:
    """A fully resolved class definition.

    All names are resolved from the ABC constant pool into strings.
    Fields and methods are parsed from raw trait data into structured
    ``FieldInfo`` and ``MethodInfoResolved`` objects.

    Attributes:
        name: Class name string.
        package: Package/namespace string (empty for default package).
        qualified_name: Full ``package.name`` string.
        super_name: Superclass name (``"Object"`` for root, ``"*"`` if none).
        super_package: Superclass package string.
        interfaces: List of interface name strings.
        is_interface: Whether this class is an interface.
        is_sealed: Whether this class is sealed (no dynamic properties).
        is_final: Whether this class is final (cannot be subclassed).
        fields: Instance fields (FieldInfo list).
        methods: Instance methods, getters, setters (MethodInfoResolved list).
        static_fields: Static fields (FieldInfo list).
        static_methods: Static methods (MethodInfoResolved list).
        constructor_index: Method index for the instance initializer.
        static_init_index: Method index for the static initializer.
        instance_index: Index in AbcFile.instances (and AbcFile.classes).
        multiname_index: Original multiname index for the class name.
        super_multiname_index: Original multiname index for the superclass.
        interface_multiname_indices: Original multiname indices for interfaces.
    """
    name: str = ""
    package: str = ""
    qualified_name: str = ""
    super_name: str = "*"
    super_package: str = ""
    interfaces: list[str] = field(default_factory=list)
    is_interface: bool = False
    is_sealed: bool = False
    is_final: bool = False
    fields: list[FieldInfo] = field(default_factory=list)
    methods: list[MethodInfoResolved] = field(default_factory=list)
    static_fields: list[FieldInfo] = field(default_factory=list)
    static_methods: list[MethodInfoResolved] = field(default_factory=list)
    constructor_index: int = 0
    static_init_index: int = 0
    instance_index: int = 0
    multiname_index: int = 0
    super_multiname_index: int = 0
    interface_multiname_indices: list[int] = field(default_factory=list)

    @property
    def all_fields(self) -> list[FieldInfo]:
        """All fields (instance + static)."""
        return self.fields + self.static_fields

    @property
    def all_methods(self) -> list[MethodInfoResolved]:
        """All methods (instance + static)."""
        return self.methods + self.static_methods

    def get_field(self, name: str) -> FieldInfo | None:
        """Find a field by name (searches instance then static)."""
        for f in self.fields:
            if f.name == name:
                return f
        for f in self.static_fields:
            if f.name == name:
                return f
        return None

    def get_method(self, name: str) -> MethodInfoResolved | None:
        """Find a method by name (searches instance then static)."""
        for m in self.methods:
            if m.name == name:
                return m
        for m in self.static_methods:
            if m.name == name:
                return m
        return None


def build_class_info(abc: AbcFile, index: int,
                     method_body_map: dict[int, int] | None = None) -> ClassInfo:
    """Build a ClassInfo from an AbcFile instance/class pair.

    Args:
        abc: The AbcFile containing the class.
        index: Index into abc.instances and abc.classes.
        method_body_map: Optional pre-built method→body index map.
            If None, one will be built automatically.

    Returns:
        Fully resolved ClassInfo.
    """
    if method_body_map is None:
        method_body_map = build_method_body_map(abc)

    inst = abc.instances[index]
    cls = abc.classes[index]

    # Resolve class name
    package, name = resolve_multiname_full(abc, inst.name)
    qualified = f"{package}.{name}" if package else name

    # Resolve superclass
    super_package, super_name = resolve_multiname_full(abc, inst.super_name)

    # Resolve interfaces
    iface_names = [resolve_multiname(abc, i) for i in inst.interfaces]

    # Resolve instance traits (fields + methods)
    inst_fields, inst_methods = resolve_traits(
        abc, inst.traits, is_static=False, method_body_map=method_body_map)

    # Resolve static traits (static fields + static methods)
    static_fields, static_methods = resolve_traits(
        abc, cls.traits, is_static=True, method_body_map=method_body_map)

    return ClassInfo(
        name=name,
        package=package,
        qualified_name=qualified,
        super_name=super_name,
        super_package=super_package,
        interfaces=iface_names,
        is_interface=bool(inst.flags & INSTANCE_Interface),
        is_sealed=bool(inst.flags & 0x01),
        is_final=bool(inst.flags & 0x02),
        fields=inst_fields,
        methods=inst_methods,
        static_fields=static_fields,
        static_methods=static_methods,
        constructor_index=inst.iinit,
        static_init_index=cls.cinit,
        instance_index=index,
        multiname_index=inst.name,
        super_multiname_index=inst.super_name,
        interface_multiname_indices=list(inst.interfaces),
    )


def build_all_classes(abc: AbcFile) -> list[ClassInfo]:
    """Build ClassInfo objects for all classes in an AbcFile.

    Args:
        abc: The AbcFile to process.

    Returns:
        List of ClassInfo, one per class, in the same order as abc.instances.
    """
    method_body_map = build_method_body_map(abc)
    return [
        build_class_info(abc, i, method_body_map)
        for i in range(len(abc.instances))
    ]
