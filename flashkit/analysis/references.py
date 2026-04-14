"""
Cross-reference index for ABC elements.

Builds indexes that answer "where is X used?" questions by scanning
class traits (field types, method signatures) and method body opcodes.

Usage::

    from flashkit.workspace import Workspace
    from flashkit.analysis.references import ReferenceIndex

    ws = Workspace()
    ws.load_swf("application.swf")
    refs = ReferenceIndex.from_workspace(ws)

    users = refs.field_type_users("int")
    creators = refs.instantiators("Point")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..workspace.workspace import Workspace

from ..abc.types import AbcFile
from ..abc.disasm import scan_relevant_opcodes
from ..abc.constants import (
    OP_pushstring, OP_constructprop, OP_callproperty, OP_callpropvoid,
    OP_getlex, OP_coerce, OP_newclass,
)
from ..info.member_info import resolve_multiname, build_method_body_map

_REF_SCAN_OPS = frozenset({
    OP_constructprop, OP_callproperty, OP_callpropvoid,
    OP_getlex, OP_coerce, OP_pushstring,
})

_REF_KIND_MAP = {
    OP_constructprop: "instantiation",
    OP_callproperty: "call",
    OP_callpropvoid: "call",
    OP_getlex: "class_ref",
    OP_coerce: "coerce",
}
from ..info.class_info import ClassInfo


@dataclass(slots=True)
class Reference:
    """A single cross-reference entry.

    Attributes:
        source_class: Qualified name of the class containing this reference.
        source_member: Member name (method or field) where this reference occurs.
        target: The referenced name (type name, class name, or string).
        ref_kind: Category: ``"field_type"``, ``"param_type"``, ``"return_type"``,
                  ``"instantiation"``, ``"call"``, ``"string_use"``, ``"coerce"``,
                  ``"class_ref"``.
        method_index: Method index if this reference is from a method body, else -1.
        offset: Bytecode offset if from a method body, else -1.
    """
    source_class: str
    source_member: str
    target: str
    ref_kind: str
    method_index: int = -1
    offset: int = -1


@dataclass(slots=True)
class ReferenceIndex:
    """Cross-reference index over all classes and method bodies.

    Provides efficient lookup for "where is X used?" queries.

    Attributes:
        refs: All reference entries.
        by_target: Map of target name → list of references to it.
        by_source: Map of source class name → list of references from it.
    """
    refs: list[Reference] = field(default_factory=list)
    by_target: dict[str, list[Reference]] = field(
        default_factory=lambda: defaultdict(list))
    by_source: dict[str, list[Reference]] = field(
        default_factory=lambda: defaultdict(list))

    def _add(self, ref: Reference) -> None:
        """Add a reference to all indexes."""
        self.refs.append(ref)
        self.by_target[ref.target].append(ref)
        self.by_source[ref.source_class].append(ref)

    @classmethod
    def from_workspace(cls, workspace: Workspace) -> ReferenceIndex:
        """Build a ReferenceIndex from a Workspace.

        Scans all class traits and method bodies.

        Args:
            workspace: A Workspace instance.

        Returns:
            Populated ReferenceIndex.
        """
        ws = workspace

        index = cls()

        for ci in ws.classes:
            index._index_class_traits(ci)

        for abc in ws.abc_blocks:
            index._index_method_bodies(abc, ws.classes)

        return index

    @classmethod
    def from_classes_and_abc(cls, classes: list[ClassInfo],
                             abc_blocks: list[AbcFile]) -> ReferenceIndex:
        """Build a ReferenceIndex from class and ABC lists directly.

        Args:
            classes: All resolved ClassInfo objects.
            abc_blocks: All AbcFile objects.

        Returns:
            Populated ReferenceIndex.
        """
        index = cls()
        for ci in classes:
            index._index_class_traits(ci)
        for abc in abc_blocks:
            index._index_method_bodies(abc, classes)
        return index

    def _index_class_traits(self, ci: ClassInfo) -> None:
        """Index field types, method param types, and return types from a class."""
        qname = ci.qualified_name

        # Field types (instance + static)
        for f in ci.all_fields:
            if f.type_name and f.type_name != "*":
                self._add(Reference(
                    source_class=qname,
                    source_member=f.name,
                    target=f.type_name,
                    ref_kind="field_type",
                ))

        # Method signatures (instance + static)
        for m in ci.all_methods:
            # Return type
            if m.return_type and m.return_type != "*":
                self._add(Reference(
                    source_class=qname,
                    source_member=m.name,
                    target=m.return_type,
                    ref_kind="return_type",
                    method_index=m.method_index,
                ))
            # Parameter types
            for pt in m.param_types:
                if pt and pt != "*":
                    self._add(Reference(
                        source_class=qname,
                        source_member=m.name,
                        target=pt,
                        ref_kind="param_type",
                        method_index=m.method_index,
                    ))

        # Superclass reference
        if ci.super_name and ci.super_name != "*" and ci.super_name != "Object":
            super_qualified = (
                f"{ci.super_package}.{ci.super_name}"
                if ci.super_package else ci.super_name
            )
            self._add(Reference(
                source_class=qname,
                source_member="<extends>",
                target=super_qualified,
                ref_kind="extends",
            ))

        # Interface references
        for iface in ci.interfaces:
            self._add(Reference(
                source_class=qname,
                source_member="<implements>",
                target=iface,
                ref_kind="implements",
            ))

    def _index_method_bodies(self, abc: AbcFile,
                             classes: list[ClassInfo]) -> None:
        """Index references from method body opcodes."""
        method_owner_map = _build_method_owner_map(abc, classes)
        method_name_map = _build_method_name_map(abc, classes)
        string_pool = abc.string_pool
        string_pool_len = len(string_pool)

        for body in abc.method_bodies:
            owner_class = method_owner_map.get(body.method, "")
            method_name = method_name_map.get(
                body.method, f"method_{body.method}")

            try:
                hits = scan_relevant_opcodes(body.code, _REF_SCAN_OPS)
            except Exception:
                continue

            for offset, op, operand in hits:
                if op == OP_pushstring:
                    if 0 < operand < string_pool_len:
                        self._add(Reference(
                            source_class=owner_class,
                            source_member=method_name,
                            target=string_pool[operand],
                            ref_kind="string_use",
                            method_index=body.method,
                            offset=offset,
                        ))
                elif op in _REF_KIND_MAP:
                    target = resolve_multiname(abc, operand)
                    if target != "*" and not target.startswith("multiname["):
                        self._add(Reference(
                            source_class=owner_class,
                            source_member=method_name,
                            target=target,
                            ref_kind=_REF_KIND_MAP[op],
                            method_index=body.method,
                            offset=offset,
                        ))

    def field_type_users(self, type_name: str) -> list[Reference]:
        """Find all fields of a given type.

        Args:
            type_name: The type name to search for.

        Returns:
            List of references where a field has this type.
        """
        return [r for r in self.by_target.get(type_name, [])
                if r.ref_kind == "field_type"]

    def method_param_users(self, type_name: str) -> list[Reference]:
        """Find all methods that take a parameter of a given type.

        Args:
            type_name: The type name to search for.

        Returns:
            List of references where a method parameter has this type.
        """
        return [r for r in self.by_target.get(type_name, [])
                if r.ref_kind == "param_type"]

    def method_return_users(self, type_name: str) -> list[Reference]:
        """Find all methods that return a given type.

        Args:
            type_name: The type name to search for.

        Returns:
            List of references where a method returns this type.
        """
        return [r for r in self.by_target.get(type_name, [])
                if r.ref_kind == "return_type"]

    def instantiators(self, class_name: str) -> list[Reference]:
        """Find all places that construct instances of a class.

        Args:
            class_name: The class being instantiated.

        Returns:
            List of instantiation references.
        """
        return [r for r in self.by_target.get(class_name, [])
                if r.ref_kind == "instantiation"]

    def string_users(self, string: str) -> list[Reference]:
        """Find all places that push a specific string constant.

        Args:
            string: The exact string value.

        Returns:
            List of string usage references.
        """
        return [r for r in self.by_target.get(string, [])
                if r.ref_kind == "string_use"]

    def references_from(self, class_name: str) -> list[Reference]:
        """Get all outgoing references from a class.

        Args:
            class_name: The source class qualified name.

        Returns:
            All references originating from this class.
        """
        return self.by_source.get(class_name, [])

    def references_to(self, target: str) -> list[Reference]:
        """Get all incoming references to a target.

        Args:
            target: The target name (type, class, method, or string).

        Returns:
            All references pointing to this target.
        """
        return self.by_target.get(target, [])

    @property
    def total_refs(self) -> int:
        return len(self.refs)


def _build_method_owner_map(abc: AbcFile,
                            classes: list[ClassInfo]) -> dict[int, str]:
    """Map method_index → owning class qualified name."""
    owner: dict[int, str] = {}
    for ci in classes:
        owner[ci.constructor_index] = ci.qualified_name
        owner[ci.static_init_index] = ci.qualified_name
        for m in ci.all_methods:
            owner[m.method_index] = ci.qualified_name
    return owner


def _build_method_name_map(abc: AbcFile,
                           classes: list[ClassInfo]) -> dict[int, str]:
    """Map method_index → readable method name."""
    name_map: dict[int, str] = {}
    for ci in classes:
        name_map[ci.constructor_index] = "<init>"
        name_map[ci.static_init_index] = "<cinit>"
        for m in ci.all_methods:
            name_map[m.method_index] = m.name
    return name_map
