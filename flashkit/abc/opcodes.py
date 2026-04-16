"""
AVM2 opcode constants and operand-format table.

Defines all 161 AVM2 instruction opcodes plus the ``_OPCODE_TABLE`` that
maps each opcode to ``(mnemonic, operand_format)``. This is the single
source of truth for the disassembler, assembler, and decompiler.

Operand format codes:
    ""       no operands
    "u8"     one unsigned byte
    "u30"    one variable-length u30
    "u30u30" two u30s (e.g. callproperty: mn_idx, arg_count)
    "s24"    one signed 24-bit branch offset
    "special" handled individually (lookupswitch, debug)

Reference: Adobe AVM2 Overview, Chapter 5 (AVM2 instructions).
"""

# ── All 161 AVM2 opcodes ────────────────────────────────────────────────────
# Grouped by functional area. Uppercase naming matches AVM2 spec conventions.

# Control flow
OP_BKPT            = 0x01
OP_NOP             = 0x02
OP_THROW           = 0x03
OP_LABEL           = 0x09
OP_IFNLT           = 0x0C
OP_IFNLE           = 0x0D
OP_IFNGT           = 0x0E
OP_IFNGE           = 0x0F
OP_JUMP            = 0x10
OP_IFTRUE          = 0x11
OP_IFFALSE         = 0x12
OP_IFEQ            = 0x13
OP_IFNE            = 0x14
OP_IFLT            = 0x15
OP_IFLE            = 0x16
OP_IFGT            = 0x17
OP_IFGE            = 0x18
OP_IFSTRICTEQ      = 0x19
OP_IFSTRICTNE      = 0x1A
OP_LOOKUPSWITCH    = 0x1B

# Super-class access
OP_GETSUPER        = 0x04
OP_SETSUPER        = 0x05

# Default XML namespace
OP_DXNS            = 0x06
OP_DXNSLATE        = 0x07

# Local register kill
OP_KILL            = 0x08

# Scope management
OP_PUSHWITH        = 0x1C
OP_POPSCOPE        = 0x1D
OP_PUSHSCOPE       = 0x30
OP_GETSCOPEOBJECT  = 0x65
OP_GETGLOBALSCOPE  = 0x64

# Stack operations
OP_POP             = 0x29
OP_DUP             = 0x2A
OP_SWAP            = 0x2B

# Push constants
OP_PUSHNULL        = 0x20
OP_PUSHUNDEFINED   = 0x21
OP_PUSHTRUE        = 0x26
OP_PUSHFALSE       = 0x27
OP_PUSHNAN         = 0x28
OP_PUSHBYTE        = 0x24
OP_PUSHSHORT       = 0x25
OP_PUSHSTRING      = 0x2C
OP_PUSHINT         = 0x2D
OP_PUSHUINT        = 0x2E
OP_PUSHDOUBLE      = 0x2F
OP_PUSHNAMESPACE   = 0x31

# Iteration
OP_NEXTNAME        = 0x1E
OP_HASNEXT         = 0x1F
OP_NEXTVALUE       = 0x23
OP_HASNEXT2        = 0x32

# Alchemy / fast memory
OP_LI8             = 0x35
OP_LI16            = 0x36
OP_LI32            = 0x37
OP_LF32            = 0x38
OP_LF64            = 0x39
OP_SI8             = 0x3A
OP_SI16            = 0x3B
OP_SI32            = 0x3C
OP_SF32            = 0x3D
OP_SF64            = 0x3E

# Calls / construction
OP_NEWFUNCTION     = 0x40
OP_CALL            = 0x41
OP_CONSTRUCT       = 0x42
OP_CALLMETHOD      = 0x43
OP_CALLSTATIC      = 0x44
OP_CALLSUPER       = 0x45
OP_CALLPROPERTY    = 0x46
OP_RETURNVOID      = 0x47
OP_RETURNVALUE     = 0x48
OP_CONSTRUCTSUPER  = 0x49
OP_CONSTRUCTPROP   = 0x4A
OP_CALLPROPLEX     = 0x4C
OP_CALLSUPERVOID   = 0x4E
OP_CALLPROPVOID    = 0x4F

# Sign extension
OP_SXI1            = 0x50
OP_SXI8            = 0x51
OP_SXI16           = 0x52

# Object creation
OP_APPLYTYPE       = 0x53
OP_NEWOBJECT       = 0x55
OP_NEWARRAY        = 0x56
OP_NEWACTIVATION   = 0x57
OP_NEWCLASS        = 0x58
OP_GETDESCENDANTS  = 0x59
OP_NEWCATCH        = 0x5A

