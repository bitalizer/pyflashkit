"""Detect classes and methods that look unused.

"Unused" is a heuristic here — AS3's dynamic name lookup, event
binding through string names, reflection, and ExternalInterface all
mean there's no hard guarantee a class with zero static references is
actually dead. But most production SWFs don't lean on those
mechanisms for internal plumbing, so flagging unreferenced classes /
methods is usually right and always worth a human look.

The detection re-uses the already-built :class:`ReferenceIndex` and
:class:`CallGraph` on a workspace — nothing new is scanned from the
bytecode. That keeps ``find_dead_*`` O(edges) rather than O(code).
"""

from __future__ import annotations

from dataclasses import dataclass


__all__ = [
    "DeadMethodReport",
    "entrypoint_candidates",
    "find_dead_classes",
    "find_dead_methods",
    "find_entrypoints_and_dead_classes",
]


def entrypoint_candidates(workspace) -> list[str]:
    """Classes that extend a Flash display-list or event-dispatch base.

    The document class (wired at SWF load time) and every class whose
    instances are pushed onto the display list transitively inherit
    from :class:`flash.display.Sprite`, :class:`MovieClip`, or
    :class:`EventDispatcher`. Those are the typical entry points a
    human inspector should start from on an unfamiliar SWF.
    """
    return _entrypoint_candidates(workspace)


@dataclass(frozen=True, slots=True)
class DeadMethodReport:
    """A candidate-dead method entry."""
    class_name: str
    method_name: str
    reason: str


# Names that look callable from outside the ABC — AS3 life-cycle,
# event handlers, Flash runtime hooks. A method named one of these on
# a class that *is* referenced shouldn't be flagged as dead.
_LIFECYCLE_NAMES: frozenset[str] = frozenset({
    # AVM2 / AS3 core
    "constructor", "<init>", "<cinit>",
    # flash.display common
    "onEnterFrame", "addedToStage", "removedFromStage", "frameConstructed",
    # Event-y conventions
    "onLoad", "onStart", "onComplete", "onError",
    "handleEvent", "dispatchEvent",
    # ExternalInterface
    "onExternalCall",
})


def find_dead_classes(workspace) -> list[str]:
    """Qualified names of classes that are never referenced.

    A class is dead if:

    * Nothing in the workspace references its name, short or qualified,
      via :class:`ReferenceIndex`.
    * It has no direct subclasses (subclassing is an implicit
      reference that the reference index doesn't always capture).
    * It isn't a workspace entry-point candidate
      (``Sprite`` / ``MovieClip`` subclass — those are often the
      document class wired up at SWF-load time).

    Returns a sorted list; stable ordering makes diffing reports
    across SWF versions straightforward.
    """
    refs = workspace.reference_index
    inheritance = workspace.inheritance

    entry_candidates = _entrypoint_candidates(workspace)
    dead: list[str] = []
    for ci in workspace.classes:
        full = ci.qualified_name
        short = ci.name
        if full in entry_candidates:
            continue
        # Has anyone mentioned it?
        if refs.references_to(full) or refs.references_to(short):
            continue
        # Subclasses count as references.
        if inheritance.get_children(full) or inheritance.get_children(short):
            continue
        dead.append(full)
    dead.sort()
    return dead


def find_dead_methods(workspace) -> list[DeadMethodReport]:
    """Methods that appear never to be invoked.

    A method is dead if the workspace's :class:`CallGraph` has no
    edges targeting its bare name, and the method doesn't look like a
    life-cycle hook (``Event`` handlers, ``<init>``, etc.). Getters,
    setters, and override methods are excluded because their call
    sites usually don't go through ``callproperty`` by name.

    Note that the heuristic misses inter-SWF calls and reflection-based
    invocations. Treat the output as a starting point, not a verdict.
    """
    graph = workspace.call_graph

    # Build a lookup: method-name → count of call edges targeting it.
    hit_counts: dict[str, int] = {}
    for edge in graph.edges:
        hit_counts[edge.target] = hit_counts.get(edge.target, 0) + 1

    out: list[DeadMethodReport] = []
    for ci in workspace.classes:
        for m in ci.all_methods:
            if m.is_getter or m.is_setter:
                continue
            if m.name in _LIFECYCLE_NAMES:
                continue
            if hit_counts.get(m.name, 0) > 0:
                continue
            out.append(DeadMethodReport(
                class_name=ci.qualified_name,
                method_name=m.name,
                reason="no callgraph edge targets this name",
            ))
    out.sort(key=lambda r: (r.class_name, r.method_name))
    return out


def find_entrypoints_and_dead_classes(workspace) -> tuple[list[str], list[str]]:
    """Convenience combo — entry-point candidates first, dead classes
    second. Cheap, reuses the same indexes both functions need."""
    return _entrypoint_candidates(workspace), find_dead_classes(workspace)


# ── helpers ────────────────────────────────────────────────────────────


# Base classes that strongly suggest "this is wired up at SWF load
# time, not explicitly constructed." Any class that extends one of
# these is treated as a possible entry-point.
_ENTRYPOINT_BASES: frozenset[str] = frozenset({
    "flash.display.Sprite",
    "flash.display.MovieClip",
    "flash.display.DisplayObject",
    "flash.display.Stage",
    "flash.events.EventDispatcher",
    "Sprite", "MovieClip", "DisplayObject", "Stage", "EventDispatcher",
})


def _entrypoint_candidates(workspace) -> list[str]:
    """Classes that extend (directly or transitively) one of the Flash
    entry-point base classes. The result is sorted; used both as an
    exclusion set by ``find_dead_classes`` and as the feed for the
    public :func:`entrypoint_candidates` API (via the combo function
    above)."""
    inheritance = workspace.inheritance
    out: list[str] = []
    for ci in workspace.classes:
        chain = [ci.qualified_name, *inheritance.get_all_parents(ci.qualified_name)]
        if any(p in _ENTRYPOINT_BASES for p in chain):
            out.append(ci.qualified_name)
    out.sort()
    return out
