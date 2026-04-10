"""
SWF tag definitions and constants.

Defines the ``SWFTag`` dataclass and well-known SWF tag type IDs.
The tag type constants eliminate magic numbers when working with
parsed SWF tag lists.

Reference: SWF File Format Specification v19, Chapter 2 (SWF structure).
"""

from __future__ import annotations

from dataclasses import dataclass


# ── Tag type constants ──────────────────────────────────────────────────────

TAG_END                            = 0
TAG_SHOW_FRAME                     = 1
TAG_SET_BACKGROUND_COLOR           = 9
TAG_DEFINE_SHAPE                   = 2
TAG_DEFINE_BITS                    = 6
TAG_DEFINE_BUTTON                  = 7
TAG_JPEG_TABLES                    = 8
TAG_DEFINE_TEXT                    = 11
TAG_DO_ACTION                      = 12
TAG_DEFINE_SOUND                   = 14
TAG_DEFINE_BITS_LOSSLESS           = 20
TAG_DEFINE_BITS_JPEG2              = 21
TAG_PLACE_OBJECT2                  = 26
TAG_REMOVE_OBJECT2                 = 28
TAG_DEFINE_SHAPE3                  = 32
TAG_DEFINE_TEXT2                   = 33
TAG_DEFINE_BITS_JPEG3              = 35
TAG_DEFINE_BITS_LOSSLESS2          = 36
TAG_DEFINE_EDIT_TEXT               = 37
TAG_DEFINE_SPRITE                  = 39
TAG_FRAME_LABEL                    = 43
TAG_DEFINE_MORPH_SHAPE             = 46
TAG_DEFINE_FONT2                   = 48
TAG_EXPORT_ASSETS                  = 56
TAG_IMPORT_ASSETS                  = 57
TAG_DO_INIT_ACTION                 = 59
TAG_DEFINE_VIDEO_STREAM            = 60
TAG_DEFINE_FONT3                   = 75
TAG_SCRIPT_LIMITS                  = 65
TAG_FILE_ATTRIBUTES                = 69
TAG_PLACE_OBJECT3                  = 70
TAG_DO_ABC                         = 72   # Raw ABC bytecode (AVM2)
TAG_SYMBOL_CLASS                   = 76   # Maps character IDs to class names
TAG_DEFINE_BINARY_DATA             = 77
TAG_DO_ABC2                        = 82   # Named ABC bytecode (flags + name + ABC)
TAG_DEFINE_SCENE_AND_FRAME_LABEL   = 86
TAG_DEBUG_ID                       = 255

# ── Human-readable tag names ────────────────────────────────────────────────

TAG_NAMES: dict[int, str] = {
    TAG_END: "End",
    TAG_SHOW_FRAME: "ShowFrame",
    TAG_SET_BACKGROUND_COLOR: "SetBackgroundColor",
    TAG_DEFINE_SHAPE: "DefineShape",
    TAG_DEFINE_BITS: "DefineBits",
    TAG_DEFINE_BUTTON: "DefineButton",
    TAG_JPEG_TABLES: "JPEGTables",
    TAG_DEFINE_TEXT: "DefineText",
    TAG_DO_ACTION: "DoAction",
    TAG_DEFINE_SOUND: "DefineSound",
    TAG_DEFINE_BITS_LOSSLESS: "DefineBitsLossless",
    TAG_DEFINE_BITS_JPEG2: "DefineBitsJPEG2",
    TAG_PLACE_OBJECT2: "PlaceObject2",
    TAG_REMOVE_OBJECT2: "RemoveObject2",
    TAG_DEFINE_SHAPE3: "DefineShape3",
    TAG_DEFINE_TEXT2: "DefineText2",
    TAG_DEFINE_BITS_JPEG3: "DefineBitsJPEG3",
    TAG_DEFINE_BITS_LOSSLESS2: "DefineBitsLossless2",
    TAG_DEFINE_EDIT_TEXT: "DefineEditText",
    TAG_DEFINE_SPRITE: "DefineSprite",
    TAG_FRAME_LABEL: "FrameLabel",
    TAG_DEFINE_MORPH_SHAPE: "DefineMorphShape",
    TAG_DEFINE_FONT2: "DefineFont2",
    TAG_EXPORT_ASSETS: "ExportAssets",
    TAG_IMPORT_ASSETS: "ImportAssets",
    TAG_DO_INIT_ACTION: "DoInitAction",
    TAG_DEFINE_VIDEO_STREAM: "DefineVideoStream",
    TAG_DEFINE_FONT3: "DefineFont3",
    TAG_SCRIPT_LIMITS: "ScriptLimits",
    TAG_FILE_ATTRIBUTES: "FileAttributes",
    TAG_PLACE_OBJECT3: "PlaceObject3",
    TAG_DO_ABC: "DoABC",
    TAG_SYMBOL_CLASS: "SymbolClass",
    TAG_DEFINE_BINARY_DATA: "DefineBinaryData",
    TAG_DO_ABC2: "DoABC2",
    TAG_DEFINE_SCENE_AND_FRAME_LABEL: "DefineSceneAndFrameLabelData",
    TAG_DEBUG_ID: "DebugID",
}


# ── SWFTag dataclass ────────────────────────────────────────────────────────

@dataclass(slots=True)
class SWFTag:
    """A single tag from a SWF file.

    SWF files are a sequence of typed tags. Each tag has a type ID,
    a payload, and optionally a name (for DoABC2 tags).

    Attributes:
        tag_type: Numeric tag type ID (see TAG_* constants).
        payload: Raw tag payload bytes.
        name: Tag name string (populated for DoABC2 tags).
    """
    tag_type: int
    payload: bytes
    name: str = ""

    @property
    def type_name(self) -> str:
        """Human-readable tag type name."""
        return TAG_NAMES.get(self.tag_type, f"Unknown({self.tag_type})")
