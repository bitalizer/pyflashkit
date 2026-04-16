"""CFG-based structuring: convert a CFG + per-block AST into a tree
of structured AS3 statements.

The algorithm is a post-dominator–driven recursive descent:

- For each region, structure starts at the region's entry and walks
  forward along the "main path", emitting statements.
- When it hits a loop header, it emits a ``WhileStmt`` wrapping the
  loop body (recursively structured with the header itself as the
  inner stop-block, so back-edges terminate the inner walk).
- When it hits a conditional branch whose immediate post-dominator
  is in the current region, it emits an ``IfStmt`` with each arm
  structured up to the post-dominator, then continues from the
  post-dominator.
- When both arms of a conditional terminate (return/throw), the
  post-dominator is ``-1``; we emit the ``if`` with no else, embed
  the then-arm, and inline the false branch after the if.
- Straight-line blocks emit their statements and flow to their single
  successor.

Out of scope for this phase: switch reconstruction (Phase 7),
exception regions (Phase 7), irreducible CFGs (Phase 7). A
conditional whose post-dominator is ``-1`` and neither arm terminates
is currently treated as the "infinite divergence" case — both arms
are inlined one after another, which produces a valid (though
un-idiomatic) structuring.
"""

from __future__ import annotations

from typing import Optional

from ..graph.cfg import CFG, BasicBlock
from ..graph.loops import Loop
from .ast.nodes import (
    BlockStmt, BreakStmt, IfStmt, Statement, WhileStmt,
)
from .stack import BlockSimResult


def structure_method(
    cfg: CFG,
    idom: dict[int, int],
    ipostdom: dict[int, int],
    loops: list[Loop],
    block_results: dict[int, BlockSimResult],
) -> BlockStmt:
    """Produce a structured AST from an already-analysed method.

    Args:
        cfg: The method's control-flow graph.
        idom: Immediate dominator map (``compute_idom``).
        ipostdom: Immediate post-dominator map (``compute_ipostdom``).
        loops: Output of ``find_loops``.
        block_results: Map from ``BasicBlock.index`` to the
            ``BlockSimResult`` produced by ``BlockStackSim`` for that
            block.

    Returns:
        A single ``BlockStmt`` representing the method body.
    """
    if not cfg.blocks:
        return BlockStmt([])

    ctx = _StructureContext(
        cfg=cfg,
        idom=idom,
        ipostdom=ipostdom,
        loops=loops,
        loop_by_header={loop.header.index: loop for loop in loops},
        block_results=block_results,
    )
    stmts = ctx.structure_region(cfg.entry, stop_at=None)
    return BlockStmt(stmts)


# ── internal state ─────────────────────────────────────────────────────────


