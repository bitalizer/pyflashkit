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
"""

from .inheritance import InheritanceGraph
from .call_graph import CallGraph, CallEdge
from .references import ReferenceIndex, Reference
from .strings import StringIndex, StringUsage
from .field_access import FieldAccessIndex, FieldAccess
from .unified import build_all_indexes

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
    "build_all_indexes",
]
