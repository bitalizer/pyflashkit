"""
SWF container builder.

Provides functions to serialize SWF tags, rebuild complete SWF files,
create new DoABC2 tags, and build SWF files from scratch.

Usage — modify an existing SWF::

    from flashkit.swf.parser import parse_swf
    from flashkit.swf.builder import rebuild_swf, make_doabc2_tag

    header, tags, version, length = parse_swf(swf_bytes)
    new_tag = make_doabc2_tag("MyCode", abc_bytes)
    tags.insert(-1, new_tag)
    output = rebuild_swf(header, tags, compress=True)

Usage — build a SWF from scratch::

    from flashkit.swf.builder import SwfBuilder

    swf = SwfBuilder(version=40, width=800, height=600, fps=30)
    swf.add_abc("MainCode", abc_bytes)
    swf.set_document_class("com.example.Main")
    output = swf.build(compress=True)

Reference: SWF File Format Specification v19, Chapter 2.
"""

from __future__ import annotations

import struct
import zlib

from .tags import SWFTag, TAG_DO_ABC, TAG_DO_ABC2, TAG_END, TAG_SYMBOL_CLASS


def build_tag_bytes(tag: SWFTag) -> bytes:
    """Serialize a single SWFTag to its binary representation.

    Uses short headers (2 bytes) for small non-ABC tags and long headers
    (6 bytes) for large payloads or DoABC/DoABC2 tags.

    Args:
        tag: The SWFTag to serialize.

    Returns:
        Raw bytes for this tag (header + payload).
    """
    payload_len = len(tag.payload)
    if payload_len < 0x3F and tag.tag_type not in (TAG_DO_ABC, TAG_DO_ABC2):
        # Short header — only for small non-ABC tags
        header = struct.pack("<H", (tag.tag_type << 6) | payload_len)
        return header + tag.payload
    else:
        # Long header
        header = struct.pack("<H", (tag.tag_type << 6) | 0x3F)
        header += struct.pack("<I", payload_len)
        return header + tag.payload


def rebuild_swf(
    header_bytes: bytes,
    tags: list[SWFTag],
    compress: bool = True,
) -> bytes:
    """Rebuild a complete SWF file from header and tags.

    Recomputes the file length field and optionally zlib-compresses
    the output.

    Args:
        header_bytes: Original SWF header (from ``parse_swf()``).
        tags: List of SWFTag objects.
        compress: If True, output CWS (zlib-compressed). Default True.

    Returns:
        Complete SWF file bytes.
    """
    body = b""
    for tag in tags:
        body += build_tag_bytes(tag)

    raw = header_bytes + body
    # Update file length field (bytes 4-7)
    raw = raw[:4] + struct.pack("<I", len(raw)) + raw[8:]

    if compress:
        return b"CWS" + raw[3:8] + zlib.compress(raw[8:], 9)
    else:
        return raw


def make_doabc2_tag(
    name: str,
    abc_data: bytes,
    lazy_init: bool = True,
) -> SWFTag:
    """Create a DoABC2 tag (type 82).

    DoABC2 tags contain flags, a null-terminated name, and the ABC
    bytecode data.

    Args:
        name: Name string for the ABC block.
        abc_data: Raw ABC bytecode bytes.
        lazy_init: If True, set the lazy initialization flag. Default True.

    Returns:
        A new SWFTag with tag_type=82.
    """
    flags = struct.pack("<I", 1 if lazy_init else 0)
    name_bytes = name.encode("utf-8") + b"\x00"
    payload = flags + name_bytes + abc_data
    return SWFTag(tag_type=TAG_DO_ABC2, payload=payload, name=name)


def make_symbol_class_tag(symbols: list[tuple[int, str]]) -> SWFTag:
    """Create a SymbolClass tag (type 76).

    Maps character IDs to class names. Character ID 0 with a class
    name defines the document class.

    Args:
        symbols: List of (character_id, class_name) pairs.

    Returns:
        A new SWFTag with tag_type=76.
    """
    payload = struct.pack("<H", len(symbols))
    for char_id, name in symbols:
        payload += struct.pack("<H", char_id)
        payload += name.encode("utf-8") + b"\x00"
    return SWFTag(tag_type=TAG_SYMBOL_CLASS, payload=payload)


def make_end_tag() -> SWFTag:
    """Create an End tag (type 0)."""
    return SWFTag(tag_type=TAG_END, payload=b"")


