"""Tests for flashkit.analysis.liveness."""

from __future__ import annotations

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.parser import parse_abc
from flashkit.abc.writer import serialize_abc
from flashkit.analysis import method_liveness, LocalLiveness


def _build_body(code: bytes, local_count: int = 2) -> tuple:
    b = AbcBuilder()
    ns = b.package_namespace(0)
    mn = b.qname(ns, b.string("Foo"))
    m = b.method()
    b.method_body(m, code=code, local_count=local_count)
    b.define_class(name=mn, super_name=0, constructor=m)
    b.script()
    raw = serialize_abc(b.build())
    abc = parse_abc(raw)
    return abc, abc.method_bodies[0]


def test_liveness_empty_body():
    # Just a returnvoid.
    abc, body = _build_body(bytes([0x47]))
    liv = method_liveness(abc, body)
    assert liv is not None
    assert liv.reads == ()
    assert liv.writes == ()


def test_liveness_detects_getlocal_short_forms():
    # getlocal_0, getlocal_1, returnvoid
    abc, body = _build_body(bytes([0xD0, 0xD1, 0x47]))
    liv = method_liveness(abc, body)
    assert liv is not None
    assert liv.reads == (0, 1)
    assert liv.writes == ()
    assert liv.is_read_only(0)
    assert liv.is_read_only(1)


def test_liveness_detects_setlocal_short_forms():
    # getlocal_0 (push scope chain), setlocal_1, returnvoid
    abc, body = _build_body(bytes([0xD0, 0xD5, 0x47]))
    liv = method_liveness(abc, body)
    assert liv is not None
    assert liv.reads == (0,)
    assert liv.writes == (1,)
    assert liv.is_write_only(1)


def test_liveness_counts_accesses():
    # getlocal_0, getlocal_0, getlocal_0, returnvoid
    abc, body = _build_body(bytes([0xD0, 0xD0, 0xD0, 0x47]))
    liv = method_liveness(abc, body)
    assert liv is not None
    assert liv.read_counts[0] == 3


def test_liveness_unused_register():
    # Only register 0 is touched; register 1 is never read/written.
    abc, body = _build_body(bytes([0xD0, 0x47]))
    liv = method_liveness(abc, body)
    assert liv is not None
    assert liv.is_unused(1)
    assert not liv.is_unused(0)
