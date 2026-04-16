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
from ..graph.cfg import build_cfg_from_bytecode
from ..graph.dominators import compute_idom, compute_ipostdom
from ..graph.loops import find_loops
from .ast.printer import AstPrinter
from .patterns import apply_patterns
from .stack import BlockStackSim
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

            sim = BlockStackSim(
                self._raw_abc,
                local0_name=class_name if (is_static and class_name) else "this",
            ) if _sim_accepts_local0() else BlockStackSim(self._raw_abc)
            block_results = {bb.index: sim.run(bb) for bb in cfg.blocks}

            root = structure_method(cfg, idom, ipostdom, loops, block_results)
            root = apply_patterns(root)
            printed = AstPrinter().print(root)
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
        # List-like: scan for the matching body.method.
        for b in mbs:
            if getattr(b, "method", None) == method_idx:
                return b
        return None


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


def _sim_accepts_local0() -> bool:
    """Feature-flag: later the stack simulator can be extended to take
    a ``local0_name`` so static-method bodies show the class name
    instead of ``this``. Until that lands the simulator always uses
    ``this`` for local-0 and callers that need the class-name
    substitution should post-process with ``str.replace``."""
    return False
