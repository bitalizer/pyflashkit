"""Tests for flashkit.analysis.const_args."""

from __future__ import annotations

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.parser import parse_abc
from flashkit.abc.writer import serialize_abc
from flashkit.analysis import ConstArgIndex


def _index_for_calls(caller_code: bytes):
    """Build an ABC whose class has a constructor with ``caller_code``
    inline, return a ConstArgIndex over the ABC."""
    b = AbcBuilder()
    pub = b.package_namespace("")
    cls = b.qname(pub, "Caller")
    ctor = b.method()
    b.method_body(
        ctor,
        code=b.asm(b.op_getlocal_0(), b.op_pushscope())
        + caller_code
        + b.asm(b.op_returnvoid()),
    )
    b.define_class(name=cls, super_name=0, constructor=ctor)
    b.script()
    raw = serialize_abc(b.build())
    abc = parse_abc(raw)
    return ConstArgIndex.from_abc(abc)


def test_string_literal_arg_captured():
    b = AbcBuilder()
    # Just rebuild everything in one go so the string indices resolve.
    pub = b.package_namespace("")
    cls = b.qname(pub, "Caller")
    target_mn = b.qname(pub, "SetFlag")
    str_idx = b.string("hello")
    ctor = b.method()
    b.method_body(
        ctor,
        code=b.asm(
            b.op_getlocal_0(), b.op_pushscope(),
            b.op_findpropstrict(target_mn),
            b.op_pushstring(str_idx),
            b.op_callpropvoid(target_mn, 1),
            b.op_returnvoid(),
        ),
    )
    b.define_class(name=cls, super_name=0, constructor=ctor)
    b.script()
    raw = serialize_abc(b.build())
    abc = parse_abc(raw)

    idx = ConstArgIndex.from_abc(abc)
    vals = idx.distinct_arg_values("SetFlag", 0)
    assert vals == {"hello"}


def test_pushbyte_arg_captured():
    b = AbcBuilder()
    pub = b.package_namespace("")
    cls = b.qname(pub, "Caller")
    target_mn = b.qname(pub, "SetFlag")
    ctor = b.method()
    b.method_body(
        ctor,
        code=b.asm(
            b.op_getlocal_0(), b.op_pushscope(),
            b.op_findpropstrict(target_mn),
            b.op_pushbyte(7),
            b.op_callpropvoid(target_mn, 1),
            b.op_returnvoid(),
        ),
    )
    b.define_class(name=cls, super_name=0, constructor=ctor)
    b.script()
    raw = serialize_abc(b.build())
    abc = parse_abc(raw)

    idx = ConstArgIndex.from_abc(abc)
    vals = idx.distinct_arg_values("SetFlag", 0)
    assert vals == {7}


def test_non_literal_arg_is_unknown():
    b = AbcBuilder()
    pub = b.package_namespace("")
    cls = b.qname(pub, "Caller")
    target_mn = b.qname(pub, "SetFlag")
    ctor = b.method()
    # getlocal_1 precedes the call — not a trivial push, so the
    # argument slot should stay UNKNOWN.
    b.method_body(
        ctor,
        code=b.asm(
            b.op_getlocal_0(), b.op_pushscope(),
            b.op_findpropstrict(target_mn),
            b.op_getlocal_1(),
            b.op_callpropvoid(target_mn, 1),
            b.op_returnvoid(),
        ),
    )
    b.define_class(name=cls, super_name=0, constructor=ctor)
    b.script()
    raw = serialize_abc(b.build())
    abc = parse_abc(raw)

    idx = ConstArgIndex.from_abc(abc)
    vals = idx.distinct_arg_values("SetFlag", 0)
    # Nothing literal was passed in slot 0.
    assert vals == set()
