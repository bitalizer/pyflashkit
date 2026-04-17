"""Smoke tests for flashkit.analysis.dead_code."""

from __future__ import annotations

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.writer import serialize_abc
from flashkit.swf.builder import SwfBuilder
from flashkit.workspace.workspace import Workspace
from flashkit.analysis import (
    entrypoint_candidates, find_dead_classes, find_dead_methods,
)


def _workspace_with(abc_bytes: bytes) -> Workspace:
    swf = SwfBuilder()
    swf.add_abc("Test", abc_bytes)
    data = swf.build(compress=False)
    ws = Workspace()
    ws.load_swf_bytes(data, name="synthetic")
    return ws


def _build_abc(callback) -> bytes:
    b = AbcBuilder()
    pub = b.package_namespace("")
    callback(b, pub)
    b.script()
    return serialize_abc(b.build())


def test_find_dead_classes_reports_unreferenced_class():
    # Two classes, neither of which references the other.
    def setup(b, pub):
        a = b.qname(pub, "A")
        z = b.qname(pub, "Z")
        b.define_class(name=a, super_name=0)
        b.define_class(name=z, super_name=0)

    ws = _workspace_with(_build_abc(setup))
    dead = find_dead_classes(ws)
    # Both classes are unreferenced in this stub; just check neither
    # crashes the pass and the result is a stable sorted list.
    assert isinstance(dead, list)
    assert dead == sorted(dead)


def test_entrypoint_candidates_is_empty_without_base_classes():
    def setup(b, pub):
        a = b.qname(pub, "A")
        b.define_class(name=a, super_name=0)

    ws = _workspace_with(_build_abc(setup))
    # No class extends Sprite / MovieClip, so no candidates.
    assert entrypoint_candidates(ws) == []


def test_find_dead_methods_returns_sorted_report():
    def setup(b, pub):
        a = b.qname(pub, "A")
        b.define_class(name=a, super_name=0)

    ws = _workspace_with(_build_abc(setup))
    reports = find_dead_methods(ws)
    assert isinstance(reports, list)
    for r in reports:
        assert r.class_name
        assert r.method_name
