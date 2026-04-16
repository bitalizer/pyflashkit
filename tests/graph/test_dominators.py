"""Tests for dominator and post-dominator tree construction.

Each CFG is built by hand so the expected idom / ipostdom tables are
verifiable against textbook definitions:

- ``idom[b]``: the unique predecessor of ``b`` in the dominator tree;
  ``idom[entry] = entry``.
- ``ipostdom[b]``: the unique successor of ``b`` in the post-dominator
  tree; for every exit block, ``ipostdom[b] = b``.

Textbook references for the small-CFG cases are taken from Cooper,
Harvey, Kennedy (2001), "A Simple, Fast Dominance Algorithm", §3.
"""

from __future__ import annotations

import os

import pytest

from flashkit.graph.cfg import BasicBlock, CFG
from flashkit.graph.dominators import compute_idom, compute_ipostdom


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


# ── idom: trivial cases ────────────────────────────────────────────────────


def test_idom_single_block():
    b0 = _mk_bb(0)
    cfg = _mk_cfg([b0])

    idom = compute_idom(cfg)

    assert idom == {0: 0}  # entry self-dominates


def test_idom_linear_chain():
    # 0 -> 1 -> 2 -> 3
    b0, b1, b2, b3 = (_mk_bb(i, i) for i in range(4))
    _link(b0, b1)
    _link(b1, b2)
    _link(b2, b3)
    cfg = _mk_cfg([b0, b1, b2, b3])

    idom = compute_idom(cfg)

    assert idom == {0: 0, 1: 0, 2: 1, 3: 2}


# ── idom: if/else diamond ──────────────────────────────────────────────────


def test_idom_if_else_diamond():
    #       0
    #      / \
    #     1   2
    #      \ /
    #       3
    b0, b1, b2, b3 = (_mk_bb(i, i) for i in range(4))
    _link(b0, b1)
    _link(b0, b2)
    _link(b1, b3)
    _link(b2, b3)
    cfg = _mk_cfg([b0, b1, b2, b3])

    idom = compute_idom(cfg)

    assert idom[0] == 0
    assert idom[1] == 0
    assert idom[2] == 0
    assert idom[3] == 0  # merge's idom is the split


# ── idom: simple loop ──────────────────────────────────────────────────────


def test_idom_simple_while_loop():
    # 0 -> 1 -> 2      (1 is header; 2 can exit)
    #      ^    |
    #      +----+      (2 loops back to 1)
    #      1 -> 3      (exit)
    b0, b1, b2, b3 = (_mk_bb(i, i) for i in range(4))
    _link(b0, b1)
    _link(b1, b2)
    _link(b1, b3)
    _link(b2, b1)  # back-edge
    cfg = _mk_cfg([b0, b1, b2, b3])

    idom = compute_idom(cfg)

    assert idom[0] == 0
    assert idom[1] == 0
    assert idom[2] == 1
    assert idom[3] == 1


# ── idom: Cooper-Harvey-Kennedy Figure 2 textbook example ─────────────────


def test_idom_multi_predecessor_merge_point():
    # Merge after a diamond-with-tail, hand-verified:
    #
    #       0
    #      / \
    #     1   2
    #      \ / \
    #       3   4
    #       \   /
    #         5
    #
    # Edges: 0->1, 0->2, 1->3, 2->3, 2->4, 3->5, 4->5
    #
    # idom table:
    #   idom[0] = 0  (entry self-dominates)
    #   idom[1] = 0  (only pred is 0)
    #   idom[2] = 0  (only pred is 0)
    #   idom[3] = 0  (preds {1, 2} -> nearest common dominator is 0)
    #   idom[4] = 2  (only pred is 2)
    #   idom[5] = 0  (preds {3, 4}; 3's idom chain is 0, 4's is 2->0;
    #                nearest common is 0)
    b = [_mk_bb(i, i) for i in range(6)]
    _link(b[0], b[1])
    _link(b[0], b[2])
    _link(b[1], b[3])
    _link(b[2], b[3])
    _link(b[2], b[4])
    _link(b[3], b[5])
    _link(b[4], b[5])
    cfg = _mk_cfg(b)

    idom = compute_idom(cfg)

    assert idom == {0: 0, 1: 0, 2: 0, 3: 0, 4: 2, 5: 0}


# ── idom: unreachable block is reported as self-dominated ─────────────────


def test_idom_unreachable_block_has_no_dominator_entry():
    # 0 -> 1
    #      2    (unreachable)
    b0, b1, b2 = (_mk_bb(i, i) for i in range(3))
    _link(b0, b1)
    cfg = _mk_cfg([b0, b1, b2])

    idom = compute_idom(cfg)

    # Unreachable blocks get no idom entry (or map to themselves; we
    # choose "self" so every block has an entry, matching how the
    # structurer will want to treat dead code).
    assert idom[0] == 0
    assert idom[1] == 0
    assert idom[2] == 2


