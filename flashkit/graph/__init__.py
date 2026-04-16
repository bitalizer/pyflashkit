"""Control-flow graph primitives for AVM2 bytecode.

This package is the foundation of the CFG-based decompiler rewrite. It
owns pure-graph concepts (basic blocks, dominators, loops) that are
independent of both bytecode semantics and AST construction.

Phase 1 exposes only the basic-block builder. Dominators and loops are
added in later phases.
"""

from .cfg import BasicBlock, CFG, build_cfg_from_bytecode
from .dominators import compute_idom, compute_ipostdom

__all__ = [
    "BasicBlock", "CFG", "build_cfg_from_bytecode",
    "compute_idom", "compute_ipostdom",
]
