"""Class-reference graph built from a Workspace.

Wraps ``ReferenceIndex`` into a per-class adjacency structure with typed
edges and per-node intrinsic features. Each user-defined class becomes a
node; each cross-reference between two user-defined classes becomes a
directed, typed edge.

Edges to framework/builtin types (Sprite, Event, Array, etc.) are
filtered out — they add noise without structural information. Strings
are collected per class in ``string_pool`` and indexed globally in
``ClassGraph.string_to_classes`` for quick reverse lookups.

Each node also carries method fingerprints
(see :mod:`flashkit.analysis.method_fingerprint`) so downstream code can
reason about method shapes without re-walking the ABC.

Typical usage::

    from flashkit.workspace import Workspace
    from flashkit.analysis import ClassGraph

    ws = Workspace()
    ws.load_swf("game.swf")
    g = ClassGraph.from_workspace(ws)

    node = g.nodes["PlayerController"]
    print(node.out_degree_by_kind)          # {'call': 12, 'field_type': 3, ...}
    print(len(node.method_fps), "methods fingerprinted")
    print(g.string_to_classes["Hello"])     # which classes reference "Hello"
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..workspace.workspace import Workspace

from .references import ReferenceIndex
from .method_fingerprint import (
    BUILTIN_TYPES,
    MethodFingerprint,
    extract_all_fingerprints,
)


__all__ = [
    "FRAMEWORK_TYPES",
    "CLASS_EDGE_KINDS",
    "ClassNode",
    "ClassGraph",
]


# Framework types filtered out of class-to-class edges. These are Flash
# Player runtime / AS3 builtins; references to them aren't meaningful
# when comparing user-defined class structure.
FRAMEWORK_TYPES: frozenset[str] = frozenset({
    "int", "uint", "Number", "String", "Boolean", "void", "Object",
    "Array", "Class", "Function", "*", "Namespace", "QName",
    "ByteArray", "Dictionary", "Date", "RegExp", "Error", "XML",
    "XMLList",
    # Display list
    "Sprite", "MovieClip", "DisplayObject", "DisplayObjectContainer",
    "BitmapData", "Bitmap", "Shape", "TextField", "TextFormat",
    # Events
    "Event", "EventDispatcher", "MouseEvent", "KeyboardEvent",
    "TimerEvent", "IOErrorEvent", "SecurityErrorEvent", "ProgressEvent",
    # Geometry
    "Point", "Rectangle", "Matrix", "ColorTransform",
    # Audio
    "Sound", "SoundChannel", "SoundTransform",
    # Network / IO
    "URLRequest", "URLLoader", "SharedObject", "Socket",
    # Misc
    "Timer", "Stage", "Loader", "LoaderInfo", "NetConnection",
    "Vector", "BlendMode",
})

# Edge kinds that represent class-to-class relationships.
CLASS_EDGE_KINDS: frozenset[str] = frozenset({
    "extends", "implements",
    "field_type", "param_type", "return_type",
    "call", "instantiation", "class_ref", "coerce",
})


def _normalize_super(super_name: str) -> str:
    """Keep the super name if it's a known builtin, else collapse to '?'."""
    if super_name in BUILTIN_TYPES:
        return super_name
    return "?"


@dataclass
class ClassNode:
    """One node per class in the graph.

    Stores intrinsic features (counts, flags) plus typed directed edges
    to/from other ``ClassNode``s in the same graph.

    Attributes:
        name: Simple class name.
        package: Package / namespace string (empty for default package).
        method_count: Number of instance methods, getters, setters.
        static_method_count: Number of static methods.
        field_count: Number of instance fields.
        static_field_count: Number of static fields.
        super_name: Superclass name, normalized — builtins preserved,
            user classes collapsed to ``"?"``.
        is_interface: Whether the class is an interface.
        is_sealed: Whether the class is sealed (no dynamic properties).
        out_edges: ``(target_name, edge_kind)`` pairs for outgoing refs.
        in_edges: ``(source_name, edge_kind)`` pairs for incoming refs.
        out_degree_by_kind: Per-kind outgoing edge counts.
        in_degree_by_kind: Per-kind incoming edge counts.
        string_pool: String constants referenced by this class.
        method_fps: Method fingerprints for all methods + constructor.
        total_code_size: Sum of bytecode sizes across all fingerprints.
    """

    name: str = ""
    package: str = ""

    method_count: int = 0
    static_method_count: int = 0
    field_count: int = 0
    static_field_count: int = 0
    super_name: str = "?"
    is_interface: bool = False
    is_sealed: bool = False

    out_edges: list[tuple[str, str]] = field(default_factory=list)
    in_edges: list[tuple[str, str]] = field(default_factory=list)
    out_degree_by_kind: dict[str, int] = field(
        default_factory=lambda: defaultdict(int))
    in_degree_by_kind: dict[str, int] = field(
        default_factory=lambda: defaultdict(int))

    string_pool: frozenset[str] = field(default_factory=frozenset)

    method_fps: list[MethodFingerprint] = field(default_factory=list)
    total_code_size: int = 0


