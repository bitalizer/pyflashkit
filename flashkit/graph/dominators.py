"""Dominator and post-dominator tree construction.

Implements the iterative algorithm from Cooper, Harvey, and Kennedy,
"A Simple, Fast Dominance Algorithm" (2001). The algorithm runs in
O(N * alpha(N)) amortised time on real programs — in practice a small
constant factor over a single reverse-postorder traversal.

For post-dominators, we run the same algorithm on the reversed CFG.
When the CFG has multiple exit blocks (common for bytecode with
multiple ``return`` / ``throw`` points), a single block cannot
post-dominate the entry; those cases return the sentinel ``-1`` for
``ipostdom[block]``, matching the conventional "virtual super-exit"
treatment.

Unreachable blocks (no path from entry) get ``idom[b] = b``. This keeps
every block in the map so downstream phases can walk the idom chain
without guarding for missing keys. The structurer can detect
unreachable blocks separately via ``bb.predecessors == []`` on a
non-entry block.
"""

from __future__ import annotations

from .cfg import CFG, BasicBlock


def _reverse_postorder(entry: BasicBlock, blocks: list[BasicBlock]) -> list[int]:
    """Return block indices in reverse postorder starting from ``entry``.

    Only reachable blocks are included. Uses an explicit stack so deep
    method bodies don't blow the Python recursion limit.
    """
    post: list[int] = []
    visited: set[int] = set()
    # (block, iterator over successors)
    stack: list[tuple[BasicBlock, int]] = [(entry, 0)]
    visited.add(entry.index)
    while stack:
        bb, si = stack[-1]
        if si < len(bb.successors):
            stack[-1] = (bb, si + 1)
            succ = bb.successors[si]
            if succ.index not in visited:
                visited.add(succ.index)
                stack.append((succ, 0))
        else:
            post.append(bb.index)
            stack.pop()
    post.reverse()
    return post


def _compute_idom_generic(
    entry_index: int,
    all_indices: list[int],
    rpo: list[int],
    preds_of: dict[int, list[int]],
) -> dict[int, int]:
    """Cooper-Harvey-Kennedy on an abstract graph description.

    Args:
        entry_index: Index of the entry block.
        all_indices: Every block index (reachable or not).
        rpo: Reverse-postorder list of reachable block indices, starting
            with ``entry_index``.
        preds_of: Mapping from block index to the list of its predecessor
            indices in this graph.

    Returns:
        Mapping from every block index in ``all_indices`` to its
        immediate dominator. Unreachable blocks map to themselves.
    """
    # Position of each reachable block in rpo; lower rpo index = earlier.
    rpo_index: dict[int, int] = {idx: pos for pos, idx in enumerate(rpo)}

    idom: dict[int, int] = {entry_index: entry_index}

    def intersect(b1: int, b2: int) -> int:
        finger1, finger2 = b1, b2
        while finger1 != finger2:
            while rpo_index[finger1] > rpo_index[finger2]:
                finger1 = idom[finger1]
            while rpo_index[finger2] > rpo_index[finger1]:
                finger2 = idom[finger2]
        return finger1

    changed = True
    while changed:
        changed = False
        # Iterate in reverse postorder, skipping the entry block.
        for b in rpo[1:]:
            # Pick an already-processed predecessor.
            processed_preds = [p for p in preds_of.get(b, ()) if p in idom]
            if not processed_preds:
                continue
            new_idom = processed_preds[0]
            for p in processed_preds[1:]:
                new_idom = intersect(p, new_idom)
            if idom.get(b) != new_idom:
                idom[b] = new_idom
                changed = True

    # Unreachable blocks: self-dominate (no valid dominator chain).
    for idx in all_indices:
        idom.setdefault(idx, idx)

    return idom


def compute_idom(cfg: CFG) -> dict[int, int]:
    """Compute immediate dominators for every block.

    Args:
        cfg: The method's control-flow graph.

    Returns:
        Mapping ``block_index -> immediate_dominator_index``.
        ``idom[entry.index] == entry.index``. Unreachable blocks map to
        themselves.
    """
    if not cfg.blocks:
        return {}

    all_indices = [bb.index for bb in cfg.blocks]
    rpo = _reverse_postorder(cfg.entry, cfg.blocks)
    preds_of = {bb.index: [p.index for p in bb.predecessors] for bb in cfg.blocks}

    return _compute_idom_generic(
        entry_index=cfg.entry.index,
        all_indices=all_indices,
        rpo=rpo,
        preds_of=preds_of,
    )


