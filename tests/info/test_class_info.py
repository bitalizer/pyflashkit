"""Tests for flashkit.info.class_info — resolved class model."""

import pytest

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.parser import parse_abc
from flashkit.abc.writer import serialize_abc
from flashkit.abc.constants import TRAIT_Getter, TRAIT_Setter, INSTANCE_Interface
from flashkit.info.class_info import build_all_classes, build_class_info


def _build_single_class(name="MyClass", package="com.test",
                        super_name="Object", fields=None, methods=None,
                        is_interface=False, interfaces=None):
    """Helper to build a single class and resolve it."""
    b = AbcBuilder()
    ns = b.package_namespace(package)
    priv = b.private_namespace()
    pub = b.package_namespace("")
    cls_mn = b.qname(ns, name)
    obj_mn = b.qname(pub, super_name) if super_name else 0

    # Build interface multinames
    iface_mns = []
    if interfaces:
        for iface in interfaces:
            iface_mns.append(b.qname(pub, iface))

    # Build instance traits
    instance_traits = []
    if fields:
        for fname, ftype in fields:
            type_mn = b.qname(pub, ftype) if ftype else 0
            field_mn = b.qname(priv, fname)
            instance_traits.append(b.trait_slot(field_mn, type_mn=type_mn, slot_id=len(instance_traits)+1))
    if methods:
        for mname, ret_type, params, kind in methods:
            ret_mn = b.qname(pub, ret_type) if ret_type else 0
            param_mns = [b.qname(pub, pt) for pt in params] if params else []
            m = b.method(params=param_mns, return_type=ret_mn)
            b.method_body(m, code=b.asm(b.op_getlocal_0(), b.op_pushscope(), b.op_returnvoid()))
            method_mn = b.qname(priv, mname)
            instance_traits.append(b.trait_method(method_mn, m, kind=kind))

    import flashkit.abc.constants as c
    flags = 0
    if is_interface:
        flags = c.INSTANCE_Interface
    else:
        flags = c.INSTANCE_Sealed

    b.define_class(
        name=cls_mn, super_name=obj_mn, flags=flags,
        instance_traits=instance_traits, interfaces=iface_mns,
    )
    b.script()

    abc = b.build()
    raw = serialize_abc(abc)
    abc2 = parse_abc(raw)
    return build_all_classes(abc2)


class TestBuildClassInfo:
    def test_basic_class(self):
        classes = _build_single_class("Player", "com.game")
        assert len(classes) == 1
        ci = classes[0]
        assert ci.name == "Player"
        assert ci.package == "com.game"
        assert ci.qualified_name == "com.game.Player"

    def test_super_name(self):
        classes = _build_single_class(super_name="Sprite")
        ci = classes[0]
        assert ci.super_name == "Sprite"

    def test_fields_resolved(self):
        classes = _build_single_class(
            fields=[("health", "int"), ("name", "String")])
        ci = classes[0]
        assert len(ci.fields) == 2
        assert ci.fields[0].name == "health"
        assert ci.fields[0].type_name == "int"
        assert ci.fields[1].name == "name"
        assert ci.fields[1].type_name == "String"

    def test_methods_resolved(self):
        from flashkit.abc.constants import TRAIT_Method
        classes = _build_single_class(
            methods=[("attack", "void", ["int"], TRAIT_Method)])
        ci = classes[0]
        assert len(ci.methods) == 1
        assert ci.methods[0].name == "attack"
        assert ci.methods[0].return_type == "void"
        assert ci.methods[0].param_types == ["int"]

    def test_getter_setter(self):
        classes = _build_single_class(
            methods=[
                ("hp", "int", [], TRAIT_Getter),
                ("hp", "void", ["int"], TRAIT_Setter),
            ])
        ci = classes[0]
        getters = [m for m in ci.methods if m.is_getter]
        setters = [m for m in ci.methods if m.is_setter]
        assert len(getters) == 1
        assert len(setters) == 1

    def test_interface_flag(self):
        classes = _build_single_class("IDisposable", is_interface=True)
        ci = classes[0]
        assert ci.is_interface is True

    def test_get_field(self):
        classes = _build_single_class(fields=[("score", "int")])
        ci = classes[0]
        f = ci.get_field("score")
        assert f is not None
        assert f.type_name == "int"
        assert ci.get_field("nonexistent") is None

    def test_get_method(self):
        from flashkit.abc.constants import TRAIT_Method
        classes = _build_single_class(
            methods=[("run", "void", [], TRAIT_Method)])
        ci = classes[0]
        m = ci.get_method("run")
        assert m is not None
        assert m.return_type == "void"
        assert ci.get_method("nonexistent") is None

    def test_all_fields_includes_static(self):
        """all_fields property includes both instance and static fields."""
        # We only build instance fields via the helper, but verify the property
        classes = _build_single_class(fields=[("x", "int")])
        ci = classes[0]
        assert len(ci.all_fields) >= 1


class TestMultipleClasses:
    def test_two_classes(self):
        b = AbcBuilder()
        ns = b.package_namespace("com.test")
        pub = b.package_namespace("")

        a_mn = b.qname(ns, "ClassA")
        b_mn = b.qname(ns, "ClassB")
        obj = b.qname(pub, "Object")

        b.define_class(name=a_mn, super_name=obj)
        b.define_class(name=b_mn, super_name=a_mn)
        b.script()

        abc = b.build()
        raw = serialize_abc(abc)
        abc2 = parse_abc(raw)
        classes = build_all_classes(abc2)

        assert len(classes) == 2
        names = {c.name for c in classes}
        assert names == {"ClassA", "ClassB"}

        class_b = next(c for c in classes if c.name == "ClassB")
        assert class_b.super_name == "ClassA"


class TestWorkspaceProperty:
    """Tests for ClassInfo.workspace public property (1.2.0 API)."""

    def test_workspace_property(self, loaded_workspace):
        cls = loaded_workspace.get_class("TestClass")
        assert cls is not None
        assert cls.workspace is loaded_workspace

    def test_workspace_property_raises_when_standalone(self):
        from flashkit.info.class_info import ClassInfo
        cls = ClassInfo(name="Orphan")
        with pytest.raises(RuntimeError, match="not attached to a Workspace"):
            cls.workspace