@dataclass
class ClassGraph:
    """Directed graph of class-to-class references with typed edges.

    Nodes are keyed by simple class name (not qualified).

    Attributes:
        nodes: Simple class name → :class:`ClassNode`.
        string_to_classes: Reverse index — string literal → set of
            class names that reference that string.
    """

    nodes: dict[str, ClassNode] = field(default_factory=dict)
    string_to_classes: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set))

    def total_degree(self, name: str) -> int:
        """Total degree (in + out) for a node, or 0 if the node is absent."""
        node = self.nodes.get(name)
        if node is None:
            return 0
        return len(node.out_edges) + len(node.in_edges)

    @classmethod
    def from_workspace(cls, workspace: Workspace) -> ClassGraph:
        """Build a :class:`ClassGraph` from a loaded :class:`Workspace`.

        Walks every class in the workspace, creates a node with intrinsic
        features, then follows its references to populate typed edges to
        other user-defined classes. Framework/builtin targets and
        self-references are filtered out. Finally, method fingerprints are
        extracted for every class.

        Args:
            workspace: A :class:`flashkit.workspace.Workspace` with at least
                one loaded SWF.

        Returns:
            A fully populated :class:`ClassGraph`.
        """
        # Reuse the workspace's already-built ReferenceIndex instead of
        # re-scanning every method body. Without this, ``workspace.class_graph``
        # triggered a second full pass over all bytecode — duplicating the
        # work ``build_all_indexes`` had just done.
        ref_index = workspace.reference_index

        # Map qualified + simple names → simple name for edge resolution.
        all_class_names: set[str] = set()
        qname_to_name: dict[str, str] = {}
        for info in workspace.classes:
            all_class_names.add(info.name)
            qname_to_name[info.qualified_name] = info.name
            qname_to_name[info.name] = info.name

        graph = cls()

        # Step 1: create nodes with intrinsic features.
        for info in workspace.classes:
            node = ClassNode(
                name=info.name,
                package=info.package,
                method_count=len(info.methods),
                static_method_count=len(info.static_methods),
                field_count=len(info.fields),
                static_field_count=len(info.static_fields),
                super_name=_normalize_super(info.super_name),
                is_interface=info.is_interface,
                is_sealed=info.is_sealed,
            )
            graph.nodes[info.name] = node

        # Step 2: walk references to build edges + string pools.
        class_strings: dict[str, set[str]] = defaultdict(set)

        for info in workspace.classes:
            refs = ref_index.references_from(info.qualified_name)
            node = graph.nodes[info.name]

            for ref in refs:
                if ref.ref_kind == "string_use":
                    class_strings[info.name].add(ref.target)
                    graph.string_to_classes[ref.target].add(info.name)
                    continue

                if ref.ref_kind not in CLASS_EDGE_KINDS:
                    continue

                target_name = qname_to_name.get(ref.target)
                if target_name is None:
                    if ref.target in all_class_names:
                        target_name = ref.target
                    else:
                        continue

                if target_name in FRAMEWORK_TYPES:
                    continue
                if target_name == info.name:
                    continue

                edge = (target_name, ref.ref_kind)
                node.out_edges.append(edge)
                node.out_degree_by_kind[ref.ref_kind] += 1

                target_node = graph.nodes.get(target_name)
                if target_node is not None:
                    target_node.in_edges.append((info.name, ref.ref_kind))
                    target_node.in_degree_by_kind[ref.ref_kind] += 1

        for cls_name, strings in class_strings.items():
            node = graph.nodes.get(cls_name)
            if node is not None:
                node.string_pool = frozenset(strings)

        # Step 3: extract method fingerprints for each class.
        for info in workspace.classes:
            node = graph.nodes.get(info.name)
            if node is None:
                continue
            try:
                abc = info.abc
            except RuntimeError:
                continue
            fps = extract_all_fingerprints(info, abc)
            node.method_fps = fps
            node.total_code_size = sum(fp.code_size for fp in fps)

        return graph
