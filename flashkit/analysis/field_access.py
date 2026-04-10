"""
Field access analysis from method body bytecode.

Tracks which methods read (``OP_getproperty``) and write
(``OP_setproperty``, ``OP_initproperty``) which fields. Provides
per-field and per-method views, plus constructor-specific queries.

Usage::

    from flashkit.workspace import Workspace
    from flashkit.analysis.field_access import FieldAccessIndex

    ws = Workspace()
    ws.load_swf("application.swf")
    idx = FieldAccessIndex.from_workspace(ws)

    writers = idx.writers_of("Entity", "_-a3B")
    reads = idx.fields_read_by("Entity", "update")
    ctor_fields = idx.constructor_assignments("Entity")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict

from ..abc.types import AbcFile
from ..abc.disasm import scan_relevant_opcodes
from ..abc.constants import OP_getproperty, OP_setproperty, OP_initproperty

_FIELD_SCAN_OPS = frozenset({OP_getproperty, OP_setproperty, OP_initproperty})

_FIELD_ACCESS_TYPE = {
    OP_getproperty: "read",
    OP_setproperty: "write",
    OP_initproperty: "init",
}
from ..info.member_info import resolve_multiname
from ..info.class_info import ClassInfo


@dataclass(slots=True)
class FieldAccess:
    """A single field read or write in bytecode.

    Attributes:
        class_name: Qualified name of the class containing the method.
        method_name: Name of the method performing the access.
        method_index: Index into AbcFile.methods.
        field_name: The resolved field/property name being accessed.
        access_type: One of ``"read"``, ``"write"``, or ``"init"``.
        offset: Bytecode offset of the instruction.
    """
    class_name: str
    method_name: str
    method_index: int
    field_name: str
    access_type: str
    offset: int


@dataclass(slots=True)
class FieldAccessIndex:
    """Index of field accesses across all method bodies.

    Tracks every ``OP_getproperty`` (read), ``OP_setproperty`` (write),
    and ``OP_initproperty`` (init) instruction, mapping them to the
    owning class and method.

    Attributes:
        accesses: All field access entries.
        by_field: Map of ``"class_name.field_name"`` → list of accesses.
        by_method: Map of ``"class_name.method_name"`` → list of accesses.
        by_class: Map of class_name → list of accesses.
    """
    accesses: list[FieldAccess] = field(default_factory=list)
    by_field: dict[str, list[FieldAccess]] = field(
        default_factory=lambda: defaultdict(list))
    by_method: dict[str, list[FieldAccess]] = field(
        default_factory=lambda: defaultdict(list))
    by_class: dict[str, list[FieldAccess]] = field(
        default_factory=lambda: defaultdict(list))

    def _add(self, access: FieldAccess) -> None:
        """Add a field access to all indexes."""
        self.accesses.append(access)
        field_key = f"{access.class_name}.{access.field_name}"
        method_key = f"{access.class_name}.{access.method_name}"
        self.by_field[field_key].append(access)
        self.by_method[method_key].append(access)
        self.by_class[access.class_name].append(access)

    @classmethod
    def from_workspace(cls, workspace: object) -> FieldAccessIndex:
        """Build a FieldAccessIndex from a Workspace.

        Walks all method bodies, decodes instructions, and collects
        field read/write references.

        Args:
            workspace: A Workspace instance.

        Returns:
            Populated FieldAccessIndex.
        """
        from ..workspace.workspace import Workspace
        ws: Workspace = workspace  # type: ignore[assignment]

        index = cls()
        for abc in ws.abc_blocks:
            index._index_abc(abc, ws.classes)
        return index

    @classmethod
    def from_abc(cls, abc: AbcFile,
                 classes: list[ClassInfo] | None = None) -> FieldAccessIndex:
        """Build a FieldAccessIndex from a single AbcFile.

        Args:
            abc: The AbcFile to analyze.
            classes: Optional class list for method name resolution.

        Returns:
            Populated FieldAccessIndex.
        """
        index = cls()
        index._index_abc(abc, classes or [])
        return index

    def _index_abc(self, abc: AbcFile, classes: list[ClassInfo]) -> None:
        """Walk all method bodies in an AbcFile and index field accesses."""
        method_owner_map = _build_method_owner_map(abc, classes)
        method_name_map = _build_method_name_map(abc, classes)

        for body in abc.method_bodies:
            owner_class = method_owner_map.get(body.method, "")
            method_name = method_name_map.get(
                body.method, f"method_{body.method}")

            try:
                hits = scan_relevant_opcodes(body.code, _FIELD_SCAN_OPS)
            except Exception:
                continue

            for offset, op, operand in hits:
                target = resolve_multiname(abc, operand)
                if target == "*" or target.startswith("multiname["):
                    continue
                self._add(FieldAccess(
                    class_name=owner_class,
                    method_name=method_name,
                    method_index=body.method,
                    field_name=target,
                    access_type=_FIELD_ACCESS_TYPE[op],
                    offset=offset,
                ))

    # ── Per-field queries ──────────────────────────────────────────────

    def writers_of(self, class_name: str, field_name: str) -> list[str]:
        """Get method names that write to a field.

        Args:
            class_name: Qualified or simple class name.
            field_name: The field name.

        Returns:
            Sorted list of unique method names that set this field.
        """
        key = self._resolve_field_key(class_name, field_name)
        return sorted(set(
            a.method_name for a in self.by_field.get(key, [])
            if a.access_type in ("write", "init")
        ))

    def readers_of(self, class_name: str, field_name: str) -> list[str]:
        """Get method names that read a field.

        Args:
            class_name: Qualified or simple class name.
            field_name: The field name.

        Returns:
            Sorted list of unique method names that read this field.
        """
        key = self._resolve_field_key(class_name, field_name)
        return sorted(set(
            a.method_name for a in self.by_field.get(key, [])
            if a.access_type == "read"
        ))

    def access_count(self, class_name: str, field_name: str) -> int:
        """Total number of accesses (read + write + init) for a field.

        Args:
            class_name: Qualified or simple class name.
            field_name: The field name.

        Returns:
            Total access count.
        """
        key = self._resolve_field_key(class_name, field_name)
        return len(self.by_field.get(key, []))

    # ── Per-method queries ─────────────────────────────────────────────

    def fields_read_by(self, class_name: str,
                       method_name: str) -> list[str]:
        """Get field names read by a method.

        Args:
            class_name: Qualified or simple class name.
            method_name: The method name.

        Returns:
            Sorted list of unique field names read.
        """
        key = self._resolve_method_key(class_name, method_name)
        return sorted(set(
            a.field_name for a in self.by_method.get(key, [])
            if a.access_type == "read"
        ))

    def fields_written_by(self, class_name: str,
                          method_name: str) -> list[str]:
        """Get field names written by a method.

        Args:
            class_name: Qualified or simple class name.
            method_name: The method name.

        Returns:
            Sorted list of unique field names written.
        """
        key = self._resolve_method_key(class_name, method_name)
        return sorted(set(
            a.field_name for a in self.by_method.get(key, [])
            if a.access_type in ("write", "init")
        ))

    def fields_accessed_by(self, class_name: str,
                           method_name: str) -> list[str]:
        """Get all field names accessed (read or write) by a method.

        Args:
            class_name: Qualified or simple class name.
            method_name: The method name.

        Returns:
            Sorted list of unique field names.
        """
        key = self._resolve_method_key(class_name, method_name)
        return sorted(set(
            a.field_name for a in self.by_method.get(key, [])
        ))

    # ── Constructor queries ────────────────────────────────────────────

    def constructor_assignments(self, class_name: str) -> list[str]:
        """Get fields assigned in the constructor, in bytecode order.

        Returns fields set via ``OP_setproperty`` or ``OP_initproperty``
        in the ``<init>`` method. Order matches the bytecode, which
        typically follows source declaration order.

        Args:
            class_name: Qualified or simple class name.

        Returns:
            List of field names in assignment order (may contain duplicates
            if a field is assigned multiple times).
        """
        key = self._resolve_method_key(class_name, "<init>")
        entries = self.by_method.get(key, [])
        return [
            a.field_name for a in entries
            if a.access_type in ("write", "init")
        ]

    def constructor_reads(self, class_name: str) -> list[str]:
        """Get fields read in the constructor.

        Args:
            class_name: Qualified or simple class name.

        Returns:
            Sorted list of unique field names read in the constructor.
        """
        key = self._resolve_method_key(class_name, "<init>")
        return sorted(set(
            a.field_name for a in self.by_method.get(key, [])
            if a.access_type == "read"
        ))

    # ── Per-class queries ──────────────────────────────────────────────

    def all_fields_in_class(self, class_name: str) -> list[str]:
        """Get all unique field names accessed within a class.

        Args:
            class_name: Qualified or simple class name.

        Returns:
            Sorted list of unique field names.
        """
        class_name = self._resolve_class_name(class_name)
        return sorted(set(
            a.field_name for a in self.by_class.get(class_name, [])
        ))

    def field_access_summary(self, class_name: str) -> dict[str, dict]:
        """Get a summary of all field accesses in a class.

        Returns a dict mapping field_name → {readers: [...], writers: [...]}.

        Args:
            class_name: Qualified or simple class name.

        Returns:
            Dict of field_name → access summary.
        """
        class_name = self._resolve_class_name(class_name)
        summary: dict[str, dict] = {}
        for a in self.by_class.get(class_name, []):
            if a.field_name not in summary:
                summary[a.field_name] = {
                    "readers": set(), "writers": set()}
            if a.access_type == "read":
                summary[a.field_name]["readers"].add(a.method_name)
            else:
                summary[a.field_name]["writers"].add(a.method_name)

        # Convert sets to sorted lists
        for info in summary.values():
            info["readers"] = sorted(info["readers"])
            info["writers"] = sorted(info["writers"])
        return summary

    # ── Properties ─────────────────────────────────────────────────────

    @property
    def total_accesses(self) -> int:
        """Total number of field access entries."""
        return len(self.accesses)

    @property
    def total_reads(self) -> int:
        """Total number of read accesses."""
        return sum(1 for a in self.accesses if a.access_type == "read")

    @property
    def total_writes(self) -> int:
        """Total number of write/init accesses."""
        return sum(
            1 for a in self.accesses
            if a.access_type in ("write", "init"))

    # ── Name resolution helpers ────────────────────────────────────────

    def _resolve_class_name(self, name: str) -> str:
        """Try exact match first, then simple name match."""
        if name in self.by_class:
            return name
        for key in self.by_class:
            if key.endswith(f".{name}") or key == name:
                return key
        return name

    def _resolve_field_key(self, class_name: str, field_name: str) -> str:
        """Resolve a class.field key, trying simple name match."""
        exact = f"{class_name}.{field_name}"
        if exact in self.by_field:
            return exact
        # Try qualified match
        for key in self.by_field:
            parts = key.rsplit(".", 1)
            if len(parts) == 2:
                cls, fld = parts
                if fld == field_name and (
                        cls == class_name
                        or cls.endswith(f".{class_name}")):
                    return key
        return exact

    def _resolve_method_key(self, class_name: str,
                            method_name: str) -> str:
        """Resolve a class.method key, trying simple name match."""
        exact = f"{class_name}.{method_name}"
        if exact in self.by_method:
            return exact
        for key in self.by_method:
            parts = key.rsplit(".", 1)
            if len(parts) == 2:
                cls, mth = parts
                if mth == method_name and (
                        cls == class_name
                        or cls.endswith(f".{class_name}")):
                    return key
        return exact


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
