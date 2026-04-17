"""Natural loop detection and loop nesting.

A *natural loop* is identified by a back-edge ``(tail, header)`` where
``header`` dominates ``tail``. Its body is the set of blocks that can
reach ``tail`` without going through ``header`` (plus the header
itself). An *exit* of the loop is a body block with a successor outside
the body.

When multiple back-edges share a header (e.g. ``continue`` inside a
``while``), they merge into a single ``Loop``: the body is the union of
the per-tail sub-bodies. This matches how structurers and most IRs
model such loops — one header, one loop construct, possibly multiple
internal continue edges. The ``Loop.tail`` field then points at an
arbitrary one of the tails (the one found first in iteration order).

Loop nesting is by set containment: loop ``A`` is an ancestor of loop
``B`` iff ``B.body`` is a proper subset of ``A.body``. The immediate
parent is the smallest enclosing ancestor. This gives an O(L^2) pass,
which is fine because L is always small (at most a few dozen loops in
the largest real methods we've seen).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .cfg import CFG, BasicBlock


@dataclass(eq=False)
class Loop:
    """A natural loop in a CFG.

    Attributes:
        header: The loop's single entry point; dominates every body
            block.
        tail: A back-edge source. If multiple back-edges target the
            same header, this is one of them (the body is the union of
            all tails' reach-regions).
        body: Every block in the loop, including ``header`` and
            ``tail``.
        exits: Body blocks with at least one successor outside
            ``body``. Ordered by block index for determinism.
        parent: The smallest enclosing loop, or ``None`` if the loop is
            top-level.
    """
    header: BasicBlock
    tail: BasicBlock
    body: frozenset[BasicBlock] = field(default_factory=frozenset)
    exits: list[BasicBlock] = field(default_factory=list)
    parent: "Loop | None" = None

    def __repr__(self) -> str:
        return (f"Loop(header=#{self.header.index}, "
                f"tail=#{self.tail.index}, "
                f"body_size={len(self.body)})")


@dataclass
class LoopTree:
    """The nesting hierarchy of a method's loops.

    Attributes:
        loops: Every loop in the method.
    """
    loops: list[Loop]

    def top_level_loops(self) -> list[Loop]:
        """Loops with no parent, in their original order."""
        return [loop for loop in self.loops if loop.parent is None]

    def children_of(self, loop: Loop) -> list[Loop]:
        """Direct children of ``loop``, in their original order."""
        return [l for l in self.loops if l.parent is loop]


def _dominates(a: int, b: int, idom: dict[int, int]) -> bool:
    """Does block ``a`` dominate block ``b`` according to ``idom``?

    A block dominates itself. Otherwise, walk the idom chain from ``b``
    until it hits ``a`` (``a`` dominates ``b``) or the entry
    (``a`` does not dominate ``b``).
    """
    if a == b:
        return True
    cur = b
    while idom[cur] != cur:
        cur = idom[cur]
        if cur == a:
            return True
    return False


def _loop_body(
    header: BasicBlock,
    tails: list[BasicBlock],
) -> set[BasicBlock]:
    """Compute the natural-loop body for one header and one or more tails.

    BFS backward from each tail, blocking the traversal at the header.
    The header is always included in the body.
    """
    body: set[BasicBlock] = {header}
    queue: deque[BasicBlock] = deque()
    for tail in tails:
        if tail is not header and tail not in body:
            body.add(tail)
            queue.append(tail)
    while queue:
        bb = queue.popleft()
        for pred in bb.predecessors:
            if pred is header or pred in body:
                continue
            body.add(pred)
            queue.append(pred)
    return body


def find_loops(cfg: CFG, idom: dict[int, int]) -> list[Loop]:
    """Identify every natural loop in ``cfg``.

    Args:
        cfg: The method's control-flow graph.
        idom: Immediate-dominator map (from ``compute_idom``).

    Returns:
        A list of ``Loop`` objects. Each loop has ``body``, ``exits``,
        and ``parent`` filled in. Order is by header block index for
        determinism.
    """
    # Collect back-edges and group by header.
    header_to_tails: dict[int, list[BasicBlock]] = {}
    for bb in cfg.blocks:
        for succ in bb.successors:
            # Back-edge: succ dominates bb.
            if _dominates(succ.index, bb.index, idom):
                header_to_tails.setdefault(succ.index, []).append(bb)

    # Build Loops.
    blocks_by_index = {bb.index: bb for bb in cfg.blocks}
    loops: list[Loop] = []
    for header_idx in sorted(header_to_tails):
        header = blocks_by_index[header_idx]
        tails = header_to_tails[header_idx]
        body = _loop_body(header, tails)
        exits = sorted(
            (bb for bb in body if any(s not in body for s in bb.successors)),
            key=lambda b: b.index,
        )
        loops.append(Loop(
            header=header,
            tail=tails[0],
            body=frozenset(body),
            exits=exits,
            parent=None,
        ))

    # Parent linking by set containment. Parent = smallest enclosing
    # ancestor (smallest body that strictly contains this one).
    for i, inner in enumerate(loops):
        smallest_parent: Loop | None = None
        for j, outer in enumerate(loops):
            if i == j:
                continue
            if inner.body < outer.body:   # strict subset
                if smallest_parent is None or len(outer.body) < len(smallest_parent.body):
                    smallest_parent = outer
        inner.parent = smallest_parent

    return loops


def build_loop_tree(loops: list[Loop]) -> LoopTree:
    """Wrap a flat list of loops as a ``LoopTree`` for traversal."""
    return LoopTree(loops=loops)
