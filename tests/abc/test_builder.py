"""Tests for flashkit.abc.builder — AbcBuilder programmatic construction."""

import pytest

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.parser import parse_abc
from flashkit.abc.writer import serialize_abc
from flashkit.abc.constants import (
    CONSTANT_QNAME, CONSTANT_PACKAGE_NAMESPACE, CONSTANT_PRIVATE_NS,
    TRAIT_SLOT, TRAIT_METHOD, TRAIT_CONST, TRAIT_GETTER, TRAIT_CLASS,
    INSTANCE_SEALED, INSTANCE_FINAL,
    ATTR_OVERRIDE,
)
from flashkit.info.class_info import build_all_classes


class TestAbcBuilderPools:
    """String, integer, double, namespace, and multiname pool construction."""

    def test_string_dedup(self):
        b = AbcBuilder()
        idx1 = b.string("hello")
        idx2 = b.string("hello")
        assert idx1 == idx2

    def test_string_zero_is_empty(self):
        b = AbcBuilder()
        assert b._string_pool[0] == ""

    def test_integer_pool(self):
        b = AbcBuilder()
        idx1 = b.integer(42)
        idx2 = b.integer(42)
        idx3 = b.integer(-1)
        assert idx1 == idx2
        assert idx1 != idx3

    def test_uint_pool(self):
        b = AbcBuilder()
        idx1 = b.uint(100)
        idx2 = b.uint(100)
        assert idx1 == idx2

    def test_double_pool(self):
        b = AbcBuilder()
        idx1 = b.double(3.14)
        idx2 = b.double(3.14)
        idx3 = b.double(2.71)
        assert idx1 == idx2
        assert idx1 != idx3

    def test_package_namespace_with_string(self):
        b = AbcBuilder()
        ns = b.package_namespace("com.test")
        assert ns >= 1
        # String should be in pool
        assert "com.test" in b._string_pool

    def test_namespace_dedup(self):
        b = AbcBuilder()
        ns1 = b.package_namespace("com.test")
        ns2 = b.package_namespace("com.test")
        assert ns1 == ns2

    def test_qname_dedup(self):
        b = AbcBuilder()
        ns = b.package_namespace("com.test")
        mn1 = b.qname(ns, "MyClass")
        mn2 = b.qname(ns, "MyClass")
        assert mn1 == mn2

    def test_qname_with_string_arg(self):
        b = AbcBuilder()
        ns = b.package_namespace("com.test")
        mn = b.qname(ns, "MyClass")
        assert mn >= 1

    def test_multiname(self):
        b = AbcBuilder()
        ns1 = b.package_namespace("com.a")
        ns2 = b.package_namespace("com.b")
        nss = b.ns_set([ns1, ns2])
        mn = b.multiname("Thing", nss)
        assert mn >= 1

    def test_rtqname(self):
        b = AbcBuilder()
        mn = b.rtqname("dynamicName")
        assert mn >= 1


class TestAbcBuilderMethods:
    """Method signature and body construction."""

    def test_empty_method(self):
        b = AbcBuilder()
        m = b.method()
        assert m == 0
        assert len(b._methods) == 1
        assert b._methods[0].param_count == 0

    def test_method_with_params(self):
        b = AbcBuilder()
        ns = b.package_namespace("")
        int_mn = b.qname(ns, "int")
        str_mn = b.qname(ns, "String")
        m = b.method(params=[str_mn], return_type=int_mn,
                     param_names=["arg0"])
        assert b._methods[m].param_count == 1
        assert b._methods[m].param_types == [str_mn]
        assert b._methods[m].return_type == int_mn

    def test_method_body(self):
        b = AbcBuilder()
        m = b.method()
        body_idx = b.method_body(m, code=b.asm(
            b.op_getlocal_0(),
            b.op_pushscope(),
            b.op_returnvoid(),
        ), max_stack=1, local_count=1)
        assert body_idx == 0
        assert b._method_bodies[0].method == m
        assert len(b._method_bodies[0].code) == 3