# ── ipostdom: trivial cases ────────────────────────────────────────────────


def test_ipostdom_single_block():
    b0 = _mk_bb(0)
    cfg = _mk_cfg([b0])

    ipostdom = compute_ipostdom(cfg)

    assert ipostdom == {0: 0}


def test_ipostdom_linear_chain():
    # 0 -> 1 -> 2 -> 3 (exit)
    # ipostdom: 3->3, 2->3, 1->2, 0->1
    b0, b1, b2, b3 = (_mk_bb(i, i) for i in range(4))
    _link(b0, b1)
    _link(b1, b2)
    _link(b2, b3)
    cfg = _mk_cfg([b0, b1, b2, b3])

    ipostdom = compute_ipostdom(cfg)

    assert ipostdom == {0: 1, 1: 2, 2: 3, 3: 3}


def test_ipostdom_if_else_diamond():
    #       0
    #      / \
    #     1   2
    #      \ /
    #       3 (exit)
    # 3 post-dominates everything; ipostdom[1]=3, ipostdom[2]=3, ipostdom[0]=3
    b0, b1, b2, b3 = (_mk_bb(i, i) for i in range(4))
    _link(b0, b1)
    _link(b0, b2)
    _link(b1, b3)
    _link(b2, b3)
    cfg = _mk_cfg([b0, b1, b2, b3])

    ipostdom = compute_ipostdom(cfg)

    assert ipostdom[3] == 3
    assert ipostdom[1] == 3
    assert ipostdom[2] == 3
    assert ipostdom[0] == 3


def test_ipostdom_multiple_exits():
    #     0
    #    / \
    #   1   2
    # both 1 and 2 are exits -> ipostdom[1]=1, ipostdom[2]=2.
    # ipostdom[0] in a graph with multiple exits is conventionally defined
    # against a virtual "super-exit"; we expose that as index -1 (no real
    # block).
    b0, b1, b2 = (_mk_bb(i, i) for i in range(3))
    _link(b0, b1)
    _link(b0, b2)
    cfg = _mk_cfg([b0, b1, b2])

    ipostdom = compute_ipostdom(cfg)

    assert ipostdom[1] == 1
    assert ipostdom[2] == 2
    # No block post-dominates 0 because its two successors diverge to
    # separate exits. We report -1 (super-exit sentinel).
    assert ipostdom[0] == -1


# ── property-based: every non-entry block's idom is one of its ancestors ─


def test_idom_block_dominates_its_own_children():
    # Small diamond-plus-tail:
    #     0
    #    / \
    #   1   2
    #    \ /
    #     3
    #     |
    #     4
    b = [_mk_bb(i, i) for i in range(5)]
    _link(b[0], b[1])
    _link(b[0], b[2])
    _link(b[1], b[3])
    _link(b[2], b[3])
    _link(b[3], b[4])
    cfg = _mk_cfg(b)

    idom = compute_idom(cfg)

    # Invariant: idom[b] must dominate b (trivially true for self), but
    # also the idom chain from any block must reach entry.
    for i in range(len(b)):
        seen = set()
        cur = i
        while idom[cur] != cur:
            assert cur not in seen, f"cycle in idom chain at {cur}"
            seen.add(cur)
            cur = idom[cur]
        assert cur == 0, f"idom chain from {i} did not reach entry"


# ── opt-in real-SWF smoke ──────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("FLASHKIT_TEST_SWF"),
    reason="opt-in: set FLASHKIT_TEST_SWF=path/to/file.swf",
)
def test_real_swf_every_method_has_valid_idom():
    from flashkit.abc.disasm import decode_instructions
    from flashkit.graph.cfg import build_cfg_from_bytecode
    from flashkit.workspace import Workspace

    ws = Workspace()
    ws.load_swf(os.environ["FLASHKIT_TEST_SWF"])

    total = 0
    for abc in ws.abc_blocks:
        for body in abc.method_bodies:
            instrs = decode_instructions(body.code)
            cfg = build_cfg_from_bytecode(instrs, list(body.exceptions))
            if not cfg.blocks:
                continue
            idom = compute_idom(cfg)
            # Every block has an entry; entry self-dominates; no cycles
            # in the idom chain of any reachable block.
            assert idom[cfg.entry.index] == cfg.entry.index
            for bb in cfg.blocks:
                assert bb.index in idom
                seen = set()
                cur = bb.index
                while idom[cur] != cur:
                    assert cur not in seen, (
                        f"idom cycle in method {body.method} at block {cur}"
                    )
                    seen.add(cur)
                    cur = idom[cur]
            total += 1

    assert total > 0
