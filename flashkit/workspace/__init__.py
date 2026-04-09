"""
Workspace and resource management.

A ``Workspace`` loads one or more SWF/SWZ files, extracts their ABC
bytecode, parses it, and builds a unified index of all classes, methods,
and strings. It is the top-level entry point for analysis.

A ``Resource`` represents a single loaded file (SWF or SWZ) with its
parsed tags and ABC content.
"""

from .resource import Resource, load_swf, load_swz
from .workspace import Workspace

__all__ = [
    "Workspace",
    "Resource",
    "load_swf",
    "load_swz",
]
