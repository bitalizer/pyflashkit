"""Structural fingerprints of AS3 method bodies.

Extracts features from a decoded method body that describe its shape
independently of identifier names:

  - Signature: param count, builtin-only param types, return type, flags
  - Shape: code size, instruction count, max_stack, local_count, handlers
  - Control flow: branch count, lookupswitch case-count tuples
  - Ops: call/construct/getprop/setprop/getlex/new* counts, math/cmp/bit
  - Constants: int/uint/double/string literals from push* opcodes
  - Sequence: top opcode-category bigrams (READ/WRITE/CALL/BRANCH/...)

These features are useful for comparing methods across SWFs even when
class/field/method names differ, or for flagging methods with unusual
shape (heavy branching, many calls, etc.) during analysis.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from ..abc.disasm import decode_instructions
from ..abc.types import AbcFile
from ..errors import ABCParseError

log = logging.getLogger(__name__)
from ..info.class_info import ClassInfo
from ..info.member_info import (
    MethodInfoResolved,
    build_method_body_map,
    resolve_multiname,
)


__all__ = [
    "MethodFingerprint",
    "BUILTIN_TYPES",
    "BRANCH_MNEMONICS",
    "CALL_MNEMONICS",
    "CONSTRUCT_MNEMONICS",
    "ARITHMETIC_MNEMONICS",
    "COMPARISON_MNEMONICS",
    "BITWISE_MNEMONICS",
    "COERCE_MNEMONICS",
    "extract_fingerprint",
    "extract_constructor_fingerprint",
    "extract_all_fingerprints",
]


BUILTIN_TYPES: frozenset[str] = frozenset({
    'int', 'uint', 'Number', 'String', 'Boolean', 'void', 'Object',
    'Array', 'Class', 'Function', '*',
    'ByteArray', 'Dictionary', 'Date', 'RegExp', 'Error', 'XML',
    'Sprite', 'MovieClip', 'DisplayObject', 'DisplayObjectContainer',
    'BitmapData', 'Bitmap', 'Shape', 'TextField', 'TextFormat',
    'Event', 'MouseEvent', 'KeyboardEvent', 'TimerEvent',
    'Point', 'Rectangle', 'Matrix', 'ColorTransform',
    'Sound', 'SoundChannel', 'SoundTransform',
    'URLRequest', 'URLLoader', 'SharedObject',
    'Timer', 'Stage',
    'Vector.<int>', 'Vector.<uint>', 'Vector.<Number>', 'Vector.<String>',
    'Vector.<Boolean>', 'Vector.<Object>',
})


BRANCH_MNEMONICS: frozenset[str] = frozenset({
    'jump', 'iftrue', 'iffalse', 'ifeq', 'ifne', 'iflt', 'ifle',
    'ifgt', 'ifge', 'ifstricteq', 'ifstrictne',
    'ifnlt', 'ifnle', 'ifngt', 'ifnge',
})

CALL_MNEMONICS: frozenset[str] = frozenset({
    'callproperty', 'callpropvoid', 'callsuper', 'callsupervoid',
    'callmethod', 'callstatic', 'callproplex', 'call',
})

CONSTRUCT_MNEMONICS: frozenset[str] = frozenset({
    'constructprop', 'construct', 'constructsuper',
})

ARITHMETIC_MNEMONICS: frozenset[str] = frozenset({
    'add', 'subtract', 'multiply', 'divide', 'modulo', 'negate',
    'increment', 'decrement', 'increment_i', 'decrement_i',
    'inclocal', 'declocal', 'inclocal_i', 'declocal_i',
    'add_i', 'subtract_i', 'multiply_i', 'negate_i', 'add_d',
})

COMPARISON_MNEMONICS: frozenset[str] = frozenset({
    'equals', 'strictequals', 'lessthan', 'lessequals',
    'greaterthan', 'greaterequals', 'instanceof', 'istype',
    'istypelate', 'in', 'typeof',
})

BITWISE_MNEMONICS: frozenset[str] = frozenset({
    'bitor', 'bitand', 'bitxor', 'lshift', 'rshift', 'urshift', 'bitnot',
})

COERCE_MNEMONICS: frozenset[str] = frozenset({
    'coerce', 'coerce_a', 'coerce_s', 'coerce_b', 'coerce_i',
    'coerce_d', 'coerce_u', 'coerce_o',
    'convert_s', 'convert_i', 'convert_d', 'convert_b',
    'convert_u', 'convert_o',
})


@dataclass(frozen=True)
class MethodFingerprint:
    """Structural features of a single method body."""

    class_name: str
    method_name: str
    is_constructor: bool = False

    param_count: int = 0
    param_types_builtin: tuple[str, ...] = ()
    return_type: str = '?'
    is_static: bool = False
    is_getter: bool = False
    is_setter: bool = False

    code_size: int = 0
    instr_count: int = 0
    max_stack: int = 0
    local_count: int = 0
    exception_count: int = 0

    branch_count: int = 0
    switch_cases: tuple[int, ...] = ()
    call_count: int = 0
    construct_count: int = 0
    getprop_count: int = 0
    setprop_count: int = 0
    getlex_count: int = 0
    newarray_count: int = 0
    newobject_count: int = 0
    arithmetic_ops: int = 0
    comparison_ops: int = 0
    bitwise_ops: int = 0
    coerce_count: int = 0
    return_void: bool = True
    throw_count: int = 0

    int_constants: tuple[int, ...] = ()
    uint_constants: tuple[int, ...] = ()
    double_constants: tuple[float, ...] = ()
    string_constants: tuple[str, ...] = ()

    opcode_bigrams: tuple[tuple[tuple[str, str], int], ...] = ()


def _categorize_opcode(mnemonic: str) -> str:
    if mnemonic.startswith('get') or mnemonic.startswith('find'):
        return 'READ'
    if mnemonic.startswith('set') or mnemonic.startswith('init'):
        return 'WRITE'
    if mnemonic.startswith('push') or mnemonic == 'dup':
        return 'PUSH'
    if mnemonic.startswith('call'):
        return 'CALL'
    if mnemonic in BRANCH_MNEMONICS or mnemonic == 'lookupswitch':
        return 'BRANCH'
    if mnemonic in ARITHMETIC_MNEMONICS:
        return 'MATH'
    if mnemonic in COMPARISON_MNEMONICS:
        return 'CMP'
    if mnemonic in BITWISE_MNEMONICS:
        return 'BIT'
    if mnemonic.startswith('return'):
        return 'RET'
    if mnemonic in COERCE_MNEMONICS:
        return 'COERCE'
    if mnemonic.startswith('construct') or mnemonic.startswith('new'):
        return 'NEW'
    return 'OTHER'


def extract_fingerprint(
    cls: ClassInfo,
    method: MethodInfoResolved,
    abc: AbcFile,
    is_constructor: bool = False,
) -> Optional[MethodFingerprint]:
    """Produce a fingerprint for one method.

    Returns None if the body is missing or the bytecode can't be
    decoded.
    """

    body_idx = method.body_index
    if body_idx < 0 or body_idx >= len(abc.method_bodies):
        return None

    body = abc.method_bodies[body_idx]

    try:
        instrs = decode_instructions(body.code)
    except (ABCParseError, IndexError, ValueError) as exc:
        log.debug("method_fingerprint: decode failed for body=%d: %s",
                  body_idx, exc)
        return None

    if not instrs:
        return None

    def normalize_type(t: str) -> str:
        return t if t in BUILTIN_TYPES else '?'

    param_types_builtin = tuple(normalize_type(t) for t in method.param_types)
    return_type = normalize_type(method.return_type)

    branch_count = 0
    switch_cases: list[int] = []
    call_count = 0
    construct_count = 0
    getprop_count = 0
    setprop_count = 0
    getlex_count = 0
    newarray_count = 0
    newobject_count = 0
    arithmetic_ops = 0
    comparison_ops = 0
    bitwise_ops = 0
    coerce_count = 0
    has_returnvalue = False
    throw_count = 0

    int_constants: list[int] = []
    uint_constants: list[int] = []
    double_constants: list[float] = []
    string_constants: list[str] = []

    for instr in instrs:
        mn = instr.mnemonic

        if mn in BRANCH_MNEMONICS:
            branch_count += 1
        elif mn == 'lookupswitch':
            if len(instr.operands) >= 2:
                switch_cases.append(instr.operands[1])
        elif mn in CALL_MNEMONICS:
            call_count += 1
        elif mn in CONSTRUCT_MNEMONICS:
            construct_count += 1
        elif mn == 'getproperty':
            getprop_count += 1
        elif mn in ('setproperty', 'initproperty'):
            setprop_count += 1
        elif mn == 'getlex':
            getlex_count += 1
        elif mn == 'newarray':
            newarray_count += 1
        elif mn == 'newobject':
            newobject_count += 1
        elif mn in ARITHMETIC_MNEMONICS:
            arithmetic_ops += 1
        elif mn in COMPARISON_MNEMONICS:
            comparison_ops += 1
        elif mn in BITWISE_MNEMONICS:
            bitwise_ops += 1
        elif mn in COERCE_MNEMONICS:
            coerce_count += 1
        elif mn == 'returnvalue':
            has_returnvalue = True
        elif mn == 'throw':
            throw_count += 1

        if mn == 'pushbyte' and instr.operands:
            int_constants.append(instr.operands[0])
        elif mn == 'pushshort' and instr.operands:
            int_constants.append(instr.operands[0])
        elif mn == 'pushint' and instr.operands:
            idx = instr.operands[0]
            if 0 < idx < len(abc.int_pool):
                int_constants.append(abc.int_pool[idx])
        elif mn == 'pushuint' and instr.operands:
            idx = instr.operands[0]
            if 0 < idx < len(abc.uint_pool):
                uint_constants.append(abc.uint_pool[idx])
        elif mn == 'pushdouble' and instr.operands:
            idx = instr.operands[0]
            if 0 < idx < len(abc.double_pool):
                double_constants.append(abc.double_pool[idx])
        elif mn == 'pushstring' and instr.operands:
            idx = instr.operands[0]
            if 0 < idx < len(abc.string_pool):
                string_constants.append(abc.string_pool[idx])

    categories = [_categorize_opcode(i.mnemonic) for i in instrs]
    bigram_counter: Counter = Counter()
    for i in range(len(categories) - 1):
        bigram_counter[(categories[i], categories[i + 1])] += 1
    top_bigrams = tuple(sorted(bigram_counter.items(), key=lambda x: -x[1])[:15])

    return MethodFingerprint(
        class_name=cls.name,
        method_name=method.name if not is_constructor else '<constructor>',
        is_constructor=is_constructor,
        param_count=len(method.param_types),
        param_types_builtin=param_types_builtin,
        return_type=return_type,
        is_static=method.is_static,
        is_getter=method.is_getter,
        is_setter=method.is_setter,
        code_size=len(body.code),
        instr_count=len(instrs),
        max_stack=body.max_stack,
        local_count=body.local_count,
        exception_count=len(body.exceptions),
        branch_count=branch_count,
        switch_cases=tuple(sorted(switch_cases)),
        call_count=call_count,
        construct_count=construct_count,
        getprop_count=getprop_count,
        setprop_count=setprop_count,
        getlex_count=getlex_count,
        newarray_count=newarray_count,
        newobject_count=newobject_count,
        arithmetic_ops=arithmetic_ops,
        comparison_ops=comparison_ops,
        bitwise_ops=bitwise_ops,
        coerce_count=coerce_count,
        return_void=not has_returnvalue,
        throw_count=throw_count,
        int_constants=tuple(sorted(int_constants)),
        uint_constants=tuple(sorted(uint_constants)),
        double_constants=tuple(sorted(double_constants)),
        string_constants=tuple(sorted(string_constants)),
        opcode_bigrams=top_bigrams,
    )


def extract_constructor_fingerprint(
    cls: ClassInfo,
    abc: AbcFile,
) -> Optional[MethodFingerprint]:
    """Fingerprint a class constructor (iinit).

    Returns None if the constructor has no body.
    """
    method_idx = cls.constructor_index
    if method_idx >= len(abc.methods):
        return None

    mi = abc.methods[method_idx]
    param_types = [resolve_multiname(abc, pt) for pt in mi.param_types]
    ret_type = resolve_multiname(abc, mi.return_type)

    body_map = build_method_body_map(abc)
    body_idx = body_map.get(method_idx, -1)
    if body_idx < 0:
        return None

    fake_method = MethodInfoResolved(
        name='<constructor>',
        param_types=param_types,
        return_type=ret_type,
        body_index=body_idx,
        method_index=method_idx,
    )

    return extract_fingerprint(cls, fake_method, abc, is_constructor=True)


def extract_all_fingerprints(
    cls: ClassInfo,
    abc: AbcFile,
) -> list[MethodFingerprint]:
    """Fingerprint the constructor plus every method of `cls`."""
    fps: list[MethodFingerprint] = []

    ctor_fp = extract_constructor_fingerprint(cls, abc)
    if ctor_fp:
        fps.append(ctor_fp)

    for m in cls.all_methods:
        fp = extract_fingerprint(cls, m, abc)
        if fp:
            fps.append(fp)

    return fps
