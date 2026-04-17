"""Tests for flashkit.analysis.complexity."""

from __future__ import annotations

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.parser import parse_abc
from flashkit.abc.writer import serialize_abc
from flashkit.analysis import cfg_complexity, method_complexity
from flashkit.graph.cfg import build_cfg_from_bytecode
from flashkit.abc.disasm import decode_instructions


def _body(code: bytes):
    b = AbcBuilder()
    ns = b.package_namespace(0)
    mn = b.qname(ns, b.string("Foo"))
    m = b.method()
    b.method_body(m, code=code)
    b.define_class(name=mn, super_name=0, constructor=m)
    b.script()
    raw = serialize_abc(b.build())
    abc = parse_abc(raw)
    return abc, abc.method_bodies[0]


def test_complexity_straight_line():
    # returnvoid only — one block, complexity 1.
    abc, body = _body(bytes([0x47]))
    mc = method_complexity(abc, body)
    assert mc is not None
    assert mc.complexity == 1
    assert mc.block_count == 1


def test_complexity_empty_cfg_floor():
    instrs = decode_instructions(b"")
    cfg = build_cfg_from_bytecode(instrs, [])
    # Empty CFG floors at 1.
    assert cfg_complexity(cfg) == 1


def test_method_complexity_handles_invalid_bytecode():
    # 0xFE is an undefined opcode; decode raises, and method_complexity
    # returns None rather than crashing.
    abc, _ = _body(bytes([0x47]))
    # Manually corrupt the body.
    abc.method_bodies[0].code = bytes([0xFE, 0xFE, 0xFE])
    mc = method_complexity(abc, abc.method_bodies[0])
    # Either returns None (decode failed) or a valid result —
    # 0xFE may be unassigned but the decoder is tolerant. Either way,
    # no crash is the contract.
    assert mc is None or mc.complexity >= 1
