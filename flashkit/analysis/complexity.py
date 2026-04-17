"""Cyclomatic complexity for AS3 methods.

Uses the CFG already built by :mod:`flashkit.graph.cfg` to compute
``E - N + 2``, the standard McCabe formula. Switch cases contribute
one edge per case, matching the convention most static analysers
(radon, lizard, SonarQube) use.

Reads nothing new from the bytecode — takes a CFG and returns an int.
A separate ``method_complexity(abc, body)`` helper decodes + builds
the CFG for callers who don't already have one.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..abc.disasm import decode_instructions
from ..abc.types import AbcFile, MethodBodyInfo
from ..errors import ABCParseError
from ..graph.cfg import CFG, build_cfg_from_bytecode


__all__ = [
    "MethodComplexity",
    "cfg_complexity",
    "method_complexity",
]


@dataclass(frozen=True, slots=True)
class MethodComplexity:
    """Cyclomatic complexity and shape stats for one method."""
    method_index: int
    complexity: int
    block_count: int
    edge_count: int
    exit_count: int


def cfg_complexity(cfg: CFG) -> int:
    """Return the McCabe cyclomatic complexity of ``cfg``.

    Formula: ``E - N + 2``, where ``E`` is the edge count across all
    blocks, ``N`` is the block count, and ``2`` accounts for the
    entry/exit virtual nodes. Empty CFGs (no blocks) map to 1, the
    floor value — a method that just returns is still "one path."
    """
    if not cfg.blocks:
        return 1
    edges = sum(len(b.successors) for b in cfg.blocks)
    nodes = len(cfg.blocks)
    return max(1, edges - nodes + 2)


def method_complexity(abc: AbcFile,
                      body: MethodBodyInfo) -> MethodComplexity | None:
    """Compute :class:`MethodComplexity` for one method body.

    Returns ``None`` if the body can't be decoded. Constructs the CFG
    via :func:`build_cfg_from_bytecode`, so this costs one bytecode
    pass per call — reuse an already-built CFG via
    :func:`cfg_complexity` if you have one.
    """
    try:
        instrs = decode_instructions(body.code)
    except (ABCParseError, IndexError, ValueError):
        return None
    cfg = build_cfg_from_bytecode(instrs, list(body.exceptions))
    edges = sum(len(b.successors) for b in cfg.blocks)
    return MethodComplexity(
        method_index=body.method,
        complexity=cfg_complexity(cfg),
        block_count=len(cfg.blocks),
        edge_count=edges,
        exit_count=len(cfg.exit_blocks),
    )