class TestAbcBuilderTraits:
    """Trait construction (slot, method, class)."""

    def test_trait_slot(self):
        t = AbcBuilder.trait_slot(name=3, type_mn=4, slot_id=1)
        assert t.kind == TRAIT_SLOT
        assert t.name == 3

    def test_trait_const(self):
        t = AbcBuilder.trait_slot(name=3, type_mn=4, is_const=True)
        assert t.kind == TRAIT_CONST

    def test_trait_method(self):
        t = AbcBuilder.trait_method(name=5, method=1)
        assert t.kind == TRAIT_METHOD
        assert t.name == 5

    def test_trait_getter(self):
        t = AbcBuilder.trait_method(name=5, method=1, kind=TRAIT_GETTER)
        assert t.kind == TRAIT_GETTER

    def test_trait_class(self):
        t = AbcBuilder.trait_class(name=1, class_index=0)
        assert t.kind == TRAIT_CLASS


class TestAbcBuilderClasses:
    """Class definition and auto-generation."""

    def test_define_class_auto_methods(self):
        b = AbcBuilder()
        ns = b.package_namespace("com.test")
        cls_mn = b.qname(ns, "Auto")
        idx = b.define_class(name=cls_mn, super_name=0)
        assert idx == 0
        # Should auto-create constructor + static init
        assert len(b._methods) == 2
        assert len(b._method_bodies) == 2

    def test_define_class_explicit_constructor(self):
        b = AbcBuilder()
        ns = b.package_namespace("")
        cls_mn = b.qname(ns, "Explicit")
        ctor = b.method()
        b.method_body(ctor, code=b.asm(
            b.op_getlocal_0(), b.op_pushscope(),
            b.op_getlocal_0(), b.op_constructsuper(0),
            b.op_returnvoid(),
        ))
        idx = b.define_class(name=cls_mn, super_name=0, constructor=ctor)
        assert idx == 0
        # Only static init was auto-created
        assert len(b._methods) == 2


class TestAbcBuilderOpcodes:
    """Opcode encoding helpers."""

    def test_op_returnvoid(self):
        assert AbcBuilder.op_returnvoid() == bytes([0x47])

    def test_op_getlocal_0(self):
        assert AbcBuilder.op_getlocal_0() == bytes([0xD0])

    def test_op_pushscope(self):
        assert AbcBuilder.op_pushscope() == bytes([0x30])

    def test_op_pushstring(self):
        code = AbcBuilder.op_pushstring(5)
        assert code[0] == 0x2C
        assert len(code) == 2  # opcode + u30(5)

    def test_op_callpropvoid(self):
        code = AbcBuilder.op_callpropvoid(3, 1)
        assert code[0] == 0x4F

    def test_asm_concatenation(self):
        code = AbcBuilder.asm(
            AbcBuilder.op_getlocal_0(),
            AbcBuilder.op_pushscope(),
            AbcBuilder.op_returnvoid(),
        )
        assert code == bytes([0xD0, 0x30, 0x47])

    def test_op_jump(self):
        code = AbcBuilder.op_jump(0)
        assert code[0] == 0x10
        assert len(code) == 4  # opcode + 3 bytes s24

    def test_op_pushbyte(self):
        code = AbcBuilder.op_pushbyte(42)
        assert code == bytes([0x24, 42])


