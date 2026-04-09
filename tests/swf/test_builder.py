"""Tests for flashkit.swf.builder — SWF construction and tag building."""

import struct
import pytest

from flashkit.swf.builder import (
    SwfBuilder, build_tag_bytes, make_doabc2_tag,
    make_symbol_class_tag, make_end_tag, rebuild_swf,
)
from flashkit.swf.parser import parse_swf
from flashkit.swf.tags import SWFTag, TAG_DO_ABC2, TAG_END, TAG_SYMBOL_CLASS
from flashkit.abc.builder import AbcBuilder
from flashkit.abc.writer import serialize_abc


class TestBuildTagBytes:
    def test_short_header(self):
        """Small non-ABC tags use 2-byte short headers."""
        tag = SWFTag(tag_type=1, payload=b"\x00\x00\x00")
        raw = build_tag_bytes(tag)
        # Short header: 2 bytes
        tag_raw = struct.unpack("<H", raw[:2])[0]
        assert (tag_raw >> 6) == 1  # tag type
        assert (tag_raw & 0x3F) == 3  # length

    def test_long_header_for_abc(self):
        """DoABC2 tags always use 6-byte long headers."""
        tag = SWFTag(tag_type=TAG_DO_ABC2, payload=b"\x00" * 10)
        raw = build_tag_bytes(tag)
        tag_raw = struct.unpack("<H", raw[:2])[0]
        assert (tag_raw & 0x3F) == 0x3F  # long header marker
        length = struct.unpack("<I", raw[2:6])[0]
        assert length == 10

    def test_end_tag(self):
        tag = make_end_tag()
        raw = build_tag_bytes(tag)
        assert raw == b"\x00\x00"


class TestMakeDoabc2Tag:
    def test_creates_tag_82(self):
        tag = make_doabc2_tag("Test", b"\x10\x00\x2e\x00")
        assert tag.tag_type == TAG_DO_ABC2
        assert tag.name == "Test"

    def test_lazy_init_flag(self):
        tag = make_doabc2_tag("Test", b"\xAB", lazy_init=True)
        flags = struct.unpack("<I", tag.payload[:4])[0]
        assert flags == 1

    def test_no_lazy_init(self):
        tag = make_doabc2_tag("Test", b"\xAB", lazy_init=False)
        flags = struct.unpack("<I", tag.payload[:4])[0]
        assert flags == 0

    def test_name_null_terminated(self):
        tag = make_doabc2_tag("MyBlock", b"\x00")
        # After 4 bytes of flags, name should be null-terminated
        null_idx = tag.payload.index(0, 4)
        name = tag.payload[4:null_idx].decode("utf-8")
        assert name == "MyBlock"


class TestMakeSymbolClassTag:
    def test_single_symbol(self):
        tag = make_symbol_class_tag([(0, "Main")])
        assert tag.tag_type == TAG_SYMBOL_CLASS
        count = struct.unpack("<H", tag.payload[:2])[0]
        assert count == 1

    def test_document_class(self):
        tag = make_symbol_class_tag([(0, "com.example.App")])
        # CharID 0 = document class
        char_id = struct.unpack("<H", tag.payload[2:4])[0]
        assert char_id == 0

    def test_multiple_symbols(self):
        symbols = [(0, "Main"), (1, "Sprite1"), (2, "Sprite2")]
        tag = make_symbol_class_tag(symbols)
        count = struct.unpack("<H", tag.payload[:2])[0]
        assert count == 3


class TestSwfBuilder:
    def _make_abc_bytes(self):
        b = AbcBuilder()
        ns = b.package_namespace("com.test")
        b.define_class(name=b.qname(ns, "Hello"), super_name=0)
        b.script()
        return serialize_abc(b.build())

    def test_build_uncompressed(self):
        abc = self._make_abc_bytes()
        swf = SwfBuilder(version=40, width=800, height=600, fps=30)
        swf.add_abc("Code", abc)
        data = swf.build(compress=False)
        assert data[:3] == b"FWS"
        assert data[3] == 40  # version

    def test_build_compressed(self):
        abc = self._make_abc_bytes()
        swf = SwfBuilder(version=40)
        swf.add_abc("Code", abc)
        data = swf.build(compress=True)
        assert data[:3] == b"CWS"

    def test_roundtrip_parse(self):
        """Build → parse should produce matching tags."""
        abc = self._make_abc_bytes()
        swf = SwfBuilder(version=40, width=800, height=600, fps=24)
        swf.add_abc("TestBlock", abc)
        swf.set_document_class("com.test.Hello")
        data = swf.build(compress=False)

        header, tags, version, length = parse_swf(data)
        assert version == 40
        abc_tags = [t for t in tags if t.tag_type == TAG_DO_ABC2]
        assert len(abc_tags) == 1
        assert abc_tags[0].name == "TestBlock"
        sym_tags = [t for t in tags if t.tag_type == TAG_SYMBOL_CLASS]
        assert len(sym_tags) == 1

    def test_file_length_correct(self):
        swf = SwfBuilder()
        data = swf.build(compress=False)
        length_field = struct.unpack("<I", data[4:8])[0]
        assert length_field == len(data)

    def test_rect_encoding(self):
        """Width/height should be encoded correctly in twips."""
        swf = SwfBuilder(width=100, height=50)
        data = swf.build(compress=False)
        # Just verify it parses without error
        header, tags, version, length = parse_swf(data)
        assert version == 40

    def test_add_raw_tag(self):
        swf = SwfBuilder()
        custom = SWFTag(tag_type=9, payload=bytes([0xFF, 0x00, 0x00]))
        swf.add_tag(custom)
        data = swf.build(compress=False)
        _, tags, _, _ = parse_swf(data)
        bg_tags = [t for t in tags if t.tag_type == 9]
        assert len(bg_tags) == 1


class TestRebuildSwf:
    def test_rebuild_preserves_structure(self):
        """Parse → rebuild → reparse should preserve tag structure."""
        abc = serialize_abc(AbcBuilder().build())
        swf = SwfBuilder(version=40)
        swf.add_abc("Code", abc)
        original = swf.build(compress=False)

        header, tags, version, length = parse_swf(original)
        rebuilt = rebuild_swf(header, tags, compress=False)
        h2, tags2, v2, l2 = parse_swf(rebuilt)

        assert v2 == version
        assert len(tags2) == len(tags)
        for t1, t2 in zip(tags, tags2):
            assert t1.tag_type == t2.tag_type
            assert t1.payload == t2.payload