def compute_ipostdom(cfg: CFG) -> dict[int, int]:
    """Compute immediate post-dominators for every block.

    A block ``b`` post-dominates ``a`` iff every path from ``a`` to any
    exit block passes through ``b``. When the CFG has multiple exit
    blocks that diverge above ``a``, no single block post-dominates
    ``a`` and this function returns ``-1`` for that entry (matching the
    conventional "super-exit" treatment).

    Args:
        cfg: The method's control-flow graph.

    Returns:
        Mapping ``block_index -> immediate_post_dominator_index``.
        Exit blocks map to themselves. Blocks with no path to any exit
        (e.g. an infinite loop with no return) and blocks where no
        single real block post-dominates map to ``-1``.
    """
    if not cfg.blocks:
        return {}

    exits = cfg.exit_blocks
    all_indices = [bb.index for bb in cfg.blocks]

    if not exits:
        # Every reachable block has no exit on any path — only possible
        # if the whole CFG is in an infinite loop. Return -1 for all.
        return {idx: -1 for idx in all_indices}

    if len(exits) == 1:
        # Single exit: run standard algorithm on the reversed CFG with
        # the exit as the "entry". In the reversed graph, block b's
        # predecessors are its original successors.
        exit_idx = exits[0].index
        reversed_rpo = _reverse_postorder_reverse_cfg(cfg, start=exits[0])
        preds_in_reverse = {
            bb.index: [s.index for s in bb.successors] for bb in cfg.blocks
        }
        ipd = _compute_idom_generic(
            entry_index=exit_idx,
            all_indices=all_indices,
            rpo=reversed_rpo,
            preds_of=preds_in_reverse,
        )
        return ipd

    # Multiple exits: introduce a virtual super-exit (sentinel index -1)
    # that is the successor of every real exit. Run the algorithm in
    # that augmented reversed graph, then strip the sentinel.
    SUPER_EXIT = -1
    augmented_all = all_indices + [SUPER_EXIT]

    # The reverse graph with a super-exit has:
    #   super-exit as entry, with edges super-exit -> every real exit,
    #   and every non-exit block b's reverse-edges = its original
    #   successors.
    # For CHK we need:
    #   - preds_of[b] in the reversed augmented graph
    #   - succs_of[b] in the reversed augmented graph (for RPO)
    exit_indices = {e.index for e in exits}

    # Successors in the augmented reverse graph (used only for RPO):
    #   super-exit -> every real exit
    #   every real block -> its original predecessors (reverse-edges)
    # Note: exits are *entries* of the reverse CFG, not leaves. Under
    # the augmentation they sit one hop below super-exit but still
    # propagate the traversal to their original predecessors.
    succs_in_aug: dict[int, list[int]] = {SUPER_EXIT: [e.index for e in exits]}
    for bb in cfg.blocks:
        succs_in_aug[bb.index] = [p.index for p in bb.predecessors]

    # Predecessors in the augmented reverse graph:
    #   super-exit: none
    #   real exit:  super-exit
    #   non-exit:   the block's original successors
    preds_of: dict[int, list[int]] = {SUPER_EXIT: []}
    for bb in cfg.blocks:
        if bb.index in exit_indices:
            preds_of[bb.index] = [SUPER_EXIT]
        else:
            preds_of[bb.index] = [s.index for s in bb.successors]

    rpo = _reverse_postorder_abstract(SUPER_EXIT, succs_in_aug)

    idom_augmented = _compute_idom_generic(
        entry_index=SUPER_EXIT,
        all_indices=augmented_all,
        rpo=rpo,
        preds_of=preds_of,
    )

    # In the augmented graph every real exit's immediate dominator is
    # SUPER_EXIT. In the non-augmented sense each exit post-dominates
    # itself, so override to self. For any other block mapped to
    # SUPER_EXIT, no real block post-dominates it — report -1.
    result: dict[int, int] = {}
    for idx in all_indices:
        ipd = idom_augmented.get(idx, idx)
        if ipd == SUPER_EXIT:
            result[idx] = idx if idx in exit_indices else -1
        else:
            result[idx] = ipd
    return result


def _reverse_postorder_reverse_cfg(
    cfg: CFG, start: BasicBlock,
) -> list[int]:
    """Reverse postorder over the reversed CFG, starting at ``start``."""
    succs = {bb.index: [p.index for p in bb.predecessors] for bb in cfg.blocks}
    return _reverse_postorder_abstract(start.index, succs)


def _reverse_postorder_abstract(
    start: int, succs: dict[int, list[int]],
) -> list[int]:
    """Iterative reverse postorder over an abstract graph."""
    post: list[int] = []
    visited: set[int] = {start}
    stack: list[tuple[int, int]] = [(start, 0)]
    while stack:
        node, si = stack[-1]
        children = succs.get(node, ())
        if si < len(children):
            stack[-1] = (node, si + 1)
            child = children[si]
            if child not in visited:
                visited.add(child)
                stack.append((child, 0))
        else:
            post.append(node)
            stack.pop()
    post.reverse()
    return post
