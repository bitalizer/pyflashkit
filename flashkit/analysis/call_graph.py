"""
Call graph extraction from method body bytecode.

Scans AVM2 bytecode instructions in MethodBodyInfo.code to build a
graph of method-to-method call edges. Each edge records the calling
method, target multiname, opcode type, and bytecode offset.

Usage::

    from flashkit.workspace import Workspace
    from flashkit.analysis.call_graph import CallGraph

    ws = Workspace()
    ws.load_swf("application.swf")
    graph = CallGraph.from_workspace(ws)

    callers = graph.get_callers("doSomething")
    callees = graph.get_callees("MyClass.init")
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
    OP_callproperty, OP_callpropvoid, OP_constructprop,
    OP_getproperty, OP_setproperty, OP_initproperty,
    OP_getlex, OP_findpropstrict, OP_newclass,
)
from ..info.member_info import resolve_multiname, build_method_body_map
from ..info.class_info import ClassInfo


# Opcode categories for edges
CALL_OPS = {OP_callproperty, OP_callpropvoid}
CONSTRUCT_OPS = {OP_constructprop}
PROPERTY_READ_OPS = {OP_getproperty, OP_getlex, OP_findpropstrict}
PROPERTY_WRITE_OPS = {OP_setproperty, OP_initproperty}
CLASS_OPS = {OP_newclass}

# All opcodes that reference a multiname in their first operand
_MULTINAME_OPS = frozenset(
    CALL_OPS | CONSTRUCT_OPS | PROPERTY_READ_OPS
    | PROPERTY_WRITE_OPS | CLASS_OPS
)

# Opcode → mnemonic for CallEdge (avoids importing the full lookup table)
_OP_MNEMONIC = {
    OP_callproperty: "callproperty",
    OP_callpropvoid: "callpropvoid",
    OP_constructprop: "constructprop",
    OP_getproperty: "getproperty",
    OP_setproperty: "setproperty",
    OP_initproperty: "initproperty",
    OP_getlex: "getlex",
    OP_findpropstrict: "findpropstrict",
    OP_newclass: "newclass",
}


@dataclass(slots=True)
class CallEdge:
    """A single call/reference edge in the graph.

    Attributes:
        caller: Qualified name of the calling method (``"Class.method"``).
        caller_method_index: Method index in the AbcFile.
        target: Target multiname string (the called/referenced name).
        opcode: The opcode that generated this edge.
        mnemonic: Human-readable opcode name.
        offset: Bytecode offset within the method body.
        edge_type: Category string: ``"call"``, ``"construct"``, ``"read"``,
                   ``"write"``, or ``"class"``.
    """
    caller: str
    caller_method_index: int
    target: str
    opcode: int
    mnemonic: str
    offset: int
    edge_type: str


def _classify_op(opcode: int) -> str:
    """Classify an opcode into an edge type string."""
    if opcode in CALL_OPS:
        return "call"
    elif opcode in CONSTRUCT_OPS:
        return "construct"
    elif opcode in PROPERTY_READ_OPS:
        return "read"
    elif opcode in PROPERTY_WRITE_OPS:
        return "write"
    elif opcode in CLASS_OPS:
        return "class"
    return "unknown"


@dataclass(slots=True)
class CallGraph:
    """Graph of method call and reference edges extracted from bytecode.

    Attributes:
        edges: All edges in the graph.
        callers_index: Map of target name → list of edges calling it.
        callees_index: Map of caller name → list of edges it produces.
    """
    edges: list[CallEdge] = field(default_factory=list)
    callers_index: dict[str, list[CallEdge]] = field(
        default_factory=lambda: defaultdict(list))
    callees_index: dict[str, list[CallEdge]] = field(
        default_factory=lambda: defaultdict(list))

    @classmethod
    def from_workspace(cls, workspace: Workspace) -> CallGraph:
        """Build a CallGraph from a Workspace.

        Iterates all ABC blocks and their method bodies, decodes
        instructions, and collects edges for multiname-referencing opcodes.

        Args:
            workspace: A Workspace instance (with .abc_blocks and .classes).

        Returns:
            Populated CallGraph.
        """
        graph = cls()

        # Build a map from method_index → class_name.method_name
        # for all classes in the workspace
        from ..workspace.workspace import Workspace
        ws: Workspace = workspace  # type: ignore[assignment]

        for abc in ws.abc_blocks:
            method_name_map = _build_method_name_map(abc, ws.classes)

            for body in abc.method_bodies:
                caller_name = method_name_map.get(
                    body.method, f"method_{body.method}")

                try:
                    hits = scan_relevant_opcodes(body.code, _MULTINAME_OPS)
                except Exception:
                    continue

                for offset, op, operand in hits:
                    target = resolve_multiname(abc, operand)
                    if target == "*" or target.startswith("multiname["):
                        continue

                    edge = CallEdge(
                        caller=caller_name,
                        caller_method_index=body.method,
                        target=target,
                        opcode=op,
                        mnemonic=_OP_MNEMONIC.get(op, f"op_0x{op:02x}"),
                        offset=offset,
                        edge_type=_classify_op(op),
                    )
                    graph.edges.append(edge)
                    graph.callers_index[target].append(edge)
                    graph.callees_index[caller_name].append(edge)

        return graph

    @classmethod
    def from_abc(cls, abc: AbcFile,
                 classes: list[ClassInfo] | None = None) -> CallGraph:
        """Build a CallGraph from a single AbcFile.

        Args:
            abc: The AbcFile to analyze.
            classes: Optional class list for method name resolution.

        Returns:
            Populated CallGraph.
        """
        graph = cls()
        method_name_map = _build_method_name_map(abc, classes or [])

        for body in abc.method_bodies:
            caller_name = method_name_map.get(
                body.method, f"method_{body.method}")

            try:
                hits = scan_relevant_opcodes(body.code, _MULTINAME_OPS)
            except Exception:
                continue

            for offset, op, operand in hits:
                target = resolve_multiname(abc, operand)
                if target == "*" or target.startswith("multiname["):
                    continue

                edge = CallEdge(
                    caller=caller_name,
                    caller_method_index=body.method,
                    target=target,
                    opcode=op,
                    mnemonic=_OP_MNEMONIC.get(op, f"op_0x{op:02x}"),
                    offset=offset,
                    edge_type=_classify_op(op),
                )
                graph.edges.append(edge)
                graph.callers_index[target].append(edge)
                graph.callees_index[caller_name].append(edge)

        return graph

    def get_callers(self, target: str) -> list[CallEdge]:
        """Get all edges where *target* is called or referenced.

        Args:
            target: Target method/property name.

        Returns:
            List of CallEdge objects referencing this target.
        """
        return self.callers_index.get(target, [])

    def get_callees(self, caller: str) -> list[CallEdge]:
        """Get all edges originating from *caller*.

        Args:
            caller: Caller method name (``"Class.method"`` format).

        Returns:
            List of CallEdge objects from this caller.
        """
        return self.callees_index.get(caller, [])

    def get_callers_by_type(self, target: str,
                            edge_type: str) -> list[CallEdge]:
        """Get edges of a specific type referencing *target*.

        Args:
            target: Target name.
            edge_type: One of ``"call"``, ``"construct"``, ``"read"``,
                       ``"write"``, ``"class"``.

        Returns:
            Filtered list of CallEdge objects.
        """
        return [e for e in self.get_callers(target)
                if e.edge_type == edge_type]

    def get_instantiators(self, class_name: str) -> list[str]:
        """Get unique caller names that construct instances of *class_name*.

        Args:
            class_name: The class being instantiated.

        Returns:
            Sorted list of unique caller names.
        """
        edges = self.get_callers_by_type(class_name, "construct")
        return sorted(set(e.caller for e in edges))

    def get_unique_callers(self, target: str) -> list[str]:
        """Get unique caller names for a target (calls only).

        Args:
            target: Target method name.

        Returns:
            Sorted list of unique caller names.
        """
        edges = self.get_callers_by_type(target, "call")
        return sorted(set(e.caller for e in edges))

    def get_unique_callees(self, caller: str) -> list[str]:
        """Get unique target names called by a caller (calls only).

        Args:
            caller: Caller method name.

        Returns:
            Sorted list of unique target names.
        """
        edges = [e for e in self.get_callees(caller) if e.edge_type == "call"]
        return sorted(set(e.target for e in edges))

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def unique_targets(self) -> int:
        return len(self.callers_index)

    @property
    def unique_callers(self) -> int:
        return len(self.callees_index)


def _build_method_name_map(abc: AbcFile,
                           classes: list[ClassInfo]) -> dict[int, str]:
    """Build a mapping from method_index → ``"ClassName.methodName"``.

    Uses ClassInfo's resolved methods to build readable names.
    Falls back to ``"method_N"`` for methods not attached to classes.
    """
    name_map: dict[int, str] = {}

    for ci in classes:
        # Instance constructor
        name_map[ci.constructor_index] = f"{ci.name}.<init>"
        # Static initializer
        name_map[ci.static_init_index] = f"{ci.name}.<cinit>"

        for m in ci.methods:
            prefix = ""
            if m.is_getter:
                prefix = "get "
            elif m.is_setter:
                prefix = "set "
            name_map[m.method_index] = f"{ci.name}.{prefix}{m.name}"

        for m in ci.static_methods:
            name_map[m.method_index] = f"{ci.name}.static {m.name}"

    return name_map
