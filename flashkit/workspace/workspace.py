"""
Workspace: the top-level container for loaded SWF/SWZ content.

The Workspace loads one or more files, aggregates all ABC content,
and provides unified access to classes, strings, and analysis.

Usage::

    from flashkit.workspace import Workspace

    ws = Workspace()
    ws.load_swf("application.swf")
    ws.load_swz("module.swz")

    for cls in ws.classes:
        print(f"{cls.qualified_name} ({len(cls.fields)} fields)")
"""

from __future__ import annotations

from pathlib import Path

from ..abc.types import AbcFile
from ..info.class_info import ClassInfo
from ..info.package_info import PackageInfo, group_by_package
from .resource import Resource, load_swf, load_swz


class Workspace:
    """Unified workspace for analyzing SWF/SWZ content.

    Load one or more files, then query the aggregated class index.
    Analysis indexes (strings, references, field access, inheritance)
    are built lazily on first access and cached.

    Attributes:
        resources: List of loaded Resource objects.
    """

    def __init__(self) -> None:
        self.resources: list[Resource] = []
        self._class_index: dict[str, ClassInfo] = {}
        self._classes: list[ClassInfo] = []
        self._packages: list[PackageInfo] | None = None
        # Lazy analysis indexes (built on first access)
        self._string_index = None
        self._reference_index = None
        self._field_access_index = None
        self._inheritance_graph = None
        self._call_graph = None
        self._indexes_built = False

    def load_swf(self, path: str | Path) -> Resource:
        """Load a SWF file into the workspace.

        Args:
            path: Path to the SWF file.

        Returns:
            The loaded Resource.
        """
        res = load_swf(path)
        self._add_resource(res)
        return res

    def load_swz(self, path: str | Path) -> Resource:
        """Load a SWZ file into the workspace.

        Args:
            path: Path to the SWZ file.

        Returns:
            The loaded Resource.
        """
        res = load_swz(path)
        self._add_resource(res)
        return res

    def load_swf_bytes(self, data: bytes, name: str = "<memory>") -> Resource:
        """Load a SWF from raw bytes (no file needed).

        Useful for programmatically constructed SWFs or testing.

        Args:
            data: Raw SWF file bytes.
            name: Display name for the resource.

        Returns:
            The loaded Resource.
        """
        from ..swf.parser import parse_swf
        from ..swf.tags import TAG_DO_ABC, TAG_DO_ABC2
        from ..abc.parser import parse_abc
        from ..info.class_info import build_all_classes

        header, tags, version, file_length = parse_swf(data)
        abc_blocks: list[AbcFile] = []
        all_classes: list[ClassInfo] = []

        for tag in tags:
            abc_data = None
            if tag.tag_type == TAG_DO_ABC:
                abc_data = tag.payload
            elif tag.tag_type == TAG_DO_ABC2 and len(tag.payload) > 4:
                try:
                    null_idx = tag.payload.index(0, 4)
                    abc_data = tag.payload[null_idx + 1:]
                except ValueError:
                    pass

            if abc_data and len(abc_data) > 4:
                abc = parse_abc(abc_data)
                abc_blocks.append(abc)
                all_classes.extend(build_all_classes(abc))

        res = Resource(
            path=name,
            kind="swf",
            swf_header=header,
            swf_tags=tags,
            swf_version=version,
            abc_blocks=abc_blocks,
            classes=all_classes,
        )
        self._add_resource(res)
        return res

    def load(self, path: str | Path) -> Resource:
        """Load a file, auto-detecting format by extension.

        Args:
            path: Path to a SWF or SWZ file.

        Returns:
            The loaded Resource.
        """
        p = Path(path)
        if p.suffix.lower() == ".swz":
            return self.load_swz(p)
        else:
            return self.load_swf(p)

    def _add_resource(self, res: Resource) -> None:
        """Add a resource and update indexes."""
        self.resources.append(res)
        for cls in res.classes:
            self._classes.append(cls)
            cls._workspace = self
            # Index by both simple name and qualified name
            self._class_index[cls.name] = cls
            if cls.qualified_name != cls.name:
                self._class_index[cls.qualified_name] = cls
        self._packages = None  # invalidate cache
        self._invalidate_indexes()

    @property
    def classes(self) -> list[ClassInfo]:
        """All classes across all loaded resources."""
        return self._classes

    @property
    def abc_blocks(self) -> list[AbcFile]:
        """All AbcFile objects across all loaded resources."""
        result: list[AbcFile] = []
        for res in self.resources:
            result.extend(res.abc_blocks)
        return result

    @property
    def packages(self) -> list[PackageInfo]:
        """All packages, computed from the class index."""
        if self._packages is None:
            self._packages = group_by_package(self._classes)
        return self._packages

    def get_class(self, name: str) -> ClassInfo | None:
        """Look up a class by name or qualified name.

        Args:
            name: Simple name (e.g. ``"MyClass"``) or qualified
                  (e.g. ``"com.example.MyClass"``).

        Returns:
            ClassInfo if found, None otherwise.
        """
        return self._class_index.get(name)

    def find_classes(
        self,
        *,
        name: str | None = None,
        extends: str | None = None,
        implements: str | None = None,
        package: str | None = None,
        is_interface: bool | None = None,
    ) -> list[ClassInfo]:
        """Find classes matching the given criteria.

        All criteria are AND-combined.

        Args:
            name: Substring match on class name.
            extends: Exact match on superclass name.
            implements: Exact match on one of the interface names.
            package: Exact match on package name.
            is_interface: Filter by interface flag.

        Returns:
            List of matching ClassInfo objects.
        """
        results = self._classes
        if name is not None:
            results = [c for c in results if name in c.name]
        if extends is not None:
            results = [c for c in results if c.super_name == extends]
        if implements is not None:
            results = [c for c in results if implements in c.interfaces]
        if package is not None:
            results = [c for c in results if c.package == package]
        if is_interface is not None:
            results = [c for c in results if c.is_interface == is_interface]
        return results

    @property
    def class_count(self) -> int:
        return len(self._classes)

    @property
    def interface_count(self) -> int:
        return sum(1 for c in self._classes if c.is_interface)

    def summary(self) -> str:
        """Return a human-readable summary of the workspace."""
        lines = [f"Workspace: {len(self.resources)} resource(s)"]
        for res in self.resources:
            lines.append(
                f"  {res.path}: {res.class_count} classes, "
                f"{res.method_count} methods, {res.string_count} strings")
        lines.append(
            f"Total: {self.class_count} classes, "
            f"{self.interface_count} interfaces, "
            f"{len(self.packages)} packages")
        return "\n".join(lines)

    # ── Lazy analysis indexes ─────────────────────────────────────────

    def _invalidate_indexes(self) -> None:
        """Reset cached analysis indexes (called when resources change)."""
        self._string_index = None
        self._reference_index = None
        self._field_access_index = None
        self._inheritance_graph = None
        self._call_graph = None
        self._indexes_built = False

    def _ensure_indexes(self) -> None:
        """Build all analysis indexes if not already built.

        Uses the unified single-pass builder so bytecode is decoded once.
        """
        if self._indexes_built:
            return
        from ..analysis.unified import build_all_indexes
        from ..analysis.inheritance import InheritanceGraph
        self._string_index, self._reference_index, self._field_access_index = (
            build_all_indexes(self))
        self._inheritance_graph = InheritanceGraph.from_classes(self._classes)
        self._indexes_built = True

    @property
    def string_index(self):
        """Lazily-built StringIndex (use convenience methods instead)."""
        self._ensure_indexes()
        return self._string_index

    @property
    def reference_index(self):
        """Lazily-built ReferenceIndex (use convenience methods instead)."""
        self._ensure_indexes()
        return self._reference_index

    @property
    def field_access_index(self):
        """Lazily-built FieldAccessIndex (use convenience methods instead)."""
        self._ensure_indexes()
        return self._field_access_index

    @property
    def inheritance(self):
        """Lazily-built InheritanceGraph."""
        self._ensure_indexes()
        return self._inheritance_graph

    @property
    def call_graph(self):
        """Lazily-built CallGraph."""
        if self._call_graph is None:
            from ..analysis.call_graph import CallGraph
            self._call_graph = CallGraph.from_workspace(self)
        return self._call_graph

    # ── Call graph ────────────────────────────────────────────────────

    def callers(self, target: str) -> list:
        """Get all callers of a method/property.

        Args:
            target: Method or property name.

        Returns:
            List of CallEdge objects.
        """
        return self.call_graph.get_callers(target)

    def callees(self, caller: str) -> list:
        """Get all calls made from a method.

        Args:
            caller: Caller method name (``"Class.method"`` format).

        Returns:
            List of CallEdge objects.
        """
        return self.call_graph.get_callees(caller)

    # ── String search ─────────────────────────────────────────────────

    def search_strings(self, pattern: str, regex: bool = False) -> list[str]:
        """Search for string constants matching a pattern.

        Args:
            pattern: Substring to search for, or regex if regex=True.
            regex: If True, treat pattern as a regular expression.

        Returns:
            List of matching string values.
        """
        return self.string_index.search(pattern, regex=regex)

    def strings_in_class(self, class_name: str) -> list[str]:
        """Get all strings referenced by a class.

        Args:
            class_name: Simple or qualified class name.

        Returns:
            Sorted list of unique string values.
        """
        return self.string_index.strings_in_class(class_name)

    def classes_using_string(self, string: str) -> list[str]:
        """Get all classes that reference a specific string.

        Args:
            string: The exact string value.

        Returns:
            Sorted list of class qualified names.
        """
        return self.string_index.classes_using_string(string)

    @property
    def all_strings(self) -> set[str]:
        """All strings across all ABC string pools."""
        self._ensure_indexes()
        return self._string_index.pool_strings

    def url_strings(self) -> list[str]:
        """Strings that look like URLs."""
        self._ensure_indexes()
        return self._string_index.url_strings()

    def debug_markers(self) -> list[str]:
        """Strings that look like debug file markers (.as, .hx, etc.)."""
        self._ensure_indexes()
        return self._string_index.debug_markers()

    # ── References ────────────────────────────────────────────────────

    def references_to(self, name: str) -> list:
        """Get all incoming references to a target name.

        Args:
            name: Target name (class, type, method, or string).

        Returns:
            List of Reference objects pointing to this target.
        """
        return self.reference_index.references_to(name)

    def references_from(self, class_name: str) -> list:
        """Get all outgoing references from a class.

        Args:
            class_name: Source class qualified name.

        Returns:
            List of Reference objects originating from this class.
        """
        return self.reference_index.references_from(class_name)

    # ── Inheritance ───────────────────────────────────────────────────

    def get_subclasses(self, name: str) -> list[str]:
        """Get direct subclasses of a class.

        Args:
            name: Class name (simple or qualified).

        Returns:
            List of subclass qualified names.
        """
        return self.inheritance.get_children(name)

    def get_superclass(self, name: str) -> str | None:
        """Get the direct superclass of a class.

        Args:
            name: Class name (simple or qualified).

        Returns:
            Superclass qualified name, or None.
        """
        return self.inheritance.get_parent(name)

    def get_ancestors(self, name: str) -> list[str]:
        """Get the full ancestor chain of a class.

        Args:
            name: Class name (simple or qualified).

        Returns:
            List from immediate parent to root.
        """
        return self.inheritance.get_all_parents(name)

    def get_descendants(self, name: str) -> list[str]:
        """Get all transitive subclasses of a class.

        Args:
            name: Class name (simple or qualified).

        Returns:
            List of all descendant qualified names.
        """
        return self.inheritance.get_all_children(name)

    # ── Field access ──────────────────────────────────────────────────

    def fields_written_by(self, class_name: str,
                          method_name: str) -> list[str]:
        """Get fields written by a method.

        Args:
            class_name: Qualified or simple class name.
            method_name: The method name.

        Returns:
            Sorted list of field names written.
        """
        return self.field_access_index.fields_written_by(
            class_name, method_name)

    def fields_read_by(self, class_name: str,
                       method_name: str) -> list[str]:
        """Get fields read by a method.

        Args:
            class_name: Qualified or simple class name.
            method_name: The method name.

        Returns:
            Sorted list of field names read.
        """
        return self.field_access_index.fields_read_by(
            class_name, method_name)

    def constructor_assignments(self, class_name: str) -> list[str]:
        """Get fields assigned in the constructor, in bytecode order.

        Args:
            class_name: Qualified or simple class name.

        Returns:
            List of field names in assignment order.
        """
        return self.field_access_index.constructor_assignments(class_name)

    def constructor_reads(self, class_name: str) -> list[str]:
        """Get fields read in the constructor.

        Args:
            class_name: Qualified or simple class name.

        Returns:
            List of field names read.
        """
        return self.field_access_index.constructor_reads(class_name)

    def field_access_count(self, class_name: str,
                           field_name: str) -> int:
        """Get total number of accesses to a field.

        Args:
            class_name: Qualified or simple class name.
            field_name: The field name.

        Returns:
            Total access count (reads + writes).
        """
        return self.field_access_index.access_count(class_name, field_name)

    def field_access_summary(self, class_name: str) -> dict[str, dict]:
        """Get a summary of all field accesses in a class.

        Args:
            class_name: Qualified or simple class name.

        Returns:
            Dict of field_name -> {readers: [...], writers: [...]}.
        """
        return self.field_access_index.field_access_summary(class_name)

    def field_writers(self, class_name: str,
                      field_name: str) -> list[str]:
        """Get methods that write to a specific field.

        Args:
            class_name: Qualified or simple class name.
            field_name: The field name.

        Returns:
            Sorted list of method names.
        """
        return self.field_access_index.writers_of(class_name, field_name)

    def field_readers(self, class_name: str,
                      field_name: str) -> list[str]:
        """Get methods that read a specific field.

        Args:
            class_name: Qualified or simple class name.
            field_name: The field name.

        Returns:
            Sorted list of method names.
        """
        return self.field_access_index.readers_of(class_name, field_name)

    # ── Search helpers ────────────────────────────────────────────────

    def get_implementors(self, interface_name: str) -> list[str]:
        """Get all classes that implement an interface.

        Args:
            interface_name: Interface name (simple or qualified).

        Returns:
            Sorted list of implementing class qualified names.
        """
        return self.inheritance.get_implementors(interface_name)

    def find_fields(
        self,
        *,
        name: str | None = None,
        type_name: str | None = None,
        is_static: bool | None = None,
    ) -> list[tuple[ClassInfo, object]]:
        """Find fields across all classes.

        Args:
            name: Substring match on field name.
            type_name: Exact match on field type.
            is_static: Filter by static flag.

        Returns:
            List of (ClassInfo, FieldInfo) tuples.
        """
        results = []
        for ci in self._classes:
            for f in ci.all_fields:
                if name is not None and name not in f.name:
                    continue
                if type_name is not None and f.type_name != type_name:
                    continue
                if is_static is not None and f.is_static != is_static:
                    continue
                results.append((ci, f))
        return results

    def find_methods(
        self,
        *,
        name: str | None = None,
        return_type: str | None = None,
        param_type: str | None = None,
        is_static: bool | None = None,
    ) -> list[tuple[ClassInfo, object]]:
        """Find methods across all classes.

        Args:
            name: Substring match on method name.
            return_type: Exact match on return type.
            param_type: Exact match on any parameter type.
            is_static: Filter by static flag.

        Returns:
            List of (ClassInfo, MethodInfoResolved) tuples.
        """
        results = []
        for ci in self._classes:
            for m in ci.all_methods:
                if name is not None and name not in m.name:
                    continue
                if return_type is not None and m.return_type != return_type:
                    continue
                if param_type is not None and param_type not in m.param_types:
                    continue
                if is_static is not None and m.is_static != is_static:
                    continue
                results.append((ci, m))
        return results

    def find_instantiators(self, class_name: str) -> list:
        """Find all places that construct instances of a class.

        Args:
            class_name: The class being instantiated.

        Returns:
            List of Reference objects with ref_kind="instantiation".
        """
        return self.reference_index.instantiators(class_name)

    def find_type_users(self, type_name: str) -> list:
        """Find all places that reference a type (fields, params, returns).

        Args:
            type_name: The type name.

        Returns:
            List of Reference objects.
        """
        result = self.reference_index.field_type_users(type_name)
        result += self.reference_index.method_param_users(type_name)
        result += self.reference_index.method_return_users(type_name)
        return result

    def find_classes_with_field_type(
        self, type_name: str,
    ) -> list[ClassInfo]:
        """Find classes that have a field of the given type.

        Args:
            type_name: The field type name.

        Returns:
            List of ClassInfo objects.
        """
        seen: set[str] = set()
        results: list[ClassInfo] = []
        for ci in self._classes:
            if ci.qualified_name in seen:
                continue
            for f in ci.all_fields:
                if f.type_name == type_name:
                    seen.add(ci.qualified_name)
                    results.append(ci)
                    break
        return results

    def disassemble_method(
        self,
        class_name: str,
        method_name: str,
    ) -> list["ResolvedInstruction"]:
        """Disassemble a method body into readable instructions.

        Decodes the AVM2 bytecode and resolves all operands: multiname
        indices become field/class/method names, string indices become
        quoted literals, int/uint/double become numeric values.

        Use ``"<init>"`` for the instance constructor and ``"<cinit>"``
        for the static initializer.

        Args:
            class_name: Class name (simple or qualified).
            method_name: Method name, or ``"<init>"``/``"<cinit>"``.

        Returns:
            List of ``ResolvedInstruction`` — each has ``offset``,
            ``mnemonic``, and ``operands`` (list of readable strings).

        Raises:
            KeyError: If class or method not found.
            ValueError: If method has no body (abstract/interface).
        """
        from ..abc.disasm import decode_instructions, resolve_instructions
        from ..info.member_info import build_method_body_map

        cls = self.get_class(class_name)
        if cls is None:
            raise KeyError(f"Class '{class_name}' not found")

        abc = cls._abc
        if abc is None:
            raise ValueError(
                f"Class '{class_name}' has no AbcFile back-reference")

        # Constructor / static initializer
        if method_name in ("<init>", "<cinit>"):
            method_idx = (cls.constructor_index if method_name == "<init>"
                          else cls.static_init_index)
            body_map = build_method_body_map(abc)
            if method_idx not in body_map:
                raise ValueError(
                    f"{method_name} on '{class_name}' has no body")
            body = abc.method_bodies[body_map[method_idx]]
        else:
            method = cls.get_method(method_name)
            if method is None:
                raise KeyError(
                    f"Method '{method_name}' not found on '{class_name}'")
            if method.body_index < 0:
                raise ValueError(
                    f"Method '{method_name}' on '{class_name}' has no body "
                    f"(abstract or interface method)")
            body = abc.method_bodies[method.body_index]

        raw = decode_instructions(body.code)
        return resolve_instructions(abc, raw)

    def find_classes_with_method_returning(
        self, return_type: str,
    ) -> list[ClassInfo]:
        """Find classes that have a method returning the given type.

        Args:
            return_type: The return type name.

        Returns:
            List of ClassInfo objects.
        """
        seen: set[str] = set()
        results: list[ClassInfo] = []
        for ci in self._classes:
            if ci.qualified_name in seen:
                continue
            for m in ci.all_methods:
                if m.return_type == return_type:
                    seen.add(ci.qualified_name)
                    results.append(ci)
                    break
        return results
