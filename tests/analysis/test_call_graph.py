"""Tests for flashkit.analysis.call_graph — CallGraph from bytecode."""

import pytest

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.parser import parse_abc
from flashkit.abc.writer import serialize_abc
from flashkit.abc.constants import TRAIT_METHOD
from flashkit.info.class_info import build_all_classes
from flashkit.analysis.call_graph import CallGraph


def _build_call_graph(setup_fn):
    """Helper: run setup_fn with an AbcBuilder, build, and create CallGraph.

    setup_fn receives (builder, pub_ns) and should define classes.
    Returns (CallGraph, classes).
    """
    b = AbcBuilder()
    pub = b.package_namespace("")
    setup_fn(b, pub)
    b.script()

    abc = b.build()
    raw = serialize_abc(abc)
    abc2 = parse_abc(raw)
    classes = build_all_classes(abc2)
    graph = CallGraph.from_abc(abc2, classes)
    return graph, classes


class TestCallGraphBasic:
    def test_no_calls(self):
        """A class with no call instructions should produce no edges."""
        def setup(b, pub):
            cls_mn = b.qname(pub, "Empty")
            b.define_class(name=cls_mn, super_name=0)

        graph, _ = _build_call_graph(setup)
        # Only constructsuper call from auto-generated constructor
        call_edges = [e for e in graph.edges if e.edge_type == "call"]
        # No callproperty/callpropvoid edges
        assert len(call_edges) == 0

    def test_callpropvoid_edge(self):
        """A method calling another property should create a call edge."""
        def setup(b, pub):
            priv = b.private_namespace()
            cls_mn = b.qname(pub, "Caller")
            target_mn = b.qname(pub, "trace")

            m = b.method()
            b.method_body(m, code=b.asm(
                b.op_getlocal_0(), b.op_pushscope(),
                b.op_findpropstrict(target_mn),
                b.op_pushstring(b.string("hello")),
                b.op_callpropvoid(target_mn, 1),
                b.op_returnvoid(),
            ), max_stack=3, local_count=1)

            method_mn = b.qname(priv, "doStuff")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_method(method_mn, m)])

        graph, classes = _build_call_graph(setup)
        call_edges = [e for e in graph.edges if e.edge_type == "call"]
        targets = [e.target for e in call_edges]
        assert "trace" in targets

    def test_constructprop_edge(self):
        """constructprop should create a 'construct' edge."""
        def setup(b, pub):
            priv = b.private_namespace()
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

        graph, _ = _build_call_graph(setup)
        construct_edges = [e for e in graph.edges if e.edge_type == "construct"]
        targets = [e.target for e in construct_edges]
        assert "Widget" in targets


class TestCallGraphQueries:
    def _build_with_calls(self):
        def setup(b, pub):
            priv = b.private_namespace()
            cls_mn = b.qname(pub, "App")
            run_mn = b.qname(pub, "run")
            init_mn = b.qname(pub, "init")

            m = b.method()
            b.method_body(m, code=b.asm(
                b.op_getlocal_0(), b.op_pushscope(),
                b.op_getlocal_0(),
                b.op_callpropvoid(run_mn, 0),
                b.op_getlocal_0(),
                b.op_callpropvoid(init_mn, 0),
                b.op_returnvoid(),
            ), max_stack=2, local_count=1)

            method_mn = b.qname(priv, "start")
            b.define_class(
                name=cls_mn, super_name=0,
                instance_traits=[b.trait_method(method_mn, m)])

        return _build_call_graph(setup)

    def test_get_callers(self):
        graph, _ = self._build_with_calls()
        callers = graph.get_callers("run")
        assert len(callers) >= 1

    def test_get_callees(self):
        graph, classes = self._build_with_calls()
        # Find the "start" method's caller name
        start_callers = [e.caller for e in graph.edges
                         if "start" in e.caller]
        if start_callers:
            callees = graph.get_callees(start_callers[0])
            targets = [e.target for e in callees if e.edge_type == "call"]
            assert "run" in targets
            assert "init" in targets

    def test_get_unique_callers(self):
        graph, _ = self._build_with_calls()
        unique = graph.get_unique_callers("run")
        assert len(unique) >= 1

    def test_edge_count(self):
        graph, _ = self._build_with_calls()
        assert graph.edge_count > 0

    def test_unique_targets(self):
        graph, _ = self._build_with_calls()
        assert graph.unique_targets > 0


class TestCallGraphGetlex:
    def test_getlex_creates_read_edge(self):
        def setup(b, pub):
            priv = b.private_namespace()
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

        graph, _ = _build_call_graph(setup)
        read_edges = [e for e in graph.edges
                      if e.edge_type == "read" and e.target == "Config"]
        assert len(read_edges) >= 1