class TestAbcBuilderBuild:
    """Build and round-trip verification."""

    def test_build_minimal(self):
        b = AbcBuilder()
        abc = b.build()
        assert abc.major_version == 46
        assert abc.minor_version == 16
        assert len(abc.scripts) >= 1

    def test_build_auto_script(self):
        b = AbcBuilder()
        abc = b.build()
        assert len(abc.scripts) == 1

    def test_build_serialize_roundtrip(self):
        """Build → serialize → parse → serialize should produce identical bytes."""
        b = AbcBuilder()
        ns = b.package_namespace("com.test")
        cls_mn = b.qname(ns, "RoundTrip")
        obj_mn = b.qname(b.package_namespace(""), "Object")
        b.define_class(name=cls_mn, super_name=obj_mn)
        b.script()

        abc = b.build()
        raw1 = serialize_abc(abc)
        abc2 = parse_abc(raw1)
        raw2 = serialize_abc(abc2)
        assert raw1 == raw2

    def test_build_with_field_and_method(self):
        """Build a class with a field and method, verify structure survives round-trip."""
        b = AbcBuilder()
        ns = b.package_namespace("com.test")
        priv_ns = b.private_namespace()
        cls_mn = b.qname(ns, "Entity")
        obj_mn = b.qname(b.package_namespace(""), "Object")
        int_mn = b.qname(b.package_namespace(""), "int")
        str_mn = b.qname(b.package_namespace(""), "String")
        field_mn = b.qname(priv_ns, "health")
        method_mn = b.qname(priv_ns, "getName")

        # doStuff method
        get_name = b.method(params=[], return_type=str_mn)
        b.method_body(get_name, code=b.asm(
            b.op_getlocal_0(), b.op_pushscope(),
            b.op_pushstring(b.string("entity")),
            b.op_returnvalue(),
        ), max_stack=2, local_count=1)

        b.define_class(
            name=cls_mn, super_name=obj_mn,
            instance_traits=[
                b.trait_slot(field_mn, type_mn=int_mn, slot_id=1),
                b.trait_method(method_mn, get_name),
            ],
        )
        b.script()

        abc = b.build()
        raw = serialize_abc(abc)
        abc2 = parse_abc(raw)

        assert len(abc2.instances) == 1
        # Verify strings survived
        assert "Entity" in abc2.string_pool
        assert "health" in abc2.string_pool
        assert "getName" in abc2.string_pool
        assert "entity" in abc2.string_pool

    def test_build_class_resolves(self):
        """Classes built with AbcBuilder resolve correctly via build_all_classes."""
        b = AbcBuilder()
        ns = b.package_namespace("com.example")
        cls_mn = b.qname(ns, "Player")
        obj_mn = b.qname(b.package_namespace(""), "Object")
        int_mn = b.qname(b.package_namespace(""), "int")
        priv = b.private_namespace()
        hp_mn = b.qname(priv, "hp")

        b.define_class(
            name=cls_mn, super_name=obj_mn,
            instance_traits=[
                b.trait_slot(hp_mn, type_mn=int_mn, slot_id=1),
            ],
        )
        b.script()

        abc = b.build()
        raw = serialize_abc(abc)
        abc2 = parse_abc(raw)
        classes = build_all_classes(abc2)

        assert len(classes) == 1
        ci = classes[0]
        assert ci.name == "Player"
        assert ci.package == "com.example"
        assert ci.qualified_name == "com.example.Player"
        assert ci.super_name == "Object"
        assert len(ci.fields) == 1
        assert ci.fields[0].name == "hp"
        assert ci.fields[0].type_name == "int"


class TestAbcBuilderSimpleClass:
    """Tests for the simple_class() convenience method."""

    def test_basic(self):
        b = AbcBuilder()
        b.simple_class("Player", package="com.game")
        b.script()
        abc = b.build()
        raw = serialize_abc(abc)
        abc2 = parse_abc(raw)
        classes = build_all_classes(abc2)
        assert len(classes) == 1
        assert classes[0].name == "Player"
        assert classes[0].package == "com.game"

    def test_with_fields(self):
        b = AbcBuilder()
        b.simple_class("Entity", fields=[("hp", "int"), ("name", "String")])
        b.script()
        abc = b.build()
        raw = serialize_abc(abc)
        classes = build_all_classes(parse_abc(raw))
        ci = classes[0]
        assert len(ci.fields) == 2
        assert ci.fields[0].name == "hp"
        assert ci.fields[0].type_name == "int"
        assert ci.fields[1].name == "name"
        assert ci.fields[1].type_name == "String"

    def test_default_package(self):
        b = AbcBuilder()
        b.simple_class("Foo")
        b.script()
        abc = b.build()
        classes = build_all_classes(parse_abc(serialize_abc(abc)))
        assert classes[0].package == ""

    def test_interface(self):
        b = AbcBuilder()
        b.simple_class("IDrawable", is_interface=True)
        b.script()
        abc = b.build()
        classes = build_all_classes(parse_abc(serialize_abc(abc)))
        assert classes[0].is_interface is True

    def test_no_super(self):
        b = AbcBuilder()
        b.simple_class("Root", super_name=None)
        b.script()
        abc = b.build()
        classes = build_all_classes(parse_abc(serialize_abc(abc)))
        assert classes[0].super_name == "*"
