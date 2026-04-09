"""
Unified search and query engine.

Combines string search, reference lookup, inheritance queries, and
call graph traversal into a single interface for querying workspace
content.
"""

from .search import SearchEngine, ClassResult, MemberResult, StringResult

__all__ = [
    "SearchEngine",
    "ClassResult",
    "MemberResult",
    "StringResult",
]
