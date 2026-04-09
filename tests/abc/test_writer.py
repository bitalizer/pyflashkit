"""Tests for flashkit.abc.writer — ABC serializer."""

import pytest

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.parser import parse_abc
from flashkit.abc.writer import serialize_abc
from flashkit.abc.types import AbcFile, MultinameInfo
from flashkit.errors import SerializeError
from tests.conftest import build_abc_bytes


class TestSerializeAbc:
    def test_with_class_roundtrip(self, abc_with_class):
        """Parse → serialize → re-parse preserves structure."""
        abc = parse_abc(abc_with_class)
        output = serialize_abc(abc)
        abc2 = parse_abc(output)
        assert len(abc2.instances) == len(abc.instances)
        assert len(abc2.methods) == len(abc.methods)
        assert abc2.string_pool == abc.string_pool

    def test_preserves_strings(self, abc_with_class):
        abc = parse_abc(abc_with_class)
        output = serialize_abc(abc)
        abc2 = parse_abc(output)
        assert "TestClass" in abc2.string_pool
        assert "myField" in abc2.string_pool

    def test_preserves_class_count(self, abc_with_class):
        abc = parse_abc(abc_with_class)
        output = serialize_abc(abc)
        abc2 = parse_abc(output)
        assert len(abc2.instances) == 1
        assert len(abc2.classes) == 1

    def test_preserves_method_count(self, abc_with_class):
        abc = parse_abc(abc_with_class)
        output = serialize_abc(abc)
        abc2 = parse_abc(output)
        assert len(abc2.methods) == 3
        assert len(abc2.method_bodies) == 3

    def test_invalid_multiname_kind_raises(self):
        """Serializing a broken AbcFile should raise SerializeError."""
        abc = AbcFile()
        abc.major_version = 46
        abc.minor_version = 16
        abc.multiname_pool = [MultinameInfo(0), MultinameInfo(kind=0xFF)]
        with pytest.raises(SerializeError):
            serialize_abc(abc)


class TestSerializeAbcBuilder:
    """Serialize ABC produced by AbcBuilder — no hand-assembled bytes."""

    def test_minimal_roundtrip(self):
        b = AbcBuilder()
        abc = b.build()
        raw1 = serialize_abc(abc)
        abc2 = parse_abc(raw1)
        raw2 = serialize_abc(abc2)
        assert raw1 == raw2

    def test_class_roundtrip(self):
        b = AbcBuilder()
        ns = b.package_namespace("com.test")
        priv = b.private_namespace()
        pub = b.package_namespace("")
        cls_mn = b.qname(ns, "Hero")
        obj_mn = b.qname(pub, "Object")
        int_mn = b.qname(pub, "int")
        field_mn = b.qname(priv, "level")

        m = b.method(return_type=int_mn)
        b.method_body(m, code=b.asm(
            b.op_getlocal_0(), b.op_pushscope(),
            b.op_pushbyte(1),
            b.op_returnvalue(),
        ), max_stack=2, local_count=1)
        method_mn = b.qname(priv, "getLevel")

        b.define_class(
            name=cls_mn, super_name=obj_mn,
            instance_traits=[
                b.trait_slot(field_mn, type_mn=int_mn, slot_id=1),
                b.trait_method(method_mn, m),
            ])
        b.script()

        abc = b.build()
        raw1 = serialize_abc(abc)
        abc2 = parse_abc(raw1)
        raw2 = serialize_abc(abc2)
        assert raw1 == raw2

        # Verify structure
        assert len(abc2.instances) == 1
        assert "Hero" in abc2.string_pool
        assert "level" in abc2.string_pool
        assert "getLevel" in abc2.string_pool

    def test_multiple_classes_roundtrip(self):
        b = AbcBuilder()
        pub = b.package_namespace("")
        obj = b.qname(pub, "Object")

        for name in ["Alpha", "Beta", "Gamma"]:
            ns = b.package_namespace("com.test")
            b.define_class(name=b.qname(ns, name), super_name=obj)
        b.script()

        abc = b.build()
        raw1 = serialize_abc(abc)
        abc2 = parse_abc(raw1)
        raw2 = serialize_abc(abc2)
        assert raw1 == raw2
        assert len(abc2.instances) == 3
