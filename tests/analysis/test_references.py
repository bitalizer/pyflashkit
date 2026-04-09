"""Tests for flashkit.analysis.references — ReferenceIndex."""

import pytest

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.parser import parse_abc
from flashkit.abc.writer import serialize_abc
from flashkit.abc.constants import TRAIT_Method
from flashkit.info.class_info import build_all_classes
from flashkit.analysis.references import ReferenceIndex


def _build_ref_index(setup_fn):
    """Helper: run setup_fn with an AbcBuilder, build, and create ReferenceIndex.

    setup_fn receives (builder, pub_ns, priv_ns) and should define classes.
    Returns (ReferenceIndex, classes).
    """
    b = AbcBuilder()
    pub = b.package_namespace("")
    priv = b.private_namespace()
    setup_fn(b, pub, priv)
    b.script()

    abc = b.build()
    raw = serialize_abc(abc)
    abc2 = parse_abc(raw)
    classes = build_all_classes(abc2)
    index = ReferenceIndex.from_classes_and_abc(classes, [abc2])
    return index, classes


class TestFieldTypeRefs:
    def test_field_type_indexed(self):
        def setup(b, pub, priv):
            cls_mn = b.qname(pub, "Entity")
            int_mn = b.qname(pub, "int")
            field_mn = b.qname(priv, "health")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_slot(field_mn, type_mn=int_mn)])

        idx, _ = _build_ref_index(setup)
        refs = idx.field_type_users("int")
        assert len(refs) >= 1
        assert any(r.source_member == "health" for r in refs)


class TestMethodSignatureRefs:
    def test_return_type_indexed(self):
        def setup(b, pub, priv):
            cls_mn = b.qname(pub, "Service")
            str_mn = b.qname(pub, "String")
            m = b.method(return_type=str_mn)
            b.method_body(m, code=b.asm(
                b.op_getlocal_0(), b.op_pushscope(),
                b.op_pushstring(b.string("result")),
                b.op_returnvalue(),
            ), max_stack=2, local_count=1)
            method_mn = b.qname(priv, "getName")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_method(method_mn, m)])

        idx, _ = _build_ref_index(setup)
        refs = idx.method_return_users("String")
        assert len(refs) >= 1

    def test_param_type_indexed(self):
        def setup(b, pub, priv):
            cls_mn = b.qname(pub, "Handler")
            int_mn = b.qname(pub, "int")
            m = b.method(params=[int_mn])
            b.method_body(m, code=b.asm(
                b.op_getlocal_0(), b.op_pushscope(), b.op_returnvoid()))
            method_mn = b.qname(priv, "handle")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_method(method_mn, m)])

        idx, _ = _build_ref_index(setup)
        refs = idx.method_param_users("int")
        assert len(refs) >= 1


class TestBytecodeRefs:
    def test_constructprop_creates_instantiation(self):
        def setup(b, pub, priv):
            cls_mn = b.qname(pub, "Factory")
            target_mn = b.qname(pub, "Widget")
            m = b.method()
            b.method_body(m, code=b.asm(
                b.op_getlocal_0(), b.op_pushscope(),
                b.op_findpropstrict(target_mn),
                b.op_constructprop(target_mn, 0),
                b.op_pop(),
                b.op_returnvoid(),
            ), max_stack=2, local_count=1)
            method_mn = b.qname(priv, "create")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_method(method_mn, m)])

        idx, _ = _build_ref_index(setup)
        refs = idx.instantiators("Widget")
        assert len(refs) >= 1

    def test_pushstring_creates_string_use(self):
        def setup(b, pub, priv):
            cls_mn = b.qname(pub, "Logger")
            m = b.method()
            b.method_body(m, code=b.asm(
                b.op_getlocal_0(), b.op_pushscope(),
                b.op_pushstring(b.string("log message")),
                b.op_pop(),
                b.op_returnvoid(),
            ), max_stack=2, local_count=1)
            method_mn = b.qname(priv, "log")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_method(method_mn, m)])

        idx, _ = _build_ref_index(setup)
        refs = idx.string_users("log message")
        assert len(refs) >= 1

    def test_getlex_creates_class_ref(self):
        def setup(b, pub, priv):
            cls_mn = b.qname(pub, "Loader")
            target_mn = b.qname(pub, "Config")
            m = b.method()
            b.method_body(m, code=b.asm(
                b.op_getlocal_0(), b.op_pushscope(),
                b.op_getlex(target_mn),
                b.op_pop(),
                b.op_returnvoid(),
            ), max_stack=2, local_count=1)
            method_mn = b.qname(priv, "load")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_method(method_mn, m)])

        idx, _ = _build_ref_index(setup)
        refs = idx.references_to("Config")
        assert any(r.ref_kind == "class_ref" for r in refs)


class TestReferenceQueries:
    def test_references_from(self):
        def setup(b, pub, priv):
            cls_mn = b.qname(pub, "Source")
            int_mn = b.qname(pub, "int")
            field_mn = b.qname(priv, "count")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_slot(field_mn, type_mn=int_mn)])

        idx, _ = _build_ref_index(setup)
        refs = idx.references_from("Source")
        assert len(refs) >= 1

    def test_total_refs(self):
        def setup(b, pub, priv):
            cls_mn = b.qname(pub, "Multi")
            int_mn = b.qname(pub, "int")
            str_mn = b.qname(pub, "String")
            f1 = b.qname(priv, "x")
            f2 = b.qname(priv, "y")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[
                    b.trait_slot(f1, type_mn=int_mn),
                    b.trait_slot(f2, type_mn=str_mn),
                ])

        idx, _ = _build_ref_index(setup)
        assert idx.total_refs >= 2
