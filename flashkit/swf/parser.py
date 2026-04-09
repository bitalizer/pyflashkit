"""
SWF container parser.

Parses SWF files (compressed or uncompressed) into a header and a list
of ``SWFTag`` objects. Handles CWS (zlib-compressed) and FWS (uncompressed)
signatures.

Usage::

    from flashkit.swf.parser import parse_swf

    with open("application.swf", "rb") as f:
        header, tags, version, file_length = parse_swf(f.read())

    for tag in tags:
        print(f"{tag.type_name}: {len(tag.payload)} bytes")

Reference: SWF File Format Specification v19, Chapter 1-2.
"""

from __future__ import annotations

import struct
import zlib

from ..errors import SWFParseError
from .tags import SWFTag, TAG_NAMES, TAG_END, TAG_DO_ABC, TAG_DO_ABC2, TAG_SYMBOL_CLASS


def _parse_rect_size(data: bytes, offset: int) -> int:
    """Calculate how many bytes a RECT structure occupies.

    The RECT is a bit-packed structure where the first 5 bits encode
    the number of bits per field (Xmin, Xmax, Ymin, Ymax).

    Args:
        data: Raw SWF bytes.
        offset: Byte offset where the RECT starts.

    Returns:
        Number of bytes the RECT occupies.
    """
    nbits = (data[offset] >> 3) & 0x1F
    total_bits = 5 + 4 * nbits
    return (total_bits + 7) // 8


def parse_swf(data: bytes) -> tuple[bytes, list[SWFTag], int, int]:
    """Parse a SWF file (compressed or uncompressed).

    Handles both CWS (zlib-compressed) and FWS (uncompressed) formats.
    The returned header bytes include everything up to the first tag
    (signature, version, file length, RECT, frame rate, frame count).

    Args:
        data: Raw SWF file bytes.

    Returns:
        Tuple of (header_bytes, tags, version, file_length).

    Raises:
        SWFParseError: If the data is not a valid SWF file.
    """
    if not data:
        raise SWFParseError("SWF data is empty")
    if len(data) < 8:
        raise SWFParseError(
            f"SWF data too short ({len(data)} bytes, minimum 8)")

    sig = data[:3]
    if sig == b"CWS":
        try:
            raw = data[:8] + zlib.decompress(data[8:])
        except zlib.error as e:
            raise SWFParseError(
                f"Failed to decompress CWS data: {e}") from e
        raw = b"FWS" + raw[3:]  # fix signature to uncompressed
    elif sig == b"FWS":
        raw = data
    else:
        raise SWFParseError(f"Not a SWF file (signature: {sig!r})")

    try:
        version = raw[3]
        file_length = struct.unpack_from("<I", raw, 4)[0]

        # RECT + frame rate (2 bytes) + frame count (2 bytes)
        rect_size = _parse_rect_size(raw, 8)
        header_end = 8 + rect_size + 4
        header_bytes = raw[:header_end]

        # Parse tags
        tags: list[SWFTag] = []
        pos = header_end
        while pos < len(raw) - 1:
            tag_raw = struct.unpack_from("<H", raw, pos)[0]
            tag_type = (tag_raw >> 6) & 0x3FF
            tag_len = tag_raw & 0x3F
            header_size = 2

            if tag_len == 0x3F:
                # Extended length: next 4 bytes are the actual length
                tag_len = struct.unpack_from("<I", raw, pos + 2)[0]
                header_size = 6

            payload = raw[pos + header_size: pos + header_size + tag_len]
            tag = SWFTag(tag_type=tag_type, payload=payload)

            # Extract name from DoABC2 tags (4-byte flags + null-terminated name)
            if tag_type == TAG_DO_ABC2 and len(payload) > 4:
                null_idx = payload.index(0, 4)
                tag.name = payload[4:null_idx].decode("utf-8", errors="replace")

            tags.append(tag)

            if tag_type == TAG_END:
                break
            pos += header_size + tag_len

    except SWFParseError:
        raise
    except (IndexError, struct.error, ValueError, OverflowError) as e:
        raise SWFParseError(f"Corrupted SWF data: {e}") from e

    return header_bytes, tags, version, file_length


def print_tags(tags: list[SWFTag]) -> None:
    """Pretty-print a SWF tag list to stdout.

    Shows tag index, type, name, size, and extra info for known tag types
    (ABC version for DoABC, symbol names for SymbolClass, etc.).

    Args:
        tags: List of SWFTag objects from ``parse_swf()``.
    """
    for i, tag in enumerate(tags):
        extra = ""
        if tag.tag_type == TAG_DO_ABC2:
            extra = f'  name="{tag.name}"'
        elif tag.tag_type == TAG_DO_ABC:
            if len(tag.payload) >= 4:
                minor, major = struct.unpack_from("<HH", tag.payload, 0)
                extra = f"  ABC v{minor}.{major}"
        elif tag.tag_type == TAG_SYMBOL_CLASS:
            if len(tag.payload) >= 2:
                count = struct.unpack_from("<H", tag.payload, 0)[0]
                extra = f"  {count} symbol(s)"
                off = 2
                for j in range(min(count, 5)):
                    cid = struct.unpack_from("<H", tag.payload, off)[0]
                    off += 2
                    null_idx = tag.payload.index(0, off)
                    sname = tag.payload[off:null_idx].decode(
                        "utf-8", errors="replace")
                    off = null_idx + 1
                    doc = " [DOCUMENT CLASS]" if cid == 0 else ""
                    extra += (
                        f'\n          CharID={cid} -> "{sname}"{doc}')

        size_str = f"{len(tag.payload):>10,}"
        print(
            f"  [{i:2d}] Tag {tag.tag_type:3d} "
            f"({tag.type_name:<30s})  {size_str} bytes{extra}")
