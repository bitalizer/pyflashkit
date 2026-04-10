"""
Resource: a single loaded SWF or SWZ file.

A Resource holds the parsed content of one file — its SWF tags (if SWF),
the extracted AbcFile objects, and the resolved ClassInfo list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ResourceError
from ..abc.types import AbcFile
from ..abc.parser import parse_abc
from ..abc.writer import serialize_abc
from ..swf.tags import SWFTag, TAG_DO_ABC, TAG_DO_ABC2
from ..swf.parser import parse_swf
from ..info.class_info import ClassInfo, build_all_classes


@dataclass(slots=True)
class Resource:
    """A loaded SWF or SWZ file with parsed ABC content.

    Attributes:
        path: Original file path.
        kind: File type (``"swf"`` or ``"swz"``).
        swf_header: SWF header bytes (None for SWZ).
        swf_tags: SWF tag list (None for SWZ).
        swf_version: SWF version number (None for SWZ).
        abc_blocks: List of parsed AbcFile objects from this resource.
        classes: All ClassInfo objects resolved from the ABC blocks.
    """
    path: str = ""
    kind: str = "swf"
    swf_header: bytes | None = None
    swf_tags: list[SWFTag] | None = None
    swf_version: int | None = None
    abc_blocks: list[AbcFile] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)

    @property
    def class_count(self) -> int:
        return len(self.classes)

    @property
    def method_count(self) -> int:
        return sum(len(abc.methods) for abc in self.abc_blocks)

    @property
    def string_count(self) -> int:
        return sum(len(abc.string_pool) for abc in self.abc_blocks)


def _extract_abc_from_tag(tag: SWFTag) -> bytes | None:
    """Extract raw ABC bytes from a DoABC or DoABC2 tag."""
    if tag.tag_type == TAG_DO_ABC:
        return tag.payload
    elif tag.tag_type == TAG_DO_ABC2 and len(tag.payload) > 4:
        try:
            null_idx = tag.payload.index(0, 4)
            return tag.payload[null_idx + 1:]
        except ValueError:
            return None
    return None


def load_swf(path: str | Path) -> Resource:
    """Load a SWF file into a Resource.

    Parses the SWF, extracts all DoABC/DoABC2 tags, parses each into
    an AbcFile, and resolves all classes.

    Args:
        path: Path to the SWF file.

    Returns:
        Resource with all ABC content and resolved classes.

    Raises:
        ResourceError: If the file cannot be read or is not a valid SWF.
    """
    path = Path(path)
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise ResourceError(f"Cannot read SWF file '{path}': {e}") from e

    if not data:
        raise ResourceError(f"SWF file is empty: '{path}'")

    try:
        header, tags, version, file_length = parse_swf(data)
    except Exception as e:
        raise ResourceError(f"Failed to parse SWF '{path}': {e}") from e

    abc_blocks: list[AbcFile] = []
    all_classes: list[ClassInfo] = []

    for tag in tags:
        abc_data = _extract_abc_from_tag(tag)
        if abc_data and len(abc_data) > 4:
            abc = parse_abc(abc_data)
            abc_blocks.append(abc)
            all_classes.extend(build_all_classes(abc))

    return Resource(
        path=str(path),
        kind="swf",
        swf_header=header,
        swf_tags=tags,
        swf_version=version,
        abc_blocks=abc_blocks,
        classes=all_classes,
    )


def load_swz(path: str | Path) -> Resource:
    """Load a SWZ file into a Resource.

    SWZ files are signed and compressed ABC modules used by Adobe AIR.
    Format: RSA signature (variable length) + zlib-compressed ABC data.
    There is no fixed magic header — we scan for a valid zlib stream
    and verify the decompressed content starts with ABC version 46.16.

    Args:
        path: Path to the SWZ file.

    Returns:
        Resource with the parsed ABC content and resolved classes.

    Raises:
        ResourceError: If the file cannot be read or contains no valid ABC.
    """
    import zlib

    path = Path(path)
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise ResourceError(f"Cannot read SWZ file '{path}': {e}") from e

    if not data:
        raise ResourceError(f"SWZ file is empty: '{path}'")

    # SWZ format: RSA signature + zlib-compressed ABC.
    # Scan for a zlib stream (0x78 byte) and verify decompressed ABC version.
    abc_data = None
    for i in range(min(len(data), 256)):
        if data[i] == 0x78 and i + 2 < len(data):
            try:
                decompressed = zlib.decompress(data[i:])
                if len(decompressed) >= 4:
                    minor = decompressed[0] | (decompressed[1] << 8)
                    major = decompressed[2] | (decompressed[3] << 8)
                    if major == 46 and minor == 16:
                        abc_data = decompressed
                        break
            except zlib.error:
                continue

    if abc_data is None:
        # Try raw (uncompressed) ABC
        if len(data) >= 4:
            minor = data[0] | (data[1] << 8)
            major = data[2] | (data[3] << 8)
            if major == 46 and minor == 16:
                abc_data = data

    if abc_data is None:
        raise ResourceError(
            f"No valid ABC data found in SWZ file: '{path}'")

    abc_blocks: list[AbcFile] = []
    all_classes: list[ClassInfo] = []

    abc = parse_abc(abc_data)
    abc_blocks.append(abc)
    all_classes.extend(build_all_classes(abc))

    return Resource(
        path=str(path),
        kind="swz",
        abc_blocks=abc_blocks,
        classes=all_classes,
    )
