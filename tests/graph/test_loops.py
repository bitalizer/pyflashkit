"""Tests for natural loop detection and loop nesting.

A "natural loop" is defined by a single back-edge (tail -> header)
where the header dominates the tail. The loop body is every block that
can reach the tail without passing through the header.

Loop nesting is computed from set containment of loop bodies.
"""

from __future__ import annotations

import os

import pytest

from flashkit.graph.cfg import BasicBlock, CFG
from flashkit.graph.dominators import compute_idom
from flashkit.graph.loops import Loop, find_loops, build_loop_tree


def _mk_bb(index: int, start: int = 0) -> BasicBlock:
    return BasicBlock(index=index, start_offset=start, end_offset=start + 1)


def _link(a: BasicBlock, b: BasicBlock) -> None:
    a.successors.append(b)
    b.predecessors.append(a)


def _mk_cfg(blocks: list[BasicBlock]) -> CFG:
    return CFG(
        entry=blocks[0],
        blocks=blocks,
        exit_blocks=[b for b in blocks if not b.successors],
        blocks_by_offset={b.start_offset: b for b in blocks},
    )


# ── no loops ───────────────────────────────────────────────────────────────


def test_no_loops_in_linear_cfg():
    b0, b1, b2 = (_mk_bb(i, i) for i in range(3))
    _link(b0, b1)
    _link(b1, b2)
    cfg = _mk_cfg([b0, b1, b2])

    loops = find_loops(cfg, compute_idom(cfg))

    assert loops == []


def test_no_loops_in_diamond():
    # 0 -> {1, 2} -> 3
    b = [_mk_bb(i, i) for i in range(4)]
    _link(b[0], b[1]); _link(b[0], b[2])
    _link(b[1], b[3]); _link(b[2], b[3])
    cfg = _mk_cfg(b)

    loops = find_loops(cfg, compute_idom(cfg))

    assert loops == []


# ── single loop ────────────────────────────────────────────────────────────


def test_single_while_loop():
    #   0 -> 1 -> 2
    #        ^    |
    #        +----+   (back-edge 2 -> 1)
    #        1 -> 3   (exit)
    b = [_mk_bb(i, i) for i in range(4)]
    _link(b[0], b[1])
    _link(b[1], b[2])
    _link(b[1], b[3])
    _link(b[2], b[1])   # back-edge
    cfg = _mk_cfg(b)

    loops = find_loops(cfg, compute_idom(cfg))

    assert len(loops) == 1
    loop = loops[0]
    assert loop.header is b[1]
    assert loop.tail is b[2]
    assert loop.body == frozenset({b[1], b[2]})
    assert loop.exits == [b[1]]     # only b[1] has a successor outside body
    assert loop.parent is None


def test_self_loop_counts_as_loop():
    # 0 -> 1 -> 2 ;  1 -> 1
    b = [_mk_bb(i, i) for i in range(3)]
    _link(b[0], b[1])
    _link(b[1], b[2])
    _link(b[1], b[1])   # self-loop
    cfg = _mk_cfg(b)

    loops = find_loops(cfg, compute_idom(cfg))

    assert len(loops) == 1
    loop = loops[0]
    assert loop.header is b[1]
    assert loop.tail is b[1]
    assert loop.body == frozenset({b[1]})
    assert loop.exits == [b[1]]


# ── nested loops ───────────────────────────────────────────────────────────


def test_nested_loops_have_parent_child_relation():
    # outer header = 1, outer tail = 4
    # inner header = 2, inner tail = 3
    #
    #   0 -> 1 -> 2 -> 3 -> 4 -> 5 (exit)
    #             ^    |    |
    #             +----+    |     inner back-edge 3 -> 2
    #        ^              |
    #        +--------------+     outer back-edge 4 -> 1
    b = [_mk_bb(i, i) for i in range(6)]
    _link(b[0], b[1])
    _link(b[1], b[2])
    _link(b[2], b[3])
    _link(b[3], b[2])     # inner back-edge
    _link(b[3], b[4])
    _link(b[4], b[1])     # outer back-edge
    _link(b[4], b[5])
    cfg = _mk_cfg(b)

    loops = find_loops(cfg, compute_idom(cfg))

    assert len(loops) == 2
    headers = {loop.header.index: loop for loop in loops}
    outer = headers[1]
    inner = headers[2]

    assert outer.body == frozenset({b[1], b[2], b[3], b[4]})
    assert inner.body == frozenset({b[2], b[3]})
    assert inner.parent is outer
    assert outer.parent is None


# ── tree ───────────────────────────────────────────────────────────────────


