"""
Resolved member (field and method) information.

Provides ``FieldInfo`` and ``MethodInfoResolved`` which resolve raw ABC
trait data into usable descriptors with string names and type names.

Also provides ``resolve_trait()`` to parse the raw bytes stored in
``TraitInfo.data`` into structured field/method details.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..abc.types import AbcFile, TraitInfo, MethodBodyInfo
from ..abc.parser import read_u30, read_u8
from ..abc.constants import (
    TRAIT_Slot, TRAIT_Const, TRAIT_Method, TRAIT_Getter, TRAIT_Setter,
    TRAIT_Class, TRAIT_Function,
    CONSTANT_QName, CONSTANT_QNameA,
    CONSTANT_RTQName, CONSTANT_RTQNameA,
    CONSTANT_Multiname, CONSTANT_MultinameA,
    CONSTANT_TypeName,
    ATTR_Metadata,
)


def resolve_multiname(abc: AbcFile, index: int) -> str:
    """Resolve a multiname pool index to a human-readable name string.

    Handles parameterized types (TypeName) like ``Vector.<int>`` by
    recursively resolving the base type and type parameters.

    Args:
        abc: The AbcFile containing the constant pools.
        index: Index into the multiname pool.

    Returns:
        Resolved name string, or ``"*"`` for index 0 (any type).
    """
    if index == 0 or index >= len(abc.multiname_pool):
        return "*"
    mn = abc.multiname_pool[index]
    if mn.kind in (CONSTANT_QName, CONSTANT_QNameA):
        if 0 < mn.name < len(abc.string_pool):
            return abc.string_pool[mn.name]
    elif mn.kind in (CONSTANT_RTQName, CONSTANT_RTQNameA):
        if 0 < mn.name < len(abc.string_pool):
            return abc.string_pool[mn.name]
    elif mn.kind in (CONSTANT_Multiname, CONSTANT_MultinameA):
        if 0 < mn.name < len(abc.string_pool):
            return abc.string_pool[mn.name]
    elif mn.kind == CONSTANT_TypeName:
        # TypeName: mn.ns = base type multiname index, mn.name = param count
        # mn.data = serialized parameter multiname indices (u30 encoded)
        base = resolve_multiname(abc, mn.ns)
        param_count = mn.name
        if param_count > 0 and mn.data:
            params = []
            offset = 0
            for _ in range(param_count):
                param_idx, offset = read_u30(mn.data, offset)
                params.append(resolve_multiname(abc, param_idx))
            return f"{base}.<{', '.join(params)}>"
        return base
    return f"multiname[{index}]"


def resolve_multiname_full(abc: AbcFile, index: int) -> tuple[str, str]:
    """Resolve a multiname to (package, name) tuple.

    Args:
        abc: The AbcFile containing the constant pools.
        index: Index into the multiname pool.

    Returns:
        Tuple of (package_string, name_string).
    """
    if index == 0 or index >= len(abc.multiname_pool):
        return ("", "*")
    mn = abc.multiname_pool[index]
    name = "*"
    package = ""
    if mn.kind in (CONSTANT_QName, CONSTANT_QNameA):
        if 0 < mn.name < len(abc.string_pool):
            name = abc.string_pool[mn.name]
        if 0 < mn.ns < len(abc.namespace_pool):
            ns = abc.namespace_pool[mn.ns]
            if 0 < ns.name < len(abc.string_pool):
                package = abc.string_pool[ns.name]
    elif mn.kind in (CONSTANT_RTQName, CONSTANT_RTQNameA,
                     CONSTANT_Multiname, CONSTANT_MultinameA):
        if 0 < mn.name < len(abc.string_pool):
            name = abc.string_pool[mn.name]
    elif mn.kind == CONSTANT_TypeName:
        # Delegate to resolve_multiname for the full "Base.<T>" string;
        # derive package from the base type multiname.
        name = resolve_multiname(abc, index)
        base_pkg, _ = resolve_multiname_full(abc, mn.ns)
        package = base_pkg
    return (package, name)


@dataclass(slots=True)
class FieldInfo:
    """A resolved field (variable or constant) on a class.

    Attributes:
        name: Field name string.
        type_name: Type name string (``"*"`` if untyped).
        is_static: Whether this is a static field.
        is_const: True for TRAIT_Const, False for TRAIT_Slot.
        slot_id: Slot index in the object's slot array.
        default_value: Default value if specified, else None.
        trait_index: Index of the original trait in the trait list.
        multiname_index: Original multiname index for the field name.
        type_multiname_index: Original multiname index for the field type.
    """
    name: str
    type_name: str
    is_static: bool = False
    is_const: bool = False
    slot_id: int = 0
    default_value: object = None
    trait_index: int = 0
    multiname_index: int = 0
    type_multiname_index: int = 0
    _owner_class: object = field(default=None, repr=False, compare=False)

    @property
    def readers(self) -> list[str]:
        """Methods that read this field.

        Returns:
            Sorted list of method names.
        """
        if self._owner_class is None or self._owner_class._workspace is None:
            return []
        return self._owner_class._workspace.field_readers(
            self._owner_class.qualified_name, self.name)

    @property
    def writers(self) -> list[str]:
        """Methods that write to this field.

        Returns:
            Sorted list of method names.
        """
        if self._owner_class is None or self._owner_class._workspace is None:
            return []
        return self._owner_class._workspace.field_writers(
            self._owner_class.qualified_name, self.name)


@dataclass(slots=True)
class MethodInfoResolved:
    """A resolved method, getter, or setter on a class.

    Attributes:
        name: Method name string.
        param_names: Parameter name strings (from debug info, may be empty).
        param_types: Parameter type name strings.
        return_type: Return type name string.
        is_static: Whether this is a static method.
        is_getter: True if this is a getter property.
        is_setter: True if this is a setter property.
        method_index: Index into AbcFile.methods.
        body_index: Index into AbcFile.method_bodies, or -1 if no body.
        disp_id: Dispatch ID.
        trait_index: Index of the original trait in the trait list.
        multiname_index: Original multiname index for the method name.
    """
    name: str
    param_names: list[str] = field(default_factory=list)
    param_types: list[str] = field(default_factory=list)
    return_type: str = "*"
    is_static: bool = False
    is_getter: bool = False
    is_setter: bool = False
    method_index: int = 0
    body_index: int = -1
    disp_id: int = 0
    trait_index: int = 0
    multiname_index: int = 0
    _owner_class: object = field(default=None, repr=False, compare=False)

    @property
    def fields_read(self) -> list[str]:
        """Fields read by this method.

        Returns:
            Sorted list of field names.
        """
        if self._owner_class is None or self._owner_class._workspace is None:
            return []
        return self._owner_class._workspace.fields_read_by(
            self._owner_class.qualified_name, self.name)

    @property
    def fields_written(self) -> list[str]:
        """Fields written by this method.

        Returns:
            Sorted list of field names.
        """
        if self._owner_class is None or self._owner_class._workspace is None:
            return []
        return self._owner_class._workspace.fields_written_by(
            self._owner_class.qualified_name, self.name)


def parse_slot_trait(data: bytes) -> tuple[int, int, int, int | None]:
    """Parse a TRAIT_Slot or TRAIT_Const trait's raw data.

    Args:
        data: The raw TraitInfo.data bytes.

    Returns:
        Tuple of (name_mn, slot_id, type_mn, default_value_index).
        default_value_index is None if no default.
    """
    off = 0
    name_mn, off = read_u30(data, off)
    _kind_byte, off = read_u8(data, off)
    slot_id, off = read_u30(data, off)
    type_mn, off = read_u30(data, off)
    vindex, off = read_u30(data, off)
    return (name_mn, slot_id, type_mn, vindex if vindex else None)


def parse_method_trait(data: bytes) -> tuple[int, int, int]:
    """Parse a TRAIT_Method, TRAIT_Getter, or TRAIT_Setter trait's raw data.

    Args:
        data: The raw TraitInfo.data bytes.

    Returns:
        Tuple of (name_mn, disp_id, method_index).
    """
    off = 0
    name_mn, off = read_u30(data, off)
    _kind_byte, off = read_u8(data, off)
    disp_id, off = read_u30(data, off)
    method_idx, off = read_u30(data, off)
    return (name_mn, disp_id, method_idx)


def parse_class_trait(data: bytes) -> tuple[int, int, int]:
    """Parse a TRAIT_Class trait's raw data.

    Returns:
        Tuple of (name_mn, slot_id, class_index).
    """
    off = 0
    name_mn, off = read_u30(data, off)
    _kind_byte, off = read_u8(data, off)
    slot_id, off = read_u30(data, off)
    class_idx, off = read_u30(data, off)
    return (name_mn, slot_id, class_idx)


def resolve_traits(
    abc: AbcFile,
    traits: list[TraitInfo],
    is_static: bool = False,
    method_body_map: dict[int, int] | None = None,
) -> tuple[list[FieldInfo], list[MethodInfoResolved]]:
    """Resolve a list of raw traits into FieldInfo and MethodInfoResolved.

    Args:
        abc: The AbcFile for constant pool lookups.
        traits: List of raw TraitInfo objects.
        is_static: Whether these are static traits.
        method_body_map: Optional mapping of method_index → body_index
            in AbcFile.method_bodies. If None, body_index won't be set.

    Returns:
        Tuple of (fields, methods).
    """
    fields: list[FieldInfo] = []
    methods: list[MethodInfoResolved] = []

    for i, trait in enumerate(traits):
        if trait.kind in (TRAIT_Slot, TRAIT_Const):
            name_mn, slot_id, type_mn, default_val = parse_slot_trait(trait.data)
            fi = FieldInfo(
                name=resolve_multiname(abc, name_mn),
                type_name=resolve_multiname(abc, type_mn),
                is_static=is_static,
                is_const=(trait.kind == TRAIT_Const),
                slot_id=slot_id,
                default_value=default_val,
                trait_index=i,
                multiname_index=name_mn,
                type_multiname_index=type_mn,
            )
            fields.append(fi)

        elif trait.kind in (TRAIT_Method, TRAIT_Getter, TRAIT_Setter):
            name_mn, disp_id, method_idx = parse_method_trait(trait.data)

            # Resolve method signature
            param_types: list[str] = []
            param_names: list[str] = []
            return_type = "*"
            if 0 <= method_idx < len(abc.methods):
                mi = abc.methods[method_idx]
                return_type = resolve_multiname(abc, mi.return_type)
                param_types = [
                    resolve_multiname(abc, pt) for pt in mi.param_types]
                param_names = [
                    abc.string_pool[pn] if 0 < pn < len(abc.string_pool) else ""
                    for pn in mi.param_names
                ]

            body_idx = -1
            if method_body_map and method_idx in method_body_map:
                body_idx = method_body_map[method_idx]

            mri = MethodInfoResolved(
                name=resolve_multiname(abc, name_mn),
                param_names=param_names,
                param_types=param_types,
                return_type=return_type,
                is_static=is_static,
                is_getter=(trait.kind == TRAIT_Getter),
                is_setter=(trait.kind == TRAIT_Setter),
                method_index=method_idx,
                body_index=body_idx,
                disp_id=disp_id,
                trait_index=i,
                multiname_index=name_mn,
            )
            methods.append(mri)

    return fields, methods


def build_method_body_map(abc: AbcFile) -> dict[int, int]:
    """Build a mapping from method_index → index in AbcFile.method_bodies.

    Args:
        abc: The AbcFile to index.

    Returns:
        Dict mapping method indices to their body indices.
    """
    return {mb.method: i for i, mb in enumerate(abc.method_bodies)}
