"""
Analysis services for ABC content.

This package provides graph-based and index-based analysis of the loaded
ABC bytecode. Each module builds a specific data structure from the parsed
ABC data that enables efficient queries.

Modules:
    inheritance: InheritanceGraph — class hierarchy (parent/child/interface).
    call_graph: CallGraph — method-to-method call edges from bytecode.
    references: ReferenceIndex — cross-references (field types, instantiations, imports).
    strings: StringIndex — string constant search and classification.
    field_access: FieldAccessIndex — field read/write tracking from bytecode.
    method_fingerprint: MethodFingerprint — structural features of method bodies.
    class_graph: ClassGraph — class-to-class reference graph with typed edges.
    liveness: LocalLiveness — per-method register read/write summary.
    const_args: ConstArgIndex — literal arguments observed at call sites.
    dead_code: dead class / method detection + entry-point candidates.
    complexity: McCabe cyclomatic complexity for method bodies.
"""

from .inheritance import InheritanceGraph
from .call_graph import CallGraph, CallEdge
from .references import ReferenceIndex, Reference
from .strings import StringIndex, StringUsage
from .field_access import FieldAccessIndex, FieldAccess
from .method_fingerprint import (
    MethodFingerprint,
    extract_fingerprint,
    extract_constructor_fingerprint,
    extract_all_fingerprints,
)
from .class_graph import (
    ClassGraph,
    ClassNode,
    FRAMEWORK_TYPES,
    CLASS_EDGE_KINDS,
)
from .unified import build_all_indexes
from .liveness import LocalLiveness, method_liveness
from .const_args import ConstArgIndex, ConstArgObservation
from .dead_code import (
    DeadMethodReport,
    entrypoint_candidates,
    find_dead_classes,
    find_dead_methods,
    find_entrypoints_and_dead_classes,
)
from .complexity import MethodComplexity, cfg_complexity, method_complexity

__all__ = [
    "InheritanceGraph",
    "CallGraph",
    "CallEdge",
    "ReferenceIndex",
    "Reference",
    "StringIndex",
    "StringUsage",
    "FieldAccessIndex",
    "FieldAccess",
    "MethodFingerprint",
    "extract_fingerprint",
    "extract_constructor_fingerprint",
    "extract_all_fingerprints",
    "ClassGraph",
    "ClassNode",
    "FRAMEWORK_TYPES",
    "CLASS_EDGE_KINDS",
    "build_all_indexes",
    "LocalLiveness",
    "method_liveness",
    "ConstArgIndex",
    "ConstArgObservation",
    "DeadMethodReport",
    "entrypoint_candidates",
    "find_dead_classes",
    "find_dead_methods",
    "find_entrypoints_and_dead_classes",
    "MethodComplexity",
    "cfg_complexity",
    "method_complexity",
]