class SwfBuilder:
    """High-level builder for constructing SWF files from scratch.

    Handles the header, RECT, frame rate, and tag assembly.
    Add ABC blocks and symbol mappings, then call ``build()``.

    Args:
        version: SWF version number. Default 40.
        width: Stage width in pixels. Default 800.
        height: Stage height in pixels. Default 600.
        fps: Frame rate. Default 24.
        frame_count: Total frames. Default 1.
    """

    def __init__(
        self,
        version: int = 40,
        width: int = 800,
        height: int = 600,
        fps: int = 24,
        frame_count: int = 1,
    ) -> None:
        self.version = version
        self.width = width
        self.height = height
        self.fps = fps
        self.frame_count = frame_count
        self._tags: list[SWFTag] = []
        self._symbols: list[tuple[int, str]] = []

    def add_tag(self, tag: SWFTag) -> None:
        """Add a raw SWF tag.

        Args:
            tag: Any SWFTag to include before the End tag.
        """
        self._tags.append(tag)

    def add_abc(self, name: str, abc_data: bytes,
                lazy_init: bool = True) -> None:
        """Add an ABC bytecode block as a DoABC2 tag.

        Args:
            name: Name for the ABC block.
            abc_data: Serialized ABC bytes.
            lazy_init: Whether to set the lazy init flag.
        """
        self._tags.append(make_doabc2_tag(name, abc_data, lazy_init))

    def add_symbol(self, char_id: int, class_name: str) -> None:
        """Map a character ID to a class name.

        Args:
            char_id: Character ID (0 for document class).
            class_name: Fully qualified class name.
        """
        self._symbols.append((char_id, class_name))

    def set_document_class(self, class_name: str) -> None:
        """Set the document class (character ID 0).

        Args:
            class_name: Fully qualified class name.
        """
        self.add_symbol(0, class_name)

    def _build_header(self) -> bytes:
        """Build the SWF header bytes (before tags)."""
        # Encode RECT in twips (1 pixel = 20 twips)
        xmax = self.width * 20
        ymax = self.height * 20
        # Calculate nbits needed
        max_val = max(xmax, ymax)
        nbits = max_val.bit_length() if max_val > 0 else 1

        # Pack RECT as bits: 5-bit nbits + 4 fields of nbits each
        # Xmin=0, Xmax, Ymin=0, Ymax
        total_bits = 5 + 4 * nbits
        total_bytes = (total_bits + 7) // 8
        rect = bytearray(total_bytes)

        # Write bits
        bit_pos = 0

        def write_bits(value: int, count: int) -> None:
            nonlocal bit_pos
            for i in range(count - 1, -1, -1):
                byte_idx = bit_pos // 8
                bit_idx = 7 - (bit_pos % 8)
                if value & (1 << i):
                    rect[byte_idx] |= (1 << bit_idx)
                bit_pos += 1

        write_bits(nbits, 5)
        write_bits(0, nbits)      # Xmin
        write_bits(xmax, nbits)   # Xmax
        write_bits(0, nbits)      # Ymin
        write_bits(ymax, nbits)   # Ymax

        # Frame rate (8.8 fixed point) + frame count
        frame_rate = struct.pack("<BB", 0, self.fps)
        frame_count = struct.pack("<H", self.frame_count)

        header = bytearray()
        header += b"FWS"
        header += bytes([self.version])
        header += struct.pack("<I", 0)  # file length (filled later)
        header += rect
        header += frame_rate
        header += frame_count
        return bytes(header)

    def build(self, compress: bool = True) -> bytes:
        """Build the complete SWF file.

        Args:
            compress: If True, produce CWS (zlib-compressed). Default True.

        Returns:
            Complete SWF file bytes.
        """
        header = self._build_header()

        # Assemble tags
        tags_bytes = bytearray()
        for tag in self._tags:
            tags_bytes += build_tag_bytes(tag)

        # Add SymbolClass if symbols were defined
        if self._symbols:
            tags_bytes += build_tag_bytes(make_symbol_class_tag(self._symbols))

        # End tag
        tags_bytes += build_tag_bytes(make_end_tag())

        # Combine and set file length
        raw = bytearray(header) + tags_bytes
        struct.pack_into("<I", raw, 4, len(raw))

        if compress:
            return b"CWS" + bytes(raw[3:8]) + zlib.compress(bytes(raw[8:]), 9)
        else:
            return bytes(raw)
