"""
Resolved class information.

``ClassInfo`` wraps an ABC InstanceInfo + ClassInfo pair with all names
resolved from the constant pool. Consumers get direct string access to
class names, superclass names, interface names, and fully resolved
field/method lists.

Public accessors
----------------
- ``workspace``: the :class:`~flashkit.workspace.workspace.Workspace` that
  owns this class.
- ``abc``: the :class:`~flashkit.abc.types.AbcFile` that defines this class.

The corresponding dataclass fields ``_workspace`` and ``_abc`` are internal;
they are written by ``build_class_info`` and should not be read directly by
consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..abc.types import AbcFile
from ..abc.constants import INSTANCE_Interface
from .member_info import (
    FieldInfo, MethodInfoResolved,
    resolve_multiname, resolve_multiname_full, resolve_traits,
    build_method_body_map,
)

if TYPE_CHECKING:
    from ..workspace.workspace import Workspace
    from ..analysis.references import Reference


@dataclass(slots=True)
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
    _abc: AbcFile | None = field(default=None, repr=False, compare=False)
    _workspace: Workspace | None = field(default=None, repr=False, compare=False)

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

    def _require_workspace(self) -> Workspace:
        """Get the workspace or raise an error."""
        if self._workspace is None:
            raise RuntimeError(
                "This ClassInfo is not attached to a Workspace. "
                "Load the SWF via Workspace.load_swf() to use "
                "analysis properties.")
        return self._workspace

    @property
    def strings(self) -> list[str]:
        """All string constants referenced by this class.

        Returns:
            Sorted list of unique string values.
        """
        ws = self._require_workspace()
        return ws.strings_in_class(self.qualified_name)

    @property
    def references_to(self) -> list[Reference]:
        """All incoming references to this class.

        Returns:
            List of Reference objects pointing to this class.
        """
        ws = self._require_workspace()
        return ws.references_to(self.name)

    @property
    def references_from(self) -> list[Reference]:
        """All outgoing references from this class.

        Returns:
            List of Reference objects originating from this class.
        """
        ws = self._require_workspace()
        return ws.references_from(self.qualified_name)

    @property
    def subclasses(self) -> list[str]:
        """Direct subclasses of this class.

        Returns:
            List of subclass qualified names.
        """
        ws = self._require_workspace()
        return ws.get_subclasses(self.qualified_name)

    @property
    def ancestors(self) -> list[str]:
        """Full ancestor chain (parent → root).

        Returns:
            List of ancestor qualified names.
        """
        ws = self._require_workspace()
        return ws.get_ancestors(self.qualified_name)

    @property
    def field_access_summary(self) -> dict[str, dict[str, list[str]]]:
        """Summary of all field accesses in this class.

        Returns:
            Dict of field_name → {readers: [...], writers: [...]}.
        """
        ws = self._require_workspace()
        return ws.field_access_summary(self.qualified_name)

    def constructor_assignments(self) -> list[str]:
        """Fields assigned in the constructor, in bytecode order.

        Returns:
            List of field names in assignment order.
        """
        ws = self._require_workspace()
        return ws.constructor_assignments(self.qualified_name)

    @property
    def abc(self) -> AbcFile:
        """The AbcFile that defines this class.

        Raises:
            RuntimeError: if the ClassInfo was built without an AbcFile
                (e.g. constructed manually rather than via build_class_info).
        """
        if self._abc is None:
            raise RuntimeError(
                "This ClassInfo has no AbcFile attached. "
                "Build it via build_class_info() or Workspace.load_swf().")
        return self._abc

    @property
    def workspace(self) -> Workspace:
        """The Workspace that owns this class.

        Raises:
            RuntimeError: if the ClassInfo was built standalone
                (e.g. via build_class_info without attaching to a Workspace).
        """
        return self._require_workspace()

    @property
    def constructor_params(self) -> list[str]:
        """Resolved type names of the constructor's parameters.

        Returns an empty list for a zero-arg constructor.
        """
        if self._abc is None:
            return []
        if self.constructor_index >= len(self._abc.methods):
            return []
        mi = self._abc.methods[self.constructor_index]
        return [resolve_multiname(self._abc, pt) for pt in mi.param_types]


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

    ci = ClassInfo(
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
    # Wire up backrefs so fields/methods can reach the workspace/abc
    ci._abc = abc
    for f in ci.fields + ci.static_fields:
        f._owner_class = ci
    for m in ci.methods + ci.static_methods:
        m._owner_class = ci
    return ci


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
