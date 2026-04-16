"""Tests for flashkit.workspace — Resource, Workspace loading, and query API."""

import os
import struct
import tempfile
import pytest

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.writer import serialize_abc
from flashkit.abc.constants import TRAIT_METHOD
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


# ── Helper for query-API tests ───────────────────────────────────────────

def _build_query_workspace(tmp_path, setup_fn):
    """Build a workspace from an AbcBuilder setup function.

    setup_fn receives (builder, pub_ns, priv_ns).
    Returns a Workspace with the SWF loaded.
    """
    b = AbcBuilder()
    pub = b.package_namespace("")
    priv = b.private_namespace()
    setup_fn(b, pub, priv)
    b.script()

    abc_bytes = serialize_abc(b.build())
    swf = SwfBuilder(version=40)
    swf.add_abc("Code", abc_bytes)
    swf_bytes = swf.build(compress=False)

    path = tmp_path / "test.swf"
    path.write_bytes(swf_bytes)

    ws = Workspace()
    ws.load_swf(path)
    return ws


# ── Query API tests (moved from search tests) ────────────────────────────

class TestWorkspaceClassQueries:
    def test_find_classes_by_name_substring(self, tmp_path):
        def setup(b, pub, priv):
            b.define_class(name=b.qname(pub, "Player"), super_name=0)
            b.define_class(name=b.qname(pub, "PlayerStats"), super_name=0)
            b.define_class(name=b.qname(pub, "Enemy"), super_name=0)

        ws = _build_query_workspace(tmp_path, setup)
        results = ws.find_classes(name="Player")
        assert len(results) == 2
        names = {c.name for c in results}
        assert "Player" in names
        assert "PlayerStats" in names

    def test_get_subclasses(self, tmp_path):
        def setup(b, pub, priv):
            base = b.qname(pub, "Base")
            b.define_class(name=base, super_name=0)
            b.define_class(name=b.qname(pub, "Child"), super_name=base)

        ws = _build_query_workspace(tmp_path, setup)
        subs = ws.get_subclasses("Base")
        assert len(subs) == 1
        assert "Child" in subs[0]

    def test_get_descendants(self, tmp_path):
        def setup(b, pub, priv):
            a = b.qname(pub, "A")
            bb = b.qname(pub, "B")
            b.define_class(name=a, super_name=0)
            b.define_class(name=bb, super_name=a)
            b.define_class(name=b.qname(pub, "C"), super_name=bb)

        ws = _build_query_workspace(tmp_path, setup)
        desc = ws.get_descendants("A")
        names = set(desc)
        assert "B" in names
        assert "C" in names


class TestWorkspaceMemberQueries:
    def test_find_fields_by_name(self, tmp_path):
        def setup(b, pub, priv):
            int_mn = b.qname(pub, "int")
            cls_mn = b.qname(pub, "Entity")
            field_mn = b.qname(priv, "health")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_slot(field_mn, type_mn=int_mn)])

        ws = _build_query_workspace(tmp_path, setup)
        results = ws.find_fields(name="health")
        assert len(results) >= 1
        assert results[0][1].name == "health"

    def test_find_fields_by_type(self, tmp_path):
        def setup(b, pub, priv):
            int_mn = b.qname(pub, "int")
            str_mn = b.qname(pub, "String")
            cls_mn = b.qname(pub, "Data")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[
                    b.trait_slot(b.qname(priv, "count"), type_mn=int_mn),
                    b.trait_slot(b.qname(priv, "label"), type_mn=str_mn),
                ])

        ws = _build_query_workspace(tmp_path, setup)
        results = ws.find_fields(type_name="int")
        assert len(results) >= 1

    def test_find_methods_by_name(self, tmp_path):
        def setup(b, pub, priv):
            str_mn = b.qname(pub, "String")
            m = b.method(return_type=str_mn)
            b.method_body(m, code=b.asm(
                b.op_getlocal_0(), b.op_pushscope(),
                b.op_pushstring(b.string("x")),
                b.op_returnvalue(),
            ), max_stack=2, local_count=1)
            cls_mn = b.qname(pub, "Service")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_method(b.qname(priv, "getName"), m)])

        ws = _build_query_workspace(tmp_path, setup)
        results = ws.find_methods(name="getName")
        assert len(results) >= 1


class TestWorkspaceStringQueries:
    def test_search_strings(self, tmp_path):
        def setup(b, pub, priv):
            cls_mn = b.qname(pub, "App")
            m = b.method()
            b.method_body(m, code=b.asm(
                b.op_getlocal_0(), b.op_pushscope(),
                b.op_pushstring(b.string("config.xml")),
                b.op_pop(),
                b.op_returnvoid(),
            ), max_stack=2, local_count=1)
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_method(b.qname(priv, "init"), m)])

        ws = _build_query_workspace(tmp_path, setup)
        results = ws.search_strings("config")
        assert len(results) >= 1
        assert any("config.xml" == s for s in results)

    def test_classes_using_string(self, tmp_path):
        def setup(b, pub, priv):
            cls_mn = b.qname(pub, "Loader")
            m = b.method()
            b.method_body(m, code=b.asm(
                b.op_getlocal_0(), b.op_pushscope(),
                b.op_pushstring(b.string("data.json")),
                b.op_pop(),
                b.op_returnvoid(),
            ), max_stack=2, local_count=1)
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_method(b.qname(priv, "fetch"), m)])

        ws = _build_query_workspace(tmp_path, setup)
        classes = ws.classes_using_string("data.json")
        assert len(classes) >= 1
        assert any("Loader" in c for c in classes)


class TestWorkspaceStructuralQueries:
    def test_find_classes_with_field_type(self, tmp_path):
        def setup(b, pub, priv):
            int_mn = b.qname(pub, "int")
            b.define_class(
                name=b.qname(pub, "HasInt"), super_name=0,
                instance_traits=[b.trait_slot(b.qname(priv, "x"), type_mn=int_mn)])
            b.define_class(
                name=b.qname(pub, "NoInt"), super_name=0)

        ws = _build_query_workspace(tmp_path, setup)
        results = ws.find_classes_with_field_type("int")
        names = {c.name for c in results}
        assert "HasInt" in names
        assert "NoInt" not in names

    def test_find_classes_with_method_returning(self, tmp_path):
        def setup(b, pub, priv):
            str_mn = b.qname(pub, "String")
            m = b.method(return_type=str_mn)
            b.method_body(m, code=b.asm(
                b.op_getlocal_0(), b.op_pushscope(),
                b.op_pushstring(b.string("x")),
                b.op_returnvalue(),
            ), max_stack=2, local_count=1)
            b.define_class(
                name=b.qname(pub, "Namer"), super_name=0,
                instance_traits=[b.trait_method(b.qname(priv, "name"), m)])
            b.define_class(
                name=b.qname(pub, "Plain"), super_name=0)

        ws = _build_query_workspace(tmp_path, setup)
        results = ws.find_classes_with_method_returning("String")
        names = {c.name for c in results}
        assert "Namer" in names
        assert "Plain" not in names


class TestWorkspaceSummary:
    def test_summary_content(self, tmp_path):
        def setup(b, pub, priv):
            b.define_class(name=b.qname(pub, "Foo"), super_name=0)

        ws = _build_query_workspace(tmp_path, setup)
        s = ws.summary()
        assert "1 classes" in s
