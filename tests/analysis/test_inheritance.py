"""Tests for flashkit.analysis.inheritance — InheritanceGraph."""

import pytest

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.parser import parse_abc
from flashkit.abc.writer import serialize_abc
from flashkit.abc.constants import INSTANCE_Interface
from flashkit.info.class_info import build_all_classes
from flashkit.analysis.inheritance import InheritanceGraph


def _build_classes(defs):
    """Build classes from a list of (package, name, super_name, interfaces, is_interface) tuples.

    super_name can be a (pkg, name) tuple or just a name string.
    interfaces is a list of name strings.
    """
    b = AbcBuilder()
    pub = b.package_namespace("")

    # Pre-create all multinames
    class_mns = {}
    for pkg, name, super_name, interfaces, is_iface in defs:
        ns = b.package_namespace(pkg)
        class_mns[(pkg, name)] = b.qname(ns, name)

    obj_mn = b.qname(pub, "Object")

    for pkg, name, super_name, interfaces, is_iface in defs:
        cls_mn = class_mns[(pkg, name)]

        # Resolve super_name
        if super_name is None:
            super_mn = obj_mn
        elif isinstance(super_name, tuple):
            sp, sn = super_name
            super_mn = class_mns.get((sp, sn), b.qname(b.package_namespace(sp), sn))
        else:
            super_mn = class_mns.get(("", super_name), b.qname(pub, super_name))

        # Resolve interfaces
        iface_mns = []
        for iface in interfaces:
            iface_mns.append(b.qname(pub, iface))

        import flashkit.abc.constants as c
        flags = c.INSTANCE_Interface if is_iface else c.INSTANCE_Sealed

        b.define_class(name=cls_mn, super_name=super_mn, flags=flags,
                       interfaces=iface_mns)

    b.script()
    abc = b.build()
    raw = serialize_abc(abc)
    abc2 = parse_abc(raw)
    return build_all_classes(abc2)


class TestInheritanceBasic:
    def test_single_class(self):
        classes = _build_classes([
            ("com.test", "Foo", None, [], False),
        ])
        graph = InheritanceGraph.from_classes(classes)
        assert "com.test.Foo" in graph.classes

    def test_parent_child(self):
        classes = _build_classes([
            ("com.test", "Base", None, [], False),
            ("com.test", "Child", ("com.test", "Base"), [], False),
        ])
        graph = InheritanceGraph.from_classes(classes)

        parent = graph.get_parent("com.test.Child")
        assert parent == "com.test.Base"

        children = graph.get_children("com.test.Base")
        assert "com.test.Child" in children

    def test_simple_name_lookup(self):
        classes = _build_classes([
            ("com.test", "Base", None, [], False),
            ("com.test", "Child", ("com.test", "Base"), [], False),
        ])
        graph = InheritanceGraph.from_classes(classes)
        # Should resolve simple name "Base" to "com.test.Base"
        children = graph.get_children("Base")
        assert "com.test.Child" in children


class TestInheritanceChain:
    def test_get_all_parents(self):
        classes = _build_classes([
            ("", "A", None, [], False),
            ("", "B", ("", "A"), [], False),
            ("", "C", ("", "B"), [], False),
        ])
        graph = InheritanceGraph.from_classes(classes)
        parents = graph.get_all_parents("C")
        assert "B" in parents
        assert "A" in parents

    def test_get_all_children(self):
        classes = _build_classes([
            ("", "Root", None, [], False),
            ("", "Mid", ("", "Root"), [], False),
            ("", "Leaf", ("", "Mid"), [], False),
        ])
        graph = InheritanceGraph.from_classes(classes)
        descendants = graph.get_all_children("Root")
        assert "Mid" in descendants
        assert "Leaf" in descendants

    def test_depth(self):
        classes = _build_classes([
            ("", "A", None, [], False),
            ("", "B", ("", "A"), [], False),
            ("", "C", ("", "B"), [], False),
        ])
        graph = InheritanceGraph.from_classes(classes)
        assert graph.get_depth("A") == 1  # Object is parent
        assert graph.get_depth("B") == 2
        assert graph.get_depth("C") == 3

    def test_is_subclass(self):
        classes = _build_classes([
            ("", "A", None, [], False),
            ("", "B", ("", "A"), [], False),
            ("", "C", ("", "B"), [], False),
        ])
        graph = InheritanceGraph.from_classes(classes)
        assert graph.is_subclass("C", "A") is True
        assert graph.is_subclass("A", "C") is False


class TestInheritanceInterfaces:
    def test_interface_implementors(self):
        classes = _build_classes([
            ("", "IDrawable", None, [], True),
            ("", "Sprite", None, ["IDrawable"], False),
            ("", "Circle", None, ["IDrawable"], False),
        ])
        graph = InheritanceGraph.from_classes(classes)
        impls = graph.get_implementors("IDrawable")
        assert "Sprite" in impls
        assert "Circle" in impls

    def test_get_interfaces(self):
        classes = _build_classes([
            ("", "IFoo", None, [], True),
            ("", "IBar", None, [], True),
            ("", "Baz", None, ["IFoo", "IBar"], False),
        ])
        graph = InheritanceGraph.from_classes(classes)
        ifaces = graph.get_interfaces("Baz")
        assert "IFoo" in ifaces
        assert "IBar" in ifaces


class TestInheritanceSiblings:
    def test_siblings(self):
        classes = _build_classes([
            ("", "Parent", None, [], False),
            ("", "Child1", ("", "Parent"), [], False),
            ("", "Child2", ("", "Parent"), [], False),
        ])
        graph = InheritanceGraph.from_classes(classes)
        siblings = graph.get_siblings("Child1")
        assert "Child2" in siblings
        assert "Child1" not in siblings


class TestInheritanceRoots:
    def test_get_roots(self):
        classes = _build_classes([
            ("", "Root1", None, [], False),
            ("", "Root2", None, [], False),
            ("", "Child", ("", "Root1"), [], False),
        ])
        graph = InheritanceGraph.from_classes(classes)
        roots = graph.get_roots()
        assert "Root1" in roots
        assert "Root2" in roots
        assert "Child" not in roots


class TestInheritanceEdgeCases:
    def test_not_found(self):
        graph = InheritanceGraph()
        assert graph.get_parent("Nonexistent") is None
        assert graph.get_children("Nonexistent") == []
        assert graph.get_depth("Nonexistent") == -1