def test_build_loop_tree_groups_children_under_parent():
    # Reuse nested-loop graph.
    b = [_mk_bb(i, i) for i in range(6)]
    _link(b[0], b[1]); _link(b[1], b[2]); _link(b[2], b[3])
    _link(b[3], b[2]); _link(b[3], b[4]); _link(b[4], b[1]); _link(b[4], b[5])
    cfg = _mk_cfg(b)
    loops = find_loops(cfg, compute_idom(cfg))

    tree = build_loop_tree(loops)

    top = tree.top_level_loops()
    assert len(top) == 1
    outer = top[0]
    assert outer.header.index == 1
    children = tree.children_of(outer)
    assert len(children) == 1
    assert children[0].header.index == 2


def test_build_loop_tree_handles_sibling_loops():
    # Two independent loops under entry:
    #   0 -> 1 -> 2 (back to 1)
    #   0 -> 3 -> 4 (back to 3)
    b = [_mk_bb(i, i) for i in range(5)]
    _link(b[0], b[1]); _link(b[1], b[2]); _link(b[2], b[1])
    _link(b[0], b[3]); _link(b[3], b[4]); _link(b[4], b[3])
    cfg = _mk_cfg(b)

    loops = find_loops(cfg, compute_idom(cfg))
    tree = build_loop_tree(loops)

    top = tree.top_level_loops()
    assert {loop.header.index for loop in top} == {1, 3}
    for loop in top:
        assert tree.children_of(loop) == []


# ── multiple back-edges to the same header merge into one loop ────────────


def test_multiple_back_edges_to_same_header_merge_into_one_loop():
    # Two tails (2, 3) both branch back to header 1. This is standard
    # AS3 compiler output for while loops with `continue` statements.
    #
    #   0 -> 1 -> 2 -> 1
    #             -> 3 -> 1
    #             1 -> 4 (exit)
    b = [_mk_bb(i, i) for i in range(5)]
    _link(b[0], b[1])
    _link(b[1], b[2])
    _link(b[2], b[1])      # back-edge 1
    _link(b[2], b[3])
    _link(b[3], b[1])      # back-edge 2
    _link(b[1], b[4])
    cfg = _mk_cfg(b)

    loops = find_loops(cfg, compute_idom(cfg))

    assert len(loops) == 1
    loop = loops[0]
    assert loop.header is b[1]
    # Body contains all blocks that reach either tail without going
    # through header: {1, 2, 3}.
    assert loop.body == frozenset({b[1], b[2], b[3]})


# ── exits ──────────────────────────────────────────────────────────────────


def test_loop_exits_reports_blocks_with_outside_successors():
    # Single loop with two exit edges:
    #   0 -> 1 -> 2 -> 3 -> 4
    #             ^    ^
    #             +----+       back-edge 3 -> 2
    #             1 -> 4       (bypass)
    # Actually let's make exits more interesting:
    #   0 -> 1 -> 2 -> 3 (back-edge)  and 2 has an extra edge to 4 (exit)
    #                                and 3 has an extra edge to 5 (exit)
    b = [_mk_bb(i, i) for i in range(6)]
    _link(b[0], b[1])
    _link(b[1], b[2])
    _link(b[2], b[3])
    _link(b[3], b[1])     # back-edge
    _link(b[2], b[4])     # first exit from loop (from block 2)
    _link(b[3], b[5])     # second exit (from block 3)
    cfg = _mk_cfg(b)

    loops = find_loops(cfg, compute_idom(cfg))

    assert len(loops) == 1
    loop = loops[0]
    assert loop.header is b[1]
    assert loop.body == frozenset({b[1], b[2], b[3]})
    assert set(loop.exits) == {b[2], b[3]}


# ── opt-in real-SWF smoke ──────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("FLASHKIT_TEST_SWF"),
    reason="opt-in: set FLASHKIT_TEST_SWF=path/to/file.swf",
)
def test_real_swf_every_method_loop_detection_terminates():
    from flashkit.abc.disasm import decode_instructions
    from flashkit.graph.cfg import build_cfg_from_bytecode
    from flashkit.workspace import Workspace

    ws = Workspace()
    ws.load_swf(os.environ["FLASHKIT_TEST_SWF"])

    total = 0
    total_loops = 0
    for abc in ws.abc_blocks:
        for body in abc.method_bodies:
            cfg = build_cfg_from_bytecode(
                decode_instructions(body.code), list(body.exceptions),
            )
            if not cfg.blocks:
                continue
            idom = compute_idom(cfg)
            loops = find_loops(cfg, idom)
            for loop in loops:
                # header is always in body
                assert loop.header in loop.body
                # tail is always in body
                assert loop.tail in loop.body
                # tail has the header as a successor (by definition of back-edge)
                assert loop.header in loop.tail.successors
            total += 1
            total_loops += len(loops)

    assert total > 0
    # Every non-trivial SWF has at least some loops.
    assert total_loops > 0
