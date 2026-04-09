"""Tests for flashkit.search — SearchEngine unified query API."""

import tempfile
import pytest

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.writer import serialize_abc
from flashkit.abc.constants import TRAIT_Method
from flashkit.swf.builder import SwfBuilder
from flashkit.workspace import Workspace
from flashkit.search import SearchEngine


def _build_workspace(tmp_path, setup_fn):
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


class TestSearchEngineClasses:
    def test_find_classes_by_name(self, tmp_path):
        def setup(b, pub, priv):
            b.define_class(name=b.qname(pub, "Player"), super_name=0)
            b.define_class(name=b.qname(pub, "PlayerStats"), super_name=0)
            b.define_class(name=b.qname(pub, "Enemy"), super_name=0)

        ws = _build_workspace(tmp_path, setup)
        engine = SearchEngine(ws)
        results = engine.find_classes(name="Player")
        assert len(results) == 2
        names = {r.name for r in results}
        assert "Player" in names
        assert "PlayerStats" in names

    def test_find_subclasses(self, tmp_path):
        def setup(b, pub, priv):
            base = b.qname(pub, "Base")
            b.define_class(name=base, super_name=0)
            b.define_class(name=b.qname(pub, "Child"), super_name=base)

        ws = _build_workspace(tmp_path, setup)
        engine = SearchEngine(ws)
        results = engine.find_subclasses("Base")
        assert len(results) == 1
        assert results[0].name == "Child"

    def test_find_subclasses_transitive(self, tmp_path):
        def setup(b, pub, priv):
            a = b.qname(pub, "A")
            bb = b.qname(pub, "B")
            b.define_class(name=a, super_name=0)
            b.define_class(name=bb, super_name=a)
            b.define_class(name=b.qname(pub, "C"), super_name=bb)

        ws = _build_workspace(tmp_path, setup)
        engine = SearchEngine(ws)
        results = engine.find_subclasses("A", transitive=True)
        names = {r.name for r in results}
        assert "B" in names
        assert "C" in names


class TestSearchEngineMembers:
    def test_find_fields(self, tmp_path):
        def setup(b, pub, priv):
            int_mn = b.qname(pub, "int")
            cls_mn = b.qname(pub, "Entity")
            field_mn = b.qname(priv, "health")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_slot(field_mn, type_mn=int_mn)])

        ws = _build_workspace(tmp_path, setup)
        engine = SearchEngine(ws)
        results = engine.find_fields(name="health")
        assert len(results) >= 1
        assert results[0].member_name == "health"

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

        ws = _build_workspace(tmp_path, setup)
        engine = SearchEngine(ws)
        results = engine.find_fields(type_name="int")
        assert len(results) >= 1
        assert all(r.member_type == "field" for r in results)

    def test_find_methods(self, tmp_path):
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

        ws = _build_workspace(tmp_path, setup)
        engine = SearchEngine(ws)
        results = engine.find_methods(name="getName")
        assert len(results) >= 1
        assert results[0].member_type == "method"


class TestSearchEngineStrings:
    def test_find_by_string(self, tmp_path):
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

        ws = _build_workspace(tmp_path, setup)
        engine = SearchEngine(ws)
        results = engine.find_by_string("config")
        assert len(results) >= 1
        assert any("config.xml" == r.string for r in results)

    def test_find_classes_by_string(self, tmp_path):
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

        ws = _build_workspace(tmp_path, setup)
        engine = SearchEngine(ws)
        results = engine.find_classes_by_string("data.json")
        assert len(results) >= 1
        assert any("Loader" in r.name for r in results)


class TestSearchEngineStructural:
    def test_find_classes_with_field_type(self, tmp_path):
        def setup(b, pub, priv):
            int_mn = b.qname(pub, "int")
            b.define_class(
                name=b.qname(pub, "HasInt"), super_name=0,
                instance_traits=[b.trait_slot(b.qname(priv, "x"), type_mn=int_mn)])
            b.define_class(
                name=b.qname(pub, "NoInt"), super_name=0)

        ws = _build_workspace(tmp_path, setup)
        engine = SearchEngine(ws)
        results = engine.find_classes_with_field_type("int")
        names = {r.name for r in results}
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

        ws = _build_workspace(tmp_path, setup)
        engine = SearchEngine(ws)
        results = engine.find_classes_with_method_returning("String")
        names = {r.name for r in results}
        assert "Namer" in names
        assert "Plain" not in names


class TestSearchEngineSummary:
    def test_summary(self, tmp_path):
        def setup(b, pub, priv):
            b.define_class(name=b.qname(pub, "Foo"), super_name=0)

        ws = _build_workspace(tmp_path, setup)
        engine = SearchEngine(ws)
        s = engine.summary()
        assert "1 classes" in s
