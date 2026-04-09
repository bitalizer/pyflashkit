"""
AVM2 bytecode disassembler / instruction decoder.

Walks the raw bytecode in ``MethodBodyInfo.code`` and yields structured
``Instruction`` objects. This is the foundation for call graph analysis,
cross-reference indexing, and string constant discovery.

Usage::

    from flashkit.abc.disasm import decode_instructions

    for instr in decode_instructions(method_body.code):
        print(f"0x{instr.offset:04X}  {instr.mnemonic}  {instr.operands}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..errors import ABCParseError
from .parser import read_u30, read_u8
from .constants import *

log = logging.getLogger(__name__)


@dataclass
class Instruction:
    """A single decoded AVM2 instruction.

    Attributes:
        offset: Byte offset of this instruction in the method body code.
        opcode: Opcode byte value.
        mnemonic: Human-readable opcode name.
        operands: List of decoded operand values.
        size: Total size in bytes (opcode + operands).
    """
    offset: int
    opcode: int
    mnemonic: str
    operands: list[int] = field(default_factory=list)
    size: int = 1


# ── Opcode table ────────────────────────────────────────────────────────────
# Maps opcode → (mnemonic, operand_format)
# Operand formats:
#   ""       = no operands
#   "u30"    = one u30
#   "u30u30" = two u30s
#   "u8"     = one byte
#   "s24"    = signed 24-bit offset
#   "u30u8"  = u30 + byte (hasnext2 uses this differently, but close enough)
#   "special" = handled individually (lookupswitch, debug)

_OPCODE_TABLE: dict[int, tuple[str, str]] = {
    # Control flow
    OP_nop:            ("nop",            ""),
    OP_throw:          ("throw",          ""),
    OP_label:          ("label",          ""),
    OP_jump:           ("jump",           "s24"),
    OP_iftrue:         ("iftrue",         "s24"),
    OP_iffalse:        ("iffalse",        "s24"),
    OP_ifeq:           ("ifeq",           "s24"),
    OP_ifne:           ("ifne",           "s24"),
    OP_iflt:           ("iflt",           "s24"),
    OP_ifle:           ("ifle",           "s24"),
    OP_ifgt:           ("ifgt",           "s24"),
    OP_ifge:           ("ifge",           "s24"),
    OP_ifstricteq:     ("ifstricteq",     "s24"),
    OP_ifstrictne:     ("ifstrictne",     "s24"),
    OP_lookupswitch:   ("lookupswitch",   "special"),

    # Scope
    OP_pushwith:       ("pushwith",       ""),
    OP_popscope:       ("popscope",       ""),
    OP_pushscope:      ("pushscope",      ""),
    OP_getscopeobject: ("getscopeobject", "u30"),

    # Stack
    OP_pop:            ("pop",            ""),
    OP_dup:            ("dup",            ""),
    OP_swap:           ("swap",           ""),

    # Push constants
    OP_pushnull:       ("pushnull",       ""),
    OP_pushundefined:  ("pushundefined",  ""),
    OP_pushtrue:       ("pushtrue",       ""),
    OP_pushfalse:      ("pushfalse",      ""),
    OP_pushnan:        ("pushnan",        ""),
    OP_pushbyte:       ("pushbyte",       "u8"),
    OP_pushshort:      ("pushshort",      "u30"),
    OP_pushstring:     ("pushstring",     "u30"),
    OP_pushint:        ("pushint",        "u30"),
    OP_pushuint:       ("pushuint",       "u30"),
    OP_pushdouble:     ("pushdouble",     "u30"),

    # Iteration
    OP_nextname:       ("nextname",       ""),
    OP_hasnext:        ("hasnext",        ""),
    OP_nextvalue:      ("nextvalue",      ""),
    OP_hasnext2:       ("hasnext2",       "u30u30"),

    # Locals
    OP_getlocal:       ("getlocal",       "u30"),
    OP_setlocal:       ("setlocal",       "u30"),
    OP_getlocal_0:     ("getlocal_0",     ""),
    OP_getlocal_1:     ("getlocal_1",     ""),
    OP_getlocal_2:     ("getlocal_2",     ""),
    OP_getlocal_3:     ("getlocal_3",     ""),
    OP_setlocal_0:     ("setlocal_0",     ""),
    OP_setlocal_1:     ("setlocal_1",     ""),
    OP_setlocal_2:     ("setlocal_2",     ""),
    OP_setlocal_3:     ("setlocal_3",     ""),

    # Properties
    OP_getproperty:    ("getproperty",    "u30"),
    OP_setproperty:    ("setproperty",    "u30"),
    OP_initproperty:   ("initproperty",   "u30"),
    OP_getlex:         ("getlex",         "u30"),
    OP_findpropstrict: ("findpropstrict", "u30"),

    # Calls
    OP_call:           ("call",           "u30"),
    OP_construct:      ("construct",      "u30"),
    OP_callproperty:   ("callproperty",   "u30u30"),
    OP_returnvoid:     ("returnvoid",     ""),
    OP_returnvalue:    ("returnvalue",    ""),
    OP_constructsuper: ("constructsuper",  "u30"),
    OP_constructprop:  ("constructprop",  "u30u30"),
    OP_callpropvoid:   ("callpropvoid",   "u30u30"),

    # Object creation
    OP_newfunction:    ("newfunction",    "u30"),
    OP_newarray:       ("newarray",       "u30"),
    OP_newclass:       ("newclass",       "u30"),

    # Type conversion
    OP_convert_s:      ("convert_s",      ""),
    OP_convert_i:      ("convert_i",      ""),
    OP_convert_d:      ("convert_d",      ""),
    OP_coerce:         ("coerce",         "u30"),
    OP_coerce_a:       ("coerce_a",       ""),
    OP_coerce_s:       ("coerce_s",       ""),

    # Comparison & logic
    OP_typeof:         ("typeof",         ""),
    OP_not:            ("not",            ""),
    OP_equals:         ("equals",         ""),
    OP_strictequals:   ("strictequals",   ""),
    OP_lessthan:       ("lessthan",       ""),
    OP_lessequals:     ("lessequals",     ""),
    OP_greaterthan:    ("greaterthan",    ""),
    OP_greaterequals:  ("greaterequals",  ""),

    # Arithmetic
    OP_increment:      ("increment",      ""),
    OP_decrement:      ("decrement",      ""),
    OP_add:            ("add",            ""),
    OP_subtract:       ("subtract",       ""),
    OP_multiply:       ("multiply",       ""),
    OP_divide:         ("divide",         ""),
    OP_modulo:         ("modulo",         ""),
    OP_increment_i:    ("increment_i",    ""),
    OP_decrement_i:    ("decrement_i",    ""),

    # Bitwise
    OP_bitor:          ("bitor",          ""),
    OP_bitand:         ("bitand",         ""),
    OP_bitxor:         ("bitxor",         ""),
    OP_lshift:         ("lshift",         ""),
    OP_rshift:         ("rshift",         ""),
    OP_urshift:        ("urshift",        ""),
    OP_bitnot:         ("bitnot",         ""),

    # Debugging
    OP_debug:          ("debug",          "special"),
    OP_debugline:      ("debugline",      "u30"),
    OP_debugfile:      ("debugfile",      "u30"),
}

# Additional opcodes not in our OP_ constants but valid AVM2
_EXTRA_OPCODES: dict[int, tuple[str, str]] = {
    0x04: ("getsuper",        "u30"),
    0x05: ("setsuper",        "u30"),
    0x06: ("dxns",            "u30"),
    0x07: ("dxnslate",        ""),
    0x08: ("kill",            "u30"),
    0x0C: ("ifnlt",           "s24"),
    0x0D: ("ifnle",           "s24"),
    0x0E: ("ifngt",           "s24"),
    0x0F: ("ifnge",           "s24"),
    0x1E: ("nextname",        ""),
    0x30: ("pushscope",       ""),
    0x43: ("callmethod",      "u30u30"),
    0x44: ("callstatic",      "u30u30"),
    0x45: ("callsuper",       "u30u30"),
    0x4C: ("callproplex",     "u30u30"),
    0x4E: ("callsupervoid",   "u30u30"),
    0x53: ("applytype",       "u30"),
    0x55: ("newobject",       "u30"),
    0x57: ("newactivation",   ""),
    0x59: ("getdescendants",  "u30"),
    0x5A: ("newcatch",        "u30"),
    0x5E: ("findproperty",    "u30"),
    0x64: ("getglobalscope",  ""),
    0x6A: ("deleteproperty",  "u30"),
    0x6C: ("getslot",         "u30"),
    0x6D: ("setslot",         "u30"),
    0x6E: ("getglobalslot",   "u30"),
    0x6F: ("setglobalslot",   "u30"),
    0x70: ("convert_s",       ""),
    0x71: ("esc_xelem",       ""),
    0x72: ("esc_xattr",       ""),
    0x73: ("convert_i",       ""),
    0x74: ("convert_u",       ""),
    0x75: ("convert_d",       ""),
    0x76: ("convert_b",       ""),
    0x77: ("convert_o",       ""),
    0x78: ("checkfilter",     ""),
    0x80: ("coerce",          "u30"),
    0x81: ("coerce_b",        ""),
    0x83: ("coerce_i",        ""),
    0x84: ("coerce_d",        ""),
    0x86: ("astype",          "u30"),
    0x87: ("astypelate",      ""),
    0x88: ("coerce_u",        ""),
    0x89: ("coerce_o",        ""),
    0x90: ("negate",          ""),
    0x92: ("inclocal",        "u30"),
    0x94: ("declocal",        "u30"),
    0x96: ("not",             ""),
    0x97: ("bitnot",          ""),
    0x9A: ("concat",          ""),
    0x9B: ("add_d",           ""),
    0xA0: ("add",             ""),
    0xA5: ("lshift",          ""),
    0xA6: ("rshift",          ""),
    0xA7: ("urshift",         ""),
    0xA8: ("bitand",          ""),
    0xA9: ("bitor",           ""),
    0xAA: ("bitxor",          ""),
    0xB1: ("instanceof",      ""),
    0xB2: ("istype",          "u30"),
    0xB3: ("istypelate",      ""),
    0xB4: ("in",              ""),
    0xC0: ("increment_i",     ""),
    0xC1: ("decrement_i",     ""),
    0xC2: ("inclocal_i",      "u30"),
    0xC3: ("declocal_i",      "u30"),
    0xC4: ("negate_i",        ""),
    0xC5: ("add_i",           ""),
    0xC6: ("subtract_i",      ""),
    0xC7: ("multiply_i",      ""),
    0xF0: ("debugline",       "u30"),
    0xF1: ("debugfile",       "u30"),
}


def _read_s24(data: bytes, offset: int) -> tuple[int, int]:
    """Read a signed 24-bit integer (little-endian)."""
    val = data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16)
    if val & 0x800000:
        val -= 0x1000000
    return val, offset + 3


def _build_lookup() -> dict[int, tuple[str, str]]:
    """Build the combined opcode lookup table."""
    lookup = dict(_EXTRA_OPCODES)
    lookup.update(_OPCODE_TABLE)  # primary table takes precedence
    return lookup

_LOOKUP = _build_lookup()


def decode_instructions(code: bytes,
                        strict: bool = False) -> list[Instruction]:
    """Decode an AVM2 bytecode stream into a list of instructions.

    Args:
        code: Raw bytecode bytes (from MethodBodyInfo.code).
        strict: If True, raise ``ABCParseError`` on any decode problem
                (unknown opcodes, truncated operands). If False (default),
                log warnings and emit partial instructions.

    Returns:
        List of decoded Instruction objects.

    Raises:
        ABCParseError: Only when ``strict=True`` and a problem is found.
    """
    instructions: list[Instruction] = []
    off = 0
    code_len = len(code)

    while off < code_len:
        start = off
        op = code[off]
        off += 1

        entry = _LOOKUP.get(op)
        if entry is None:
            msg = f"Unknown opcode 0x{op:02X} at offset 0x{start:04X}"
            if strict:
                raise ABCParseError(msg)
            log.warning(msg)
            instructions.append(Instruction(
                offset=start, opcode=op, mnemonic=f"unknown_0x{op:02X}",
                operands=[], size=1))
            continue

        mnemonic, fmt = entry
        operands: list[int] = []

        try:
            if fmt == "":
                pass
            elif fmt == "u8":
                val, off = read_u8(code, off)
                operands.append(val)
            elif fmt == "u30":
                val, off = read_u30(code, off)
                operands.append(val)
            elif fmt == "u30u30":
                val1, off = read_u30(code, off)
                val2, off = read_u30(code, off)
                operands.extend([val1, val2])
            elif fmt == "s24":
                val, off = _read_s24(code, off)
                operands.append(val)
            elif fmt == "special":
                if op == OP_lookupswitch:
                    default_off, off = _read_s24(code, off)
                    case_count, off = read_u30(code, off)
                    operands.append(default_off)
                    operands.append(case_count)
                    for _ in range(case_count + 1):
                        case_off, off = _read_s24(code, off)
                        operands.append(case_off)
                elif op == OP_debug:
                    debug_type, off = read_u8(code, off)
                    index, off = read_u30(code, off)
                    reg, off = read_u8(code, off)
                    extra, off = read_u30(code, off)
                    operands.extend([debug_type, index, reg, extra])
        except (IndexError, ValueError) as e:
            msg = (f"Truncated operand for {mnemonic} at offset "
                   f"0x{start:04X}: {e}")
            if strict:
                raise ABCParseError(msg) from e
            log.warning(msg)
            # Emit what we have so far and stop decoding
            instructions.append(Instruction(
                offset=start, opcode=op, mnemonic=mnemonic,
                operands=operands, size=off - start))
            break

        instructions.append(Instruction(
            offset=start, opcode=op, mnemonic=mnemonic,
            operands=operands, size=off - start))

    return instructions
