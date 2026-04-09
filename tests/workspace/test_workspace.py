"""Tests for flashkit.workspace — Resource and Workspace loading."""

import os
import struct
import tempfile
import pytest

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.writer import serialize_abc
from flashkit.swf.builder import SwfBuilder
from flashkit.workspace import Workspace, Resource, load_swf
from flashkit.errors import ResourceError, SWFParseError


def _build_test_swf(classes=None, compress=False):
    """Build a SWF with the given class definitions.

    Args:
        classes: List of (package, name) tuples. Defaults to one test class.
        compress: Whether to zlib-compress the output.

    Returns:
        Complete SWF file bytes.
    """
    if classes is None:
        classes = [("com.test", "TestClass")]

    b = AbcBuilder()
    pub = b.package_namespace("")
    obj_mn = b.qname(pub, "Object")

    for pkg, name in classes:
        ns = b.package_namespace(pkg)
        cls_mn = b.qname(ns, name)
        b.define_class(name=cls_mn, super_name=obj_mn)

    b.script()
    abc_bytes = serialize_abc(b.build())

    swf = SwfBuilder(version=40, width=800, height=600, fps=30)
    swf.add_abc("TestCode", abc_bytes)
    return swf.build(compress=compress)


class TestLoadSwf:
    def test_load_from_file(self, tmp_path):
        swf_bytes = _build_test_swf()
        path = tmp_path / "test.swf"
        path.write_bytes(swf_bytes)

        res = load_swf(path)
        assert res.kind == "swf"
        assert len(res.abc_blocks) == 1
        assert len(res.classes) == 1
        assert res.classes[0].name == "TestClass"

    def test_load_compressed(self, tmp_path):
        swf_bytes = _build_test_swf(compress=True)
        path = tmp_path / "test.swf"
        path.write_bytes(swf_bytes)

        res = load_swf(path)
        assert len(res.classes) == 1

    def test_missing_file(self):
        with pytest.raises(ResourceError, match="Cannot read"):
            load_swf("/nonexistent/path.swf")

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.swf"
        path.write_bytes(b"")
        with pytest.raises(ResourceError, match="empty"):
            load_swf(path)

    def test_invalid_swf(self, tmp_path):
        path = tmp_path / "bad.swf"
        path.write_bytes(b"not a swf file at all")
        with pytest.raises(ResourceError, match="Failed to parse"):
            load_swf(path)


class TestWorkspace:
    def test_load_single(self, tmp_path):
        swf_bytes = _build_test_swf()
        path = tmp_path / "app.swf"
        path.write_bytes(swf_bytes)

        ws = Workspace()
        ws.load_swf(path)
        assert ws.class_count == 1
        assert ws.classes[0].name == "TestClass"

    def test_get_class_by_name(self, tmp_path):
        swf_bytes = _build_test_swf()
        path = tmp_path / "app.swf"
        path.write_bytes(swf_bytes)

        ws = Workspace()
        ws.load_swf(path)
        ci = ws.get_class("TestClass")
        assert ci is not None
        assert ci.name == "TestClass"

    def test_get_class_by_qualified_name(self, tmp_path):
        swf_bytes = _build_test_swf()
        path = tmp_path / "app.swf"
        path.write_bytes(swf_bytes)

        ws = Workspace()
        ws.load_swf(path)
        ci = ws.get_class("com.test.TestClass")
        assert ci is not None

    def test_get_class_not_found(self, tmp_path):
        swf_bytes = _build_test_swf()
        path = tmp_path / "app.swf"
        path.write_bytes(swf_bytes)

        ws = Workspace()
        ws.load_swf(path)
        assert ws.get_class("NonExistent") is None

    def test_multiple_classes(self, tmp_path):
        classes = [
            ("com.game", "Player"),
            ("com.game", "Enemy"),
            ("com.ui", "HUD"),
        ]
        swf_bytes = _build_test_swf(classes=classes)
        path = tmp_path / "app.swf"
        path.write_bytes(swf_bytes)

        ws = Workspace()
        ws.load_swf(path)
        assert ws.class_count == 3
        names = {c.name for c in ws.classes}
        assert names == {"Player", "Enemy", "HUD"}

    def test_find_classes_by_name(self, tmp_path):
        classes = [("com.game", "Player"), ("com.game", "PlayerStats")]
        swf_bytes = _build_test_swf(classes=classes)
        path = tmp_path / "app.swf"
        path.write_bytes(swf_bytes)

        ws = Workspace()
        ws.load_swf(path)
        results = ws.find_classes(name="Player")
        assert len(results) == 2

    def test_find_classes_by_package(self, tmp_path):
        classes = [("com.game", "Player"), ("com.ui", "Button")]
        swf_bytes = _build_test_swf(classes=classes)
        path = tmp_path / "app.swf"
        path.write_bytes(swf_bytes)

        ws = Workspace()
        ws.load_swf(path)
        results = ws.find_classes(package="com.game")
        assert len(results) == 1
        assert results[0].name == "Player"

    def test_abc_blocks(self, tmp_path):
        swf_bytes = _build_test_swf()
        path = tmp_path / "app.swf"
        path.write_bytes(swf_bytes)

        ws = Workspace()
        ws.load_swf(path)
        assert len(ws.abc_blocks) == 1

    def test_summary(self, tmp_path):
        swf_bytes = _build_test_swf()
        path = tmp_path / "app.swf"
        path.write_bytes(swf_bytes)

        ws = Workspace()
        ws.load_swf(path)
        s = ws.summary()
        assert "1 resource" in s
        assert "1 classes" in s

    def test_load_swf_bytes(self):
        """load_swf_bytes should work without temp files."""
        swf_bytes = _build_test_swf()
        ws = Workspace()
        res = ws.load_swf_bytes(swf_bytes)
        assert ws.class_count == 1
        assert ws.classes[0].name == "TestClass"
        assert res.path == "<memory>"

    def test_load_swf_bytes_custom_name(self):
        swf_bytes = _build_test_swf()
        ws = Workspace()
        res = ws.load_swf_bytes(swf_bytes, name="test.swf")
        assert res.path == "test.swf"

    def test_resource_properties(self, tmp_path):
        swf_bytes = _build_test_swf()
        path = tmp_path / "app.swf"
        path.write_bytes(swf_bytes)

        ws = Workspace()
        res = ws.load_swf(path)
        assert res.class_count == 1
        assert res.method_count > 0
        assert res.string_count > 0
