"""Tests for flashkit.swf.parser — SWF container parsing."""

import pytest

from flashkit.swf.parser import parse_swf
from flashkit.swf.tags import TAG_DO_ABC2, TAG_END
from flashkit.swf.builder import SwfBuilder, make_doabc2_tag
from flashkit.abc.builder import AbcBuilder
from flashkit.abc.writer import serialize_abc
from flashkit.errors import SWFParseError


def _build_test_swf(compress=False):
    """Helper to build a simple SWF with one ABC class."""
    b = AbcBuilder()
    ns = b.package_namespace("com.test")
    cls = b.qname(ns, "TestClass")
    b.define_class(name=cls, super_name=0)
    b.script()
    abc_bytes = serialize_abc(b.build())

    swf = SwfBuilder(version=40, width=800, height=600, fps=30)
    swf.add_abc("TestCode", abc_bytes)
    return swf.build(compress=compress)


class TestParseSwfValid:
    def test_uncompressed(self):
        data = _build_test_swf(compress=False)
        header, tags, version, length = parse_swf(data)
        assert version == 40
        assert any(t.tag_type == TAG_DO_ABC2 for t in tags)
        assert any(t.tag_type == TAG_END for t in tags)

    def test_compressed(self):
        data = _build_test_swf(compress=True)
        assert data[:3] == b"CWS"
        header, tags, version, length = parse_swf(data)
        assert version == 40
        assert any(t.tag_type == TAG_DO_ABC2 for t in tags)

    def test_doabc2_tag_has_name(self):
        data = _build_test_swf(compress=False)
        _, tags, _, _ = parse_swf(data)
        abc_tags = [t for t in tags if t.tag_type == TAG_DO_ABC2]
        assert len(abc_tags) == 1
        assert abc_tags[0].name == "TestCode"

    def test_file_length_field(self):
        data = _build_test_swf(compress=False)
        _, _, _, length = parse_swf(data)
        assert length == len(data)

    def test_header_bytes_returned(self):
        data = _build_test_swf(compress=False)
        header, _, _, _ = parse_swf(data)
        # Header should start with FWS
        assert header[:3] == b"FWS"
        # Header should be smaller than the whole file
        assert len(header) < len(data)


class TestParseSwfErrors:
    def test_empty_data(self):
        with pytest.raises(SWFParseError, match="empty"):
            parse_swf(b"")

    def test_too_short(self):
        with pytest.raises(SWFParseError, match="too short"):
            parse_swf(b"FWS\x28")

    def test_bad_signature(self):
        with pytest.raises(SWFParseError, match="Not a SWF"):
            parse_swf(b"XYZ\x00\x00\x00\x00\x00")

    def test_corrupted_zlib(self):
        # CWS header but garbage compressed data
        data = b"CWS\x28" + b"\x00\x00\x00\x20" + b"\xff\xff\xff\xff"
        with pytest.raises(SWFParseError, match="decompress"):
            parse_swf(data)
