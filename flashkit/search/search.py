"""
Unified search engine for workspace content.

Provides a high-level query API that combines all analysis indexes
(inheritance, call graph, references, strings) into a single interface.

Usage::

    from flashkit.workspace import Workspace
    from flashkit.search import SearchEngine

    ws = Workspace()
    ws.load_swf("application.swf")
    engine = SearchEngine(ws)

    # Find classes extending a base
    subclasses = engine.find_subclasses("BaseSprite")

    # Find who instantiates a class
    creators = engine.find_instantiators("Point")

    # Find classes using a specific string
    matches = engine.find_by_string("config.xml")
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..info.class_info import ClassInfo
from ..analysis.inheritance import InheritanceGraph
from ..analysis.call_graph import CallGraph, CallEdge
from ..analysis.references import ReferenceIndex, Reference
from ..analysis.strings import StringIndex, StringUsage


@dataclass
class ClassResult:
    """A class search result with context about why it matched.

    Attributes:
        class_info: The matched ClassInfo.
        match_reason: Why this class matched (e.g. ``"extends BaseSprite"``).
    """
    class_info: ClassInfo
    match_reason: str = ""

    @property
    def name(self) -> str:
        return self.class_info.qualified_name


@dataclass
class MemberResult:
    """A member (field or method) search result.

    Attributes:
        class_name: Owning class qualified name.
        member_name: Field or method name.
        member_type: ``"field"`` or ``"method"``.
        match_reason: Why this member matched.
    """
    class_name: str
    member_name: str
    member_type: str
    match_reason: str = ""


@dataclass
class StringResult:
    """A string search result.

    Attributes:
        string: The matched string value.
        usages: Where this string is used.
    """
    string: str
    usages: list[StringUsage] = field(default_factory=list)


class SearchEngine:
    """Unified query interface over all analysis indexes.

    Lazily builds analysis indexes on first use.

    Args:
        workspace: A Workspace instance with loaded content.
    """

    def __init__(self, workspace: object) -> None:
        from ..workspace.workspace import Workspace
        self._ws: Workspace = workspace  # type: ignore[assignment]
        self._inheritance: InheritanceGraph | None = None
        self._call_graph: CallGraph | None = None
        self._references: ReferenceIndex | None = None
        self._strings: StringIndex | None = None

    @property
    def inheritance(self) -> InheritanceGraph:
        """Lazily built inheritance graph."""
        if self._inheritance is None:
            self._inheritance = InheritanceGraph.from_classes(self._ws.classes)
        return self._inheritance

    @property
    def call_graph(self) -> CallGraph:
        """Lazily built call graph."""
        if self._call_graph is None:
            self._call_graph = CallGraph.from_workspace(self._ws)
        return self._call_graph

    @property
    def references(self) -> ReferenceIndex:
        """Lazily built reference index."""
        if self._references is None:
            self._references = ReferenceIndex.from_workspace(self._ws)
        return self._references

    @property
    def strings(self) -> StringIndex:
        """Lazily built string index."""
        if self._strings is None:
            self._strings = StringIndex.from_workspace(self._ws)
        return self._strings

    # ── Class queries ──────────────────────────────────────────────────────

    def find_classes(
        self,
        *,
        name: str | None = None,
        extends: str | None = None,
        implements: str | None = None,
        package: str | None = None,
        is_interface: bool | None = None,
    ) -> list[ClassResult]:
        """Find classes matching criteria (delegates to Workspace.find_classes).

        All criteria are AND-combined.

        Args:
            name: Substring match on class name.
            extends: Exact match on superclass name.
            implements: Exact match on one of the interface names.
            package: Exact match on package name.
            is_interface: Filter by interface flag.

        Returns:
            List of ClassResult objects.
        """
        matches = self._ws.find_classes(
            name=name, extends=extends, implements=implements,
            package=package, is_interface=is_interface,
        )
        reasons: list[str] = []
        if name:
            reasons.append(f"name contains '{name}'")
        if extends:
            reasons.append(f"extends {extends}")
        if implements:
            reasons.append(f"implements {implements}")
        if package:
            reasons.append(f"in package {package}")
        if is_interface is not None:
            reasons.append("is interface" if is_interface else "is class")
        reason = ", ".join(reasons)
        return [ClassResult(class_info=c, match_reason=reason) for c in matches]

    def find_subclasses(self, class_name: str,
                        transitive: bool = False) -> list[ClassResult]:
        """Find direct or transitive subclasses.

        Args:
            class_name: The parent class name.
            transitive: If True, include all descendants.

        Returns:
            List of ClassResult objects.
        """
        if transitive:
            names = self.inheritance.get_all_children(class_name)
        else:
            names = self.inheritance.get_children(class_name)

        results: list[ClassResult] = []
        for n in names:
            ci = self._ws.get_class(n)
            if ci:
                results.append(ClassResult(
                    class_info=ci,
                    match_reason=f"{'transitively ' if transitive else ''}extends {class_name}",
                ))
        return results

    def find_implementors(self, interface_name: str) -> list[ClassResult]:
        """Find classes implementing an interface.

        Args:
            interface_name: The interface name.

        Returns:
            List of ClassResult objects.
        """
        names = self.inheritance.get_implementors(interface_name)
        results: list[ClassResult] = []
        for n in names:
            ci = self._ws.get_class(n)
            if ci:
                results.append(ClassResult(
                    class_info=ci,
                    match_reason=f"implements {interface_name}",
                ))
        return results

    # ── Member queries ─────────────────────────────────────────────────────

    def find_fields(
        self,
        *,
        name: str | None = None,
        type_name: str | None = None,
        is_static: bool | None = None,
    ) -> list[MemberResult]:
        """Find fields across all classes.

        Args:
            name: Substring match on field name.
            type_name: Exact match on field type.
            is_static: Filter by static flag.

        Returns:
            List of MemberResult objects.
        """
        results: list[MemberResult] = []
        for ci in self._ws.classes:
            for f in ci.all_fields:
                if name is not None and name not in f.name:
                    continue
                if type_name is not None and f.type_name != type_name:
                    continue
                if is_static is not None and f.is_static != is_static:
                    continue
                reason_parts = []
                if name:
                    reason_parts.append(f"name contains '{name}'")
                if type_name:
                    reason_parts.append(f"type={type_name}")
                results.append(MemberResult(
                    class_name=ci.qualified_name,
                    member_name=f.name,
                    member_type="field",
                    match_reason=", ".join(reason_parts),
                ))
        return results

    def find_methods(
        self,
        *,
        name: str | None = None,
        return_type: str | None = None,
        param_type: str | None = None,
        is_static: bool | None = None,
    ) -> list[MemberResult]:
        """Find methods across all classes.

        Args:
            name: Substring match on method name.
            return_type: Exact match on return type.
            param_type: Exact match on any parameter type.
            is_static: Filter by static flag.

        Returns:
            List of MemberResult objects.
        """
        results: list[MemberResult] = []
        for ci in self._ws.classes:
            for m in ci.all_methods:
                if name is not None and name not in m.name:
                    continue
                if return_type is not None and m.return_type != return_type:
                    continue
                if param_type is not None and param_type not in m.param_types:
                    continue
                if is_static is not None and m.is_static != is_static:
                    continue
                reason_parts = []
                if name:
                    reason_parts.append(f"name contains '{name}'")
                if return_type:
                    reason_parts.append(f"returns {return_type}")
                if param_type:
                    reason_parts.append(f"takes {param_type}")
                results.append(MemberResult(
                    class_name=ci.qualified_name,
                    member_name=m.name,
                    member_type="method",
                    match_reason=", ".join(reason_parts),
                ))
        return results

    # ── Reference queries ──────────────────────────────────────────────────

    def find_instantiators(self, class_name: str) -> list[Reference]:
        """Find all places that construct instances of a class.

        Args:
            class_name: The class being instantiated.

        Returns:
            List of Reference objects with ref_kind="instantiation".
        """
        return self.references.instantiators(class_name)

    def find_type_users(self, type_name: str) -> list[Reference]:
        """Find all places that reference a type (fields, params, returns).

        Args:
            type_name: The type name.

        Returns:
            Combined list of field_type, param_type, and return_type references.
        """
        result = self.references.field_type_users(type_name)
        result += self.references.method_param_users(type_name)
        result += self.references.method_return_users(type_name)
        return result

    def find_callers(self, method_name: str) -> list[CallEdge]:
        """Find all callers of a method.

        Args:
            method_name: The method name.

        Returns:
            List of CallEdge objects.
        """
        return self.call_graph.get_callers(method_name)

    def find_callees(self, caller: str) -> list[CallEdge]:
        """Find all methods/properties called by a method.

        Args:
            caller: The caller method name (``"Class.method"``).

        Returns:
            List of CallEdge objects.
        """
        return self.call_graph.get_callees(caller)

    # ── String queries ─────────────────────────────────────────────────────

    def find_by_string(self, pattern: str,
                       regex: bool = False) -> list[StringResult]:
        """Find string constants matching a pattern.

        Args:
            pattern: Substring or regex pattern.
            regex: If True, treat as regex.

        Returns:
            List of StringResult objects with usage locations.
        """
        matching = self.strings.search(pattern, regex=regex)
        results: list[StringResult] = []
        for s in matching:
            results.append(StringResult(
                string=s,
                usages=self.strings.by_string.get(s, []),
            ))
        return results

    def find_classes_by_string(self, string: str) -> list[ClassResult]:
        """Find classes that reference a specific string constant.

        Args:
            string: The exact string value.

        Returns:
            List of ClassResult objects.
        """
        class_names = self.strings.classes_using_string(string)
        results: list[ClassResult] = []
        for n in class_names:
            ci = self._ws.get_class(n)
            if ci:
                results.append(ClassResult(
                    class_info=ci,
                    match_reason=f"uses string '{string[:50]}'",
                ))
        return results

    # ── Structural pattern queries ─────────────────────────────────────────

    def find_classes_with_field_type(self, type_name: str) -> list[ClassResult]:
        """Find classes that have a field of the given type.

        Args:
            type_name: The field type name.

        Returns:
            List of ClassResult objects.
        """
        seen: set[str] = set()
        results: list[ClassResult] = []
        for ci in self._ws.classes:
            for f in ci.all_fields:
                if f.type_name == type_name and ci.qualified_name not in seen:
                    seen.add(ci.qualified_name)
                    results.append(ClassResult(
                        class_info=ci,
                        match_reason=f"has field of type {type_name}",
                    ))
        return results

    def find_classes_with_method_returning(
        self, return_type: str,
    ) -> list[ClassResult]:
        """Find classes that have a method returning the given type.

        Args:
            return_type: The return type name.

        Returns:
            List of ClassResult objects.
        """
        seen: set[str] = set()
        results: list[ClassResult] = []
        for ci in self._ws.classes:
            for m in ci.all_methods:
                if m.return_type == return_type and ci.qualified_name not in seen:
                    seen.add(ci.qualified_name)
                    results.append(ClassResult(
                        class_info=ci,
                        match_reason=f"has method returning {return_type}",
                    ))
        return results

    # ── Summary ────────────────────────────────────────────────────────────

    def summary(self) -> str:
        """Return a summary of the search engine's indexed data."""
        lines = [f"SearchEngine over {self._ws.class_count} classes"]
        if self._inheritance:
            lines.append(
                f"  Inheritance: {len(self._inheritance.classes)} nodes")
        if self._call_graph:
            lines.append(
                f"  Call graph: {self._call_graph.edge_count} edges")
        if self._references:
            lines.append(
                f"  References: {self._references.total_refs} refs")
        if self._strings:
            lines.append(
                f"  Strings: {self._strings.unique_string_count} unique, "
                f"{self._strings.total_usages} usages")
        return "\n".join(lines)