class _StructureContext:
    """Holds analysis results so the recursion doesn't need to carry
    dozens of parameters."""

    def __init__(self, cfg, idom, ipostdom, loops, loop_by_header,
                 block_results):
        self.cfg = cfg
        self.idom = idom
        self.ipostdom = ipostdom
        self.loops = loops
        self.loop_by_header = loop_by_header
        self.block_results = block_results
        # Visited blocks within the current top-level recursion. Prevents
        # infinite loops on pathological input.
        self._emitted: set[int] = set()

    # ── block lookups ──────────────────────────────────────────────────────

    def _block_by_index(self, idx: int) -> Optional[BasicBlock]:
        if idx < 0 or idx >= len(self.cfg.blocks):
            return None
        return self.cfg.blocks[idx]

    def _in_loop_body(self, block: BasicBlock, loop: Loop) -> bool:
        return block in loop.body

    # ── recursion entry point ──────────────────────────────────────────────

    def structure_region(
        self,
        start: Optional[BasicBlock],
        stop_at: Optional[BasicBlock],
    ) -> list[Statement]:
        """Structure a region starting at ``start`` and stopping when
        we reach ``stop_at`` (or a terminator block)."""
        stmts: list[Statement] = []
        current = start

        while current is not None and current is not stop_at:
            if current.index in self._emitted:
                # Reached a block we've already emitted via a different
                # path — cut the recursion. In reducible CFGs this only
                # fires on back-edges of loops, which are handled by
                # structure_loop's stop_at=header sentinel before we
                # get here.
                break
            self._emitted.add(current.index)

            # Loop header? Emit the loop and continue from its exit.
            loop = self.loop_by_header.get(current.index)
            if loop is not None:
                stmts.append(self._structure_loop(loop))
                after = self._loop_continuation(loop)
                current = after
                continue

            block_result = self.block_results[current.index]
            terminator = block_result.terminator

            # Conditional branch.
            if terminator == "if":
                cond = block_result.branch_condition
                successors = current.successors
                if len(successors) < 2:
                    # Malformed: fall through to straight-line handling.
                    stmts.extend(block_result.statements)
                    current = successors[0] if successors else None
                    continue
                fall_through, branch_target = successors[0], successors[1]
                stmts.extend(block_result.statements)

                # Pick a merge point: the immediate post-dominator if it's
                # a real block.
                pdom_idx = self.ipostdom.get(current.index, -1)
                pdom = self._block_by_index(pdom_idx) if pdom_idx >= 0 else None

                # Structure both arms up to pdom.
                then_stmts = self.structure_region(fall_through, stop_at=pdom)
                else_stmts = self.structure_region(branch_target, stop_at=pdom)

                # In ffdec's idiom, the compiler emits ``iffalse`` when
                # the fall-through is the "then" arm (condition holds ->
                # fall through). Our simulator wraps iffalse in UnaryOp("!")
                # so that branch_condition is always "branch-taken-when-
                # truthy". Therefore: fall-through = !cond-taken = else
                # arm in the user's source. The ``then`` arm is
                # branch_target.
                #
                # Flip: emit ``if (!cond) { fall_stmts } else { branch_stmts }``
                # or equivalently ``if (cond_for_fall) { fall_stmts } ...``.
                # We keep the simpler form: if (!branch_cond) { fall } else { branch }.
                # But since most of our tests use iffalse that'd produce
                # ``if (!!(a == b))`` — double negation. Simplify by
                # stripping a leading ``!`` if present.
                display_cond, flipped = self._simplify_condition(cond)
                if flipped:
                    then_body_stmts = then_stmts
                    else_body_stmts = else_stmts
                else:
                    # branch_taken-when-truthy with no negation. The
                    # "then" arm is branch_target; the else arm is
                    # fall-through.
                    then_body_stmts = else_stmts
                    else_body_stmts = then_stmts

                stmts.append(_make_if(display_cond, then_body_stmts,
                                      else_body_stmts))

                # Continue from the merge point if there is one.
                current = pdom
                continue

            # Return/throw terminators: emit statements and stop this
            # region.
            if terminator in ("return", "throw"):
                stmts.extend(block_result.statements)
                current = None
                continue

            # Switch: Phase 7. For now, emit statements and stop.
            if terminator == "switch":
                stmts.extend(block_result.statements)
                current = None
                continue

            # Jump or fall-through: emit statements, continue with sole
            # successor.
            stmts.extend(block_result.statements)
            if current.successors:
                current = current.successors[0]
            else:
                current = None

        return stmts

    # ── loop structuring ──────────────────────────────────────────────────

    def _structure_loop(self, loop: Loop) -> Statement:
        """Structure a natural loop as a ``WhileStmt``.

        The loop body is structured with ``stop_at`` set to the header
        itself, so back-edges cut the inner walk. The loop's condition
        comes from the header block's terminator (which must be an
        ``if`` — a conditional branch where one successor is in the
        body and one is outside).
        """
        header = loop.header
        header_result = self.block_results[header.index]

        # Detect header type:
        # - "while" loop: header ends in a conditional branch, one
        #   successor is the body, one is the exit.
        # - "do-while" or infinite loop: header doesn't branch out; the
        #   tail contains the exit check. We treat these as ``while
        #   (true)`` and rely on ``break`` statements we insert at
        #   non-header exits.

        if header_result.terminator == "if" and len(header.successors) == 2:
            body_entry, exit_block = self._classify_loop_header_successors(
                loop, header,
            )
            if body_entry is not None and exit_block is not None:
                cond = header_result.branch_condition
                # Our branch_condition is "branch-taken-when-truthy".
                # If the branch-target is the exit, then the body is
                # entered when the condition is FALSE -> while (!cond).
                # If the branch-target is the body, loop while truthy.
                taken_target = header.successors[1]
                if taken_target is exit_block:
                    # Condition is "exit when taken"; loop condition is !cond.
                    loop_cond, _flipped = self._simplify_condition(_negate(cond))
                else:
                    loop_cond, _flipped = self._simplify_condition(cond)

                # Mark header as emitted so the inner recursion doesn't
                # re-emit its statements, then reset after.
                self._emitted.add(header.index)
                body_stmts = (
                    list(header_result.statements)
                    + self.structure_region(body_entry, stop_at=header)
                )
                return WhileStmt(loop_cond, BlockStmt(body_stmts))

        # Fallback: while(true) with the body being everything from the
        # header, stopped at the header itself (back-edge).
        self._emitted.add(header.index)
        body_stmts = (
            list(header_result.statements)
            + self.structure_region(
                header.successors[0] if header.successors else None,
                stop_at=header,
            )
        )
        from .ast.nodes import Literal
        return WhileStmt(Literal(True), BlockStmt(body_stmts))

    def _classify_loop_header_successors(self, loop, header):
        """For a conditional-branch loop header, identify which
        successor is inside the loop body and which is the exit."""
        s0, s1 = header.successors[0], header.successors[1]
        in_body_0 = s0 in loop.body
        in_body_1 = s1 in loop.body
        if in_body_0 and not in_body_1:
            return s0, s1
        if in_body_1 and not in_body_0:
            return s1, s0
        return None, None

    def _loop_continuation(self, loop: Loop) -> Optional[BasicBlock]:
        """Find the block that structuring should continue from after
        a loop. This is the loop's single exit target, if there's one.
        If there are multiple exits, we return the first in block-index
        order — structurer will emit ``break`` stmts where needed
        (Phase 7 will formalise this)."""
        header = loop.header
        if (header.successors and len(header.successors) == 2
                and self.block_results[header.index].terminator == "if"):
            body_entry, exit_block = self._classify_loop_header_successors(
                loop, header,
            )
            if exit_block is not None:
                return exit_block
        return None

    # ── condition simplification ──────────────────────────────────────────

    def _simplify_condition(self, cond):
        """Peel any number of leading ``!`` wrappers.

        Returns ``(simplified_cond, flipped)`` where ``flipped`` is
        ``True`` when an odd number of ``!`` were peeled (so the
        returned condition has opposite polarity and the caller should
        swap then/else arms).
        """
        from .ast.nodes import UnaryOp
        flipped = False
        while isinstance(cond, UnaryOp) and cond.op == "!":
            cond = cond.operand
            flipped = not flipped
        return cond, flipped


# ── helpers ────────────────────────────────────────────────────────────────


def _make_if(cond, then_stmts, else_stmts):
    """Build an ``IfStmt`` with the given arms, omitting an empty
    ``else`` arm."""
    then_body = BlockStmt(then_stmts)
    if not else_stmts:
        return IfStmt(cond, then_body, None)
    # Collapse ``else { if (...) }`` to ``else if (...)`` by placing
    # the inner IfStmt directly in else_body.
    if len(else_stmts) == 1 and isinstance(else_stmts[0], IfStmt):
        return IfStmt(cond, then_body, else_stmts[0])
    return IfStmt(cond, then_body, BlockStmt(else_stmts))


def _negate(cond):
    """Wrap ``cond`` in ``UnaryOp("!", ...)``; double negation is not
    peeled here — the caller uses ``_simplify_condition`` for that."""
    from .ast.nodes import UnaryOp
    return UnaryOp("!", cond)