# Property lookup
OP_FINDPROPSTRICT  = 0x5D
OP_FINDPROPERTY    = 0x5E
OP_FINDDEF         = 0x5F
OP_GETLEX          = 0x60
OP_SETPROPERTY     = 0x61
OP_GETPROPERTY     = 0x66
OP_INITPROPERTY    = 0x68
OP_DELETEPROPERTY  = 0x6A

# Slots (numeric property access)
OP_GETSLOT         = 0x6C
OP_SETSLOT         = 0x6D
OP_GETGLOBALSLOT   = 0x6E
OP_SETGLOBALSLOT   = 0x6F

# Locals
OP_GETLOCAL        = 0x62
OP_SETLOCAL        = 0x63
OP_GETLOCAL_0      = 0xD0
OP_GETLOCAL_1      = 0xD1
OP_GETLOCAL_2      = 0xD2
OP_GETLOCAL_3      = 0xD3
OP_SETLOCAL_0      = 0xD4
OP_SETLOCAL_1      = 0xD5
OP_SETLOCAL_2      = 0xD6
OP_SETLOCAL_3      = 0xD7

# Type conversion / coercion
OP_CONVERT_S       = 0x70
OP_ESC_XELEM       = 0x71
OP_ESC_XATTR       = 0x72
OP_CONVERT_I       = 0x73
OP_CONVERT_U       = 0x74
OP_CONVERT_D       = 0x75
OP_CONVERT_B       = 0x76
OP_CONVERT_O       = 0x77
OP_CHECKFILTER     = 0x78
OP_COERCE          = 0x80
OP_COERCE_B        = 0x81
OP_COERCE_A        = 0x82
OP_COERCE_I        = 0x83
OP_COERCE_D        = 0x84
OP_COERCE_S        = 0x85
OP_ASTYPE          = 0x86
OP_ASTYPELATE      = 0x87
OP_COERCE_U        = 0x88
OP_COERCE_O        = 0x89

# Unary arithmetic / logic
OP_NEGATE          = 0x90
OP_INCREMENT       = 0x91
OP_INCLOCAL        = 0x92
OP_DECREMENT       = 0x93
OP_DECLOCAL        = 0x94
OP_TYPEOF          = 0x95
OP_NOT             = 0x96
OP_BITNOT          = 0x97

# Binary arithmetic
OP_ADD             = 0xA0
OP_SUBTRACT        = 0xA1
OP_MULTIPLY        = 0xA2
OP_DIVIDE          = 0xA3
OP_MODULO          = 0xA4

# Bitwise
OP_LSHIFT          = 0xA5
OP_RSHIFT          = 0xA6
OP_URSHIFT         = 0xA7
OP_BITAND          = 0xA8
OP_BITOR           = 0xA9
OP_BITXOR          = 0xAA

# Comparison
OP_EQUALS          = 0xAB
OP_STRICTEQUALS    = 0xAC
OP_LESSTHAN        = 0xAD
OP_LESSEQUALS      = 0xAE
OP_GREATERTHAN     = 0xAF
OP_GREATEREQUALS   = 0xB0
OP_INSTANCEOF      = 0xB1
OP_ISTYPE          = 0xB2
OP_ISTYPELATE      = 0xB3
OP_IN              = 0xB4

# Integer arithmetic (int-typed)
OP_INCREMENT_I     = 0xC0
OP_DECREMENT_I     = 0xC1
OP_INCLOCAL_I      = 0xC2
OP_DECLOCAL_I      = 0xC3
OP_NEGATE_I        = 0xC4
OP_ADD_I           = 0xC5
OP_SUBTRACT_I      = 0xC6
OP_MULTIPLY_I      = 0xC7

# Debugging
OP_DEBUG           = 0xEF
OP_DEBUGLINE       = 0xF0
OP_DEBUGFILE       = 0xF1


# ── Opcode table ────────────────────────────────────────────────────────────
# Maps opcode byte -> (mnemonic, operand_format).
# Single source of truth for disassembly, assembly, and skip-table generation.

