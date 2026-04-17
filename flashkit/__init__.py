"""
flashkit — SWF/ABC toolkit for parsing, analyzing, and manipulating Flash files.

A Python library for working with Adobe Flash SWF containers and AVM2
bytecode. Provides low-level binary parsing with round-trip fidelity,
a rich resolved class model, and analysis tools for inheritance graphs,
call graphs, cross-references, and string search.

Packages:
    swf: SWF container format (parse, build, tag types).
    abc: AVM2 bytecode (parse, write, constants, data types).
    info: Rich resolved model (ClassInfo, FieldInfo, MethodInfo).
    workspace: Loaded binary workspace (SWF/SWZ resources).
    analysis: Inheritance graph, call graph, references, strings.
Quick start::

    from flashkit import parse_swf, parse_abc, serialize_abc

    header, tags, version, length = parse_swf(swf_bytes)
    abc = parse_abc(abc_bytes)
    output = serialize_abc(abc)
"""

__version__ = "1.3.0"

from .errors import (
    FlashkitError, ParseError, SWFParseError,
    ABCParseError, SerializeError, ResourceError,
)
from .swf.parser import parse_swf
from .swf.builder import rebuild_swf, make_doabc2_tag
from .abc.parser import parse_abc
from .abc.writer import serialize_abc
from .abc.types import AbcFile
from .workspace.workspace import Workspace
from .info.class_info import ClassInfo

__all__ = [
    "__version__",
    # Errors
    "FlashkitError",
    "ParseError",
    "SWFParseError",
    "ABCParseError",
    "SerializeError",
    "ResourceError",
    # Core API
    "parse_swf",
    "rebuild_swf",
    "make_doabc2_tag",
    "parse_abc",
    "serialize_abc",
    "AbcFile",
    "Workspace",
    "ClassInfo",
]
