"""
SWF container format handling.

This package handles the SWF (Small Web Format) container — the file
format used by Adobe Flash Player. A SWF file is a sequence of typed
tags containing graphics, sounds, scripts (ABC bytecode), and metadata.

Quick start::

    from flashkit.swf import parse_swf, rebuild_swf, TAG_DO_ABC2

    header, tags, version, length = parse_swf(swf_bytes)
    output = rebuild_swf(header, tags, compress=True)
"""

from .tags import (
    SWFTag,
    TAG_NAMES,
    TAG_END,
    TAG_SHOW_FRAME,
    TAG_SET_BACKGROUND_COLOR,
    TAG_SCRIPT_LIMITS,
    TAG_FILE_ATTRIBUTES,
    TAG_DO_ABC,
    TAG_SYMBOL_CLASS,
    TAG_DEFINE_BINARY_DATA,
    TAG_DO_ABC2,
    TAG_DEFINE_SCENE_AND_FRAME_LABEL,
    TAG_DEBUG_ID,
)
from .parser import parse_swf, print_tags
from .builder import (
    build_tag_bytes,
    rebuild_swf,
    make_doabc2_tag,
    make_symbol_class_tag,
    make_end_tag,
    SwfBuilder,
)

__all__ = [
    # Tags
    "SWFTag",
    "TAG_NAMES",
    "TAG_END",
    "TAG_SHOW_FRAME",
    "TAG_SET_BACKGROUND_COLOR",
    "TAG_SCRIPT_LIMITS",
    "TAG_FILE_ATTRIBUTES",
    "TAG_DO_ABC",
    "TAG_SYMBOL_CLASS",
    "TAG_DEFINE_BINARY_DATA",
    "TAG_DO_ABC2",
    "TAG_DEFINE_SCENE_AND_FRAME_LABEL",
    "TAG_DEBUG_ID",
    # Parser
    "parse_swf",
    "print_tags",
    # Builder
    "build_tag_bytes",
    "rebuild_swf",
    "make_doabc2_tag",
    "make_symbol_class_tag",
    "make_end_tag",
    "SwfBuilder",
]
