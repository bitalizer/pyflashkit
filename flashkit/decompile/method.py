"""Single-method AVM2 bytecode decompiler.

Orchestrates the CFG-based pipeline:

    bytecode
      -> decoded instructions        (flashkit.abc.disasm)
      -> basic blocks + CFG          (flashkit.graph.cfg)
      -> dominator / post-dominator  (flashkit.graph.dominators)
      -> natural loops               (flashkit.graph.loops)
      -> per-block AST (stack sim)   (flashkit.decompile.stack)
      -> structured AST              (flashkit.decompile.structure)
      -> idiomatic rewrites          (flashkit.decompile.patterns)
      -> AS3 source                  (flashkit.decompile.ast.printer)

This module's public entry point — ``MethodDecompiler.decompile`` —
preserves the existing signature so callers (``AS3Decompiler`` in
``class_.py``, ``DecompilerCache`` in ``cache.py``, the CLI) continue
to work unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Union

from ..abc.disasm import decode_instructions
from ..graph.cfg import CFG, build_cfg_from_bytecode
from ..graph.dominators import compute_idom, compute_ipostdom, reverse_postorder
from ..graph.loops import find_loops
from .ast.nodes import Expression, Identifier
from .ast.printer import AstPrinter
from .patterns import apply_patterns
from .stack import BlockSimResult, BlockStackSim
from .structure import structure_method

if TYPE_CHECKING:
    from ..abc.types import AbcFile

log = logging.getLogger(__name__)

__all__ = ["MethodDecompiler"]


class MethodDecompiler:
    """Decompile a single AVM2 method body into AS3 source.

    The instance is cheap to construct (just stores the ABC reference);
    each ``decompile(method_idx, ...)`` call runs the full pipeline
    from bytecode to source on that one method.
    """

    def __init__(self, abc) -> None:
        self.abc = abc
        # ``abc`` may be a raw ``AbcFile`` or the internal ``_adapter.AbcView``
        # used by ``class_.py``. The stack simulator reads bytecode pools via
        # the raw AbcFile; ``_abc`` is the underlying object in either case.
        self._raw_abc = getattr(abc, "_abc", abc)

    def decompile(
        self,
        method_idx: int,
        indent: str = "    ",
        class_idx: int = -1,
        is_static: bool = False,
        class_name: str = "",
    ) -> str:
        """Decompile one method body to AS3 source.

        Args:
            method_idx: Index into ``AbcFile.methods``.
            indent: Leading indent applied to every line of the output.
                The outer braces of the body are stripped; only the
                statements (indented one level relative to ``indent``)
                are emitted.
            class_idx: Unused by this implementation; kept for API
                compatibility.
            is_static: When ``True`` and ``class_name`` is non-empty,
                local-register-0 names this class instead of ``this``
                (static methods have the class object in local 0).
            class_name: Identifier to substitute for local-0 in a
                static method.

        Returns:
            AS3 source as a string. Empty string if the body is
            trivial (a single ``returnvoid`` with no other work).
        """
        body = self._get_body(method_idx)
        if body is None:
            return ""

        try:
            instrs = decode_instructions(body.code)
            cfg = build_cfg_from_bytecode(instrs, list(body.exceptions))
            if not cfg.blocks:
                return ""

            idom = compute_idom(cfg)
            ipostdom = compute_ipostdom(cfg)
            loops = find_loops(cfg, idom)

            param_count = self._param_count_of(method_idx)
            sim = BlockStackSim(
                self._raw_abc,
                param_count=param_count,
                local0_name=(class_name if (is_static and class_name)
                             else "this"),
            )
            block_results = _simulate_all_blocks(cfg, sim)

            root = structure_method(cfg, idom, ipostdom, loops, block_results)
            root = apply_patterns(root)
            printed = AstPrinter().print(root)
        # Broad catch is intentional: the decompiler pipeline runs
        # across CFG, dominators, stack sim, structurer, and pattern
        # rewrites — any of them can raise novel internal errors on
        # adversarial bytecode. Surface as a comment in the output so
        # callers keep working rather than abort a batch decompile.
        except Exception as exc:  # noqa: BLE001
            log.warning("decompile(method=%d) failed: %s", method_idx, exc)
            return f"{indent}// decompile error: {exc}\n"

        return _reindent_body(printed, indent)

    # ── helpers ────────────────────────────────────────────────────────────

    def _get_body(self, method_idx: int):
        """Look up a method body via whichever API the wrapped ABC exposes.

        Flashkit's raw ``AbcFile`` exposes ``method_bodies`` as a list
        (index = position), while ``_adapter.AbcView`` wraps it in a
        dict-like with ``.get(method_idx)``.
        """
        mbs = self.abc.method_bodies
        getter = getattr(mbs, "get", None)
        if callable(getter):
            return getter(method_idx)
        for b in mbs:
            if getattr(b, "method", None) == method_idx:
                return b
        return None

    def _param_count_of(self, method_idx: int) -> int:
        """Number of declared parameters on the given method, or 0 when
        the method table is absent or the index is out of range."""
        methods = getattr(self._raw_abc, "methods", None)
        if not methods or not (0 <= method_idx < len(methods)):
            return 0
        m = methods[method_idx]
        return int(getattr(m, "param_count", 0) or 0)


# ── cross-block stack dataflow ────────────────────────────────────────────


def _simulate_all_blocks(
    cfg: CFG,
    sim: BlockStackSim,
) -> dict[int, BlockSimResult]:
    """Run the stack simulator on every block in forward dataflow order.

    Each block's entry stack is the *meet* of its predecessors' exit
    stacks. This is what lets a conditional like ``iftrue`` find its
    operand on the stack when the value was pushed in a predecessor
    block (the common ``getlex``-then-``iftrue`` split across the
    fall-through edge). Without this pass the stack simulator starts
    every block with an empty stack and falls back to
    ``Identifier("_unknown")`` for the missing operand.

    Algorithm:

    * Iterate reverse-postorder so predecessors are processed before
      successors on all forward edges. Loop back-edges are the only
      place where a successor can be visited before one of its
      predecessors.
    * Start unvisited predecessor contributions as ``None`` (bottom).
      The meet ignores ``None`` contributors, so a loop header on its
      first pass sees only the forward-edge predecessor.
    * After one RPO pass, repeat until the set of block-exit stacks
      stops changing. In practice reducible CFGs converge in one or
      two passes; a small iteration cap guards pathological cases.
    """
    order = reverse_postorder(cfg.entry, cfg.blocks)
    exit_stacks: dict[int, list[Expression] | None] = {
        bb.index: None for bb in cfg.blocks
    }
    results: dict[int, BlockSimResult] = {}

    # Bound the worklist; each extra pass only helps irreducible CFGs
    # and loop back-edges that change an operand shape. Anything beyond
    # a handful of passes means the fixpoint isn't actually stable —
    # bail out and keep whatever we have.
    for _ in range(8):
        changed = False
        for idx in order:
            bb = cfg.blocks[idx]  # blocks are indexed by position
            entry = _meet_predecessors(bb, exit_stacks)
            res = sim.run(bb, entry_stack=entry)
            if exit_stacks[idx] != res.stack:
                exit_stacks[idx] = list(res.stack)
                changed = True
            results[idx] = res
        if not changed:
            break

    # Unreachable blocks (not in RPO) still need a result entry for the
    # structurer. They never execute, so an empty entry stack is fine.
    for bb in cfg.blocks:
        if bb.index not in results:
            results[bb.index] = sim.run(bb)

    return results


def _meet_predecessors(
    bb,
    exit_stacks: dict[int, list[Expression] | None],
) -> list[Expression]:
    """Merge predecessor exit stacks into a single entry stack.

    AVM2 is verified to have matching stack heights at every merge
    point, so we take the shortest non-``None`` predecessor height as
    ground truth. Slot-by-slot: if every contributing predecessor
    agrees on the AST value, keep it; otherwise emit a synthetic name
    so the value is still a real expression (``_s{depth}_b{block}``)
    and not ``_unknown``. The printer renders it as a plain identifier
    which is at least reconstructible from context.
    """
    contribs = [
        exit_stacks[p.index] for p in bb.predecessors
        if exit_stacks[p.index] is not None
    ]
    if not contribs:
        return []

    min_depth = min(len(s) for s in contribs)
    merged: list[Expression] = []
    for depth in range(min_depth):
        values = [s[depth] for s in contribs]
        first = values[0]
        if all(_ast_equal(v, first) for v in values[1:]):
            merged.append(first)
        else:
            merged.append(Identifier(f"_s{depth}_b{bb.index}"))
    return merged


def _ast_equal(a: Expression, b: Expression) -> bool:
    """Structural equality on AST nodes.

    Dataclass ``__eq__`` covers field-by-field comparison; we guard on
    type first so unrelated subclasses don't try to compare across each
    other. Any exception from non-dataclass nodes falls back to
    identity — the safe answer ("not equal") for the meet.
    """
    if type(a) is not type(b):
        return False
    try:
        return a == b
    # Non-dataclass AST nodes with custom __eq__ can raise on mismatched
    # operand types. Fall back to identity so meet stays total.
    except Exception:  # noqa: BLE001
        return a is b


# ── output shaping ─────────────────────────────────────────────────────────


def _reindent_body(printed: str, indent: str) -> str:
    """Strip the outer braces emitted by ``AstPrinter`` for a
    ``BlockStmt`` and re-indent the body to match the caller's
    requested indent level.

    The printer emits::

        {
            stmt1;
            stmt2;
        }

    Callers expect just::

            stmt1;
            stmt2;

    (with ``indent`` applied to every line). Empty output or output
    containing only the braces collapses to the empty string.
    """
    lines = printed.split("\n")
    # Drop leading ``{`` and trailing ``}`` that wrap the top-level block.
    if lines and lines[0].lstrip() == "{":
        lines = lines[1:]
    if lines and lines[-1].rstrip() == "}":
        lines = lines[:-1]
    # The printer indents body statements by 4 spaces. Strip that prefix
    # so we can re-indent with the caller's chosen string.
    stripped: list[str] = []
    for line in lines:
        if line.startswith("    "):
            stripped.append(line[4:])
        else:
            stripped.append(line)
    if not any(s.strip() for s in stripped):
        return ""
    return "\n".join(f"{indent}{s}" if s else "" for s in stripped) + "\n"