OPCODE_TABLE: dict[int, tuple[str, str]] = {
    # Control flow
    OP_BKPT:            ("bkpt",            ""),
    OP_NOP:             ("nop",             ""),
    OP_THROW:           ("throw",           ""),
    OP_LABEL:           ("label",           ""),
    OP_IFNLT:           ("ifnlt",           "s24"),
    OP_IFNLE:           ("ifnle",           "s24"),
    OP_IFNGT:           ("ifngt",           "s24"),
    OP_IFNGE:           ("ifnge",           "s24"),
    OP_JUMP:            ("jump",            "s24"),
    OP_IFTRUE:          ("iftrue",          "s24"),
    OP_IFFALSE:         ("iffalse",         "s24"),
    OP_IFEQ:            ("ifeq",            "s24"),
    OP_IFNE:            ("ifne",            "s24"),
    OP_IFLT:            ("iflt",            "s24"),
    OP_IFLE:            ("ifle",            "s24"),
    OP_IFGT:            ("ifgt",            "s24"),
    OP_IFGE:            ("ifge",            "s24"),
    OP_IFSTRICTEQ:      ("ifstricteq",      "s24"),
    OP_IFSTRICTNE:      ("ifstrictne",      "s24"),
    OP_LOOKUPSWITCH:    ("lookupswitch",    "special"),

    # Super access
    OP_GETSUPER:        ("getsuper",        "u30"),
    OP_SETSUPER:        ("setsuper",        "u30"),

    # Default XML namespace
    OP_DXNS:            ("dxns",            "u30"),
    OP_DXNSLATE:        ("dxnslate",        ""),

    # Register kill
    OP_KILL:            ("kill",            "u30"),

    # Scope
    OP_PUSHWITH:        ("pushwith",        ""),
    OP_POPSCOPE:        ("popscope",        ""),
    OP_PUSHSCOPE:       ("pushscope",       ""),
    OP_GETSCOPEOBJECT:  ("getscopeobject",  "u8"),
    OP_GETGLOBALSCOPE:  ("getglobalscope",  ""),

    # Stack
    OP_POP:             ("pop",             ""),
    OP_DUP:             ("dup",             ""),
    OP_SWAP:            ("swap",            ""),

    # Push constants
    OP_PUSHNULL:        ("pushnull",        ""),
    OP_PUSHUNDEFINED:   ("pushundefined",   ""),
    OP_PUSHTRUE:        ("pushtrue",        ""),
    OP_PUSHFALSE:       ("pushfalse",       ""),
    OP_PUSHNAN:         ("pushnan",         ""),
    OP_PUSHBYTE:        ("pushbyte",        "u8"),
    OP_PUSHSHORT:       ("pushshort",       "u30"),
    OP_PUSHSTRING:      ("pushstring",      "u30"),
    OP_PUSHINT:         ("pushint",         "u30"),
    OP_PUSHUINT:        ("pushuint",        "u30"),
    OP_PUSHDOUBLE:      ("pushdouble",      "u30"),
    OP_PUSHNAMESPACE:   ("pushnamespace",   "u30"),

    # Iteration
    OP_NEXTNAME:        ("nextname",        ""),
    OP_HASNEXT:         ("hasnext",         ""),
    OP_NEXTVALUE:       ("nextvalue",       ""),
    OP_HASNEXT2:        ("hasnext2",        "u30u30"),

    # Alchemy
    OP_LI8:             ("li8",             ""),
    OP_LI16:            ("li16",            ""),
    OP_LI32:            ("li32",            ""),
    OP_LF32:            ("lf32",            ""),
    OP_LF64:            ("lf64",            ""),
    OP_SI8:             ("si8",             ""),
    OP_SI16:            ("si16",            ""),
    OP_SI32:            ("si32",            ""),
    OP_SF32:            ("sf32",            ""),
    OP_SF64:            ("sf64",            ""),

    # Calls
    OP_NEWFUNCTION:     ("newfunction",     "u30"),
    OP_CALL:            ("call",            "u30"),
    OP_CONSTRUCT:       ("construct",       "u30"),
    OP_CALLMETHOD:      ("callmethod",      "u30u30"),
    OP_CALLSTATIC:      ("callstatic",      "u30u30"),
    OP_CALLSUPER:       ("callsuper",       "u30u30"),
    OP_CALLPROPERTY:    ("callproperty",    "u30u30"),
    OP_RETURNVOID:      ("returnvoid",      ""),
    OP_RETURNVALUE:     ("returnvalue",     ""),
    OP_CONSTRUCTSUPER:  ("constructsuper",  "u30"),
    OP_CONSTRUCTPROP:   ("constructprop",   "u30u30"),
    OP_CALLPROPLEX:     ("callproplex",     "u30u30"),
    OP_CALLSUPERVOID:   ("callsupervoid",   "u30u30"),
    OP_CALLPROPVOID:    ("callpropvoid",    "u30u30"),

    # Sign extension
    OP_SXI1:            ("sxi1",            ""),
    OP_SXI8:            ("sxi8",            ""),
    OP_SXI16:           ("sxi16",           ""),

    # Object creation
    OP_APPLYTYPE:       ("applytype",       "u30"),
    OP_NEWOBJECT:       ("newobject",       "u30"),
    OP_NEWARRAY:        ("newarray",        "u30"),
    OP_NEWACTIVATION:   ("newactivation",   ""),
    OP_NEWCLASS:        ("newclass",        "u30"),
    OP_GETDESCENDANTS:  ("getdescendants",  "u30"),
    OP_NEWCATCH:        ("newcatch",        "u30"),

    # Property lookup
    OP_FINDPROPSTRICT:  ("findpropstrict",  "u30"),
    OP_FINDPROPERTY:    ("findproperty",    "u30"),
    OP_FINDDEF:         ("finddef",         "u30"),
    OP_GETLEX:          ("getlex",          "u30"),
    OP_SETPROPERTY:     ("setproperty",     "u30"),
    OP_GETPROPERTY:     ("getproperty",     "u30"),
    OP_INITPROPERTY:    ("initproperty",    "u30"),
    OP_DELETEPROPERTY:  ("deleteproperty",  "u30"),

    # Slots
    OP_GETSLOT:         ("getslot",         "u30"),
    OP_SETSLOT:         ("setslot",         "u30"),
    OP_GETGLOBALSLOT:   ("getglobalslot",   "u30"),
    OP_SETGLOBALSLOT:   ("setglobalslot",   "u30"),

    # Locals
    OP_GETLOCAL:        ("getlocal",        "u30"),
    OP_SETLOCAL:        ("setlocal",        "u30"),
    OP_GETLOCAL_0:      ("getlocal_0",      ""),
    OP_GETLOCAL_1:      ("getlocal_1",      ""),
    OP_GETLOCAL_2:      ("getlocal_2",      ""),
    OP_GETLOCAL_3:      ("getlocal_3",      ""),
    OP_SETLOCAL_0:      ("setlocal_0",      ""),
    OP_SETLOCAL_1:      ("setlocal_1",      ""),
    OP_SETLOCAL_2:      ("setlocal_2",      ""),
    OP_SETLOCAL_3:      ("setlocal_3",      ""),

    # Type conversion
    OP_CONVERT_S:       ("convert_s",       ""),
    OP_ESC_XELEM:       ("esc_xelem",       ""),
    OP_ESC_XATTR:       ("esc_xattr",       ""),
    OP_CONVERT_I:       ("convert_i",       ""),
    OP_CONVERT_U:       ("convert_u",       ""),
    OP_CONVERT_D:       ("convert_d",       ""),
    OP_CONVERT_B:       ("convert_b",       ""),
    OP_CONVERT_O:       ("convert_o",       ""),
    OP_CHECKFILTER:     ("checkfilter",     ""),
    OP_COERCE:          ("coerce",          "u30"),
    OP_COERCE_B:        ("coerce_b",        ""),
    OP_COERCE_A:        ("coerce_a",        ""),
    OP_COERCE_I:        ("coerce_i",        ""),
    OP_COERCE_D:        ("coerce_d",        ""),
    OP_COERCE_S:        ("coerce_s",        ""),
    OP_ASTYPE:          ("astype",          "u30"),
    OP_ASTYPELATE:      ("astypelate",      ""),
    OP_COERCE_U:        ("coerce_u",        ""),
    OP_COERCE_O:        ("coerce_o",        ""),

    # Unary arithmetic / logic
    OP_NEGATE:          ("negate",          ""),
    OP_INCREMENT:       ("increment",       ""),
    OP_INCLOCAL:        ("inclocal",        "u30"),
    OP_DECREMENT:       ("decrement",       ""),
    OP_DECLOCAL:        ("declocal",        "u30"),
    OP_TYPEOF:          ("typeof",          ""),
    OP_NOT:             ("not",             ""),
    OP_BITNOT:          ("bitnot",          ""),

    # Binary arithmetic
    OP_ADD:             ("add",             ""),
    OP_SUBTRACT:        ("subtract",        ""),
    OP_MULTIPLY:        ("multiply",        ""),
    OP_DIVIDE:          ("divide",          ""),
    OP_MODULO:          ("modulo",          ""),

    # Bitwise
    OP_LSHIFT:          ("lshift",          ""),
    OP_RSHIFT:          ("rshift",          ""),
    OP_URSHIFT:         ("urshift",         ""),
    OP_BITAND:          ("bitand",          ""),
    OP_BITOR:           ("bitor",           ""),
    OP_BITXOR:          ("bitxor",          ""),

    # Comparison
    OP_EQUALS:          ("equals",          ""),
    OP_STRICTEQUALS:    ("strictequals",    ""),
    OP_LESSTHAN:        ("lessthan",        ""),
    OP_LESSEQUALS:      ("lessequals",      ""),
    OP_GREATERTHAN:     ("greaterthan",     ""),
    OP_GREATEREQUALS:   ("greaterequals",   ""),
    OP_INSTANCEOF:      ("instanceof",      ""),
    OP_ISTYPE:          ("istype",          "u30"),
    OP_ISTYPELATE:      ("istypelate",      ""),
    OP_IN:              ("in",              ""),

    # Integer arithmetic
    OP_INCREMENT_I:     ("increment_i",     ""),
    OP_DECREMENT_I:     ("decrement_i",     ""),
    OP_INCLOCAL_I:      ("inclocal_i",      "u30"),
    OP_DECLOCAL_I:      ("declocal_i",      "u30"),
    OP_NEGATE_I:        ("negate_i",        ""),
    OP_ADD_I:           ("add_i",           ""),
    OP_SUBTRACT_I:      ("subtract_i",      ""),
    OP_MULTIPLY_I:      ("multiply_i",      ""),

    # Debugging
    OP_DEBUG:           ("debug",           "special"),
    OP_DEBUGLINE:       ("debugline",       "u30"),
    OP_DEBUGFILE:       ("debugfile",       "u30"),
}


