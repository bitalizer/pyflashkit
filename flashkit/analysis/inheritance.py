"""
Inheritance graph for ABC classes.

Builds a directed graph of class inheritance and interface implementation
from resolved ClassInfo data. Supports ancestor/descendant queries,
interface implementor lookup, and subclass checks.

Usage::

    from flashkit.workspace import Workspace
    from flashkit.analysis.inheritance import InheritanceGraph

    ws = Workspace()
    ws.load_swf("application.swf")
    graph = InheritanceGraph.from_classes(ws.classes)

    parent = graph.get_parent("MySprite")
    children = graph.get_children("BaseEntity")
    implementors = graph.get_implementors("IDisposable")
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from dataclasses import dataclass, field
from collections import defaultdict

from ..info.class_info import ClassInfo

if TYPE_CHECKING:
    from ..workspace.workspace import Workspace


@dataclass(slots=True)
class InheritanceGraph:
    """Directed graph of class inheritance and interface relationships.

    Attributes:
        classes: Map of qualified name → ClassInfo.
        parent_map: Map of class name → superclass name.
        children_map: Map of class name → set of direct subclass names.
        interface_map: Map of class name → set of interface names it implements.
        implementors_map: Map of interface name → set of class names implementing it.
    """
    classes: dict[str, ClassInfo] = field(default_factory=dict)
    parent_map: dict[str, str] = field(default_factory=dict)
    children_map: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    interface_map: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    implementors_map: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    @classmethod
    def from_classes(cls, classes: list[ClassInfo]) -> InheritanceGraph:
        """Build an InheritanceGraph from a list of ClassInfo objects.

        Args:
            classes: All resolved classes (typically from Workspace.classes).

        Returns:
            Populated InheritanceGraph.
        """
        graph = cls()

        for ci in classes:
            key = ci.qualified_name
            graph.classes[key] = ci

            # Parent → child edge
            if ci.super_name and ci.super_name != "*":
                super_qualified = (
                    f"{ci.super_package}.{ci.super_name}"
                    if ci.super_package else ci.super_name
                )
                graph.parent_map[key] = super_qualified
                graph.children_map[super_qualified].add(key)

            # Interface edges
            for iface in ci.interfaces:
                graph.interface_map[key].add(iface)
                graph.implementors_map[iface].add(key)

        return graph

    @classmethod
    def from_workspace(cls, workspace: Workspace) -> InheritanceGraph:
        """Return the workspace's cached InheritanceGraph.

        Kept as a thin accessor for backwards compatibility; the real
        build happens lazily inside Workspace.

        Args:
            workspace: Workspace instance with loaded classes.

        Returns:
            The same InheritanceGraph
            ``workspace.inheritance`` returns.
        """
        return workspace.inheritance

    def get_parent(self, name: str) -> str | None:
        """Get the direct superclass of a class.

        Args:
            name: Class name (simple or qualified).

        Returns:
            Superclass qualified name, or None if not found / root class.
        """
        key = self._resolve_name(name)
        return self.parent_map.get(key) if key else None

    def get_children(self, name: str) -> list[str]:
        """Get direct subclasses of a class.

        Args:
            name: Class name (simple or qualified).

        Returns:
            List of direct subclass qualified names.
        """
        key = self._resolve_name(name)
        if key is None:
            return []
        return sorted(self.children_map.get(key, set()))

    def get_all_parents(self, name: str) -> list[str]:
        """Get the full ancestor chain (class → superclass → ... → root).

        Args:
            name: Class name (simple or qualified).

        Returns:
            List of ancestor qualified names, from immediate parent to root.
        """
        key = self._resolve_name(name)
        if key is None:
            return []
        result: list[str] = []
        visited: set[str] = set()
        current = key
        while current in self.parent_map:
            parent = self.parent_map[current]
            if parent in visited:
                break  # circular inheritance guard
            visited.add(parent)
            result.append(parent)
            current = parent
        return result

    def get_all_children(self, name: str) -> list[str]:
        """Get all descendants (transitive closure of subclasses).

        Args:
            name: Class name (simple or qualified).

        Returns:
            List of all descendant qualified names (breadth-first order).
        """
        key = self._resolve_name(name)
        if key is None:
            return []
        result: list[str] = []
        visited: set[str] = set()
        queue = [key]
        while queue:
            current = queue.pop(0)
            for child in sorted(self.children_map.get(current, set())):
                if child not in visited:
                    visited.add(child)
                    result.append(child)
                    queue.append(child)
        return result

    def get_implementors(self, interface_name: str) -> list[str]:
        """Get all classes that directly implement an interface.

        Args:
            interface_name: Interface name (simple or qualified).

        Returns:
            List of implementing class qualified names.
        """
        # Try exact match first, then simple name scan
        if interface_name in self.implementors_map:
            return sorted(self.implementors_map[interface_name])
        # Try matching simple name in the implementors keys
        for key, impls in self.implementors_map.items():
            if key == interface_name or key.endswith(f".{interface_name}"):
                return sorted(impls)
        return []

    def get_interfaces(self, name: str) -> list[str]:
        """Get all interfaces directly implemented by a class.

        Args:
            name: Class name (simple or qualified).

        Returns:
            List of interface name strings.
        """
        key = self._resolve_name(name)
        if key is None:
            return []
        return sorted(self.interface_map.get(key, set()))

    def get_siblings(self, name: str) -> list[str]:
        """Get classes sharing the same direct parent (excluding self).

        Args:
            name: Class name (simple or qualified).

        Returns:
            List of sibling class qualified names.
        """
        key = self._resolve_name(name)
        if key is None:
            return []
        parent = self.parent_map.get(key)
        if parent is None:
            return []
        return sorted(c for c in self.children_map.get(parent, set()) if c != key)

    def is_subclass(self, child: str, parent: str) -> bool:
        """Check if *child* is a (transitive) subclass of *parent*.

        Args:
            child: Potential subclass name.
            parent: Potential ancestor name.

        Returns:
            True if child inherits from parent (directly or transitively).
        """
        child_key = self._resolve_name(child)
        parent_key = self._resolve_name(parent)
        if child_key is None or parent_key is None:
            return False
        ancestors = self.get_all_parents(child_key)
        return parent_key in ancestors

    def get_roots(self) -> list[str]:
        """Get all root classes (no superclass in the graph).

        Returns:
            List of root class qualified names.
        """
        roots: list[str] = []
        for name in self.classes:
            parent = self.parent_map.get(name)
            if parent is None or parent not in self.classes:
                roots.append(name)
        return sorted(roots)

    def get_depth(self, name: str) -> int:
        """Get the inheritance depth of a class (0 for roots).

        Args:
            name: Class name (simple or qualified).

        Returns:
            Number of ancestors in the graph, or -1 if not found.
        """
        key = self._resolve_name(name)
        if key is None:
            return -1
        return len(self.get_all_parents(key))

    def _resolve_name(self, name: str) -> str | None:
        """Resolve a simple or qualified name to a name known in the graph.

        Checks loaded classes first, then parent/children map keys
        (for external classes like Object that aren't loaded but appear
        as superclasses).
        """
        # Exact match in loaded classes
        if name in self.classes:
            return name
        # Exact match in external references (parent/child keys)
        if name in self.children_map or name in self.parent_map:
            return name
        # Try simple name match in loaded classes
        for qname, ci in self.classes.items():
            if ci.name == name:
                return qname
        # Try simple name match in children_map keys (external classes)
        for key in self.children_map:
            if key.endswith(f".{name}") or key == name:
                return key
        return None