# ── Reverse lookup: mnemonic -> opcode byte ────────────────────────────────
# Useful for assemblers that accept symbolic instruction names.
MNEMONIC_TO_OPCODE: dict[str, int] = {
    mnemonic: op for op, (mnemonic, _) in OPCODE_TABLE.items()
}


# ── Increment/decrement pattern helper ──────────────────────────────────────

_INC_OPS = frozenset({OP_INCREMENT, OP_INCREMENT_I})
_INCDEC_OPS = frozenset({OP_INCREMENT, OP_INCREMENT_I, OP_DECREMENT, OP_DECREMENT_I})


def match_local_incdec(code: bytes, p: int, reg_idx: int):
    """Detect a pre/post increment/decrement pattern after a getlocal.

    AVM2 compilers emit ``a++`` as a short sequence of ``dup + increment +
    setlocal`` (post) or ``increment + dup + setlocal`` (pre). Given the
    offset right after a ``getlocal`` for register ``reg_idx``, this helper
    tests whether the following bytes match either pattern.

    Returns:
        ``(is_pre, is_increment, new_p)`` if a pattern matches, else ``None``.
    """
    from .parser import read_u30

    if p + 2 > len(code):
        return None
    b0 = code[p]
    b1 = code[p + 1] if p + 1 < len(code) else 0xFF

    def _check_setlocal(pos: int):
        if pos >= len(code):
            return None
        op = code[pos]
        if 0 <= reg_idx <= 3 and op == OP_SETLOCAL_0 + reg_idx:
            return pos + 1
        if op == OP_SETLOCAL:
            if pos + 1 >= len(code):
                return None
            idx, new_p = read_u30(code, pos + 1)
            if idx == reg_idx:
                return new_p
        return None

    # Post: dup -> inc/dec -> setlocal_N
    if b0 == OP_DUP and b1 in _INCDEC_OPS:
        is_inc = b1 in _INC_OPS
        r = _check_setlocal(p + 2)
        if r is not None:
            return (False, is_inc, r)

    # Pre: inc/dec -> dup -> setlocal_N
    if b0 in _INCDEC_OPS and b1 == OP_DUP:
        is_inc = b0 in _INC_OPS
        r = _check_setlocal(p + 2)
        if r is not None:
            return (True, is_inc, r)
    return None


__all__ = [name for name in globals() if name.startswith("OP_")] + [
    "OPCODE_TABLE",
    "MNEMONIC_TO_OPCODE",
    "match_local_incdec",
    "_INC_OPS",
    "_INCDEC_OPS",
]
