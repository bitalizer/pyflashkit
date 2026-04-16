"""
Decompiler utility helpers — stack manipulation, expression formatting,
string escaping, bytecode skipping, namespace inspection.

These helpers are pure (no decompiler state) and are used by both the
stack simulator and the class decompiler.
"""

from __future__ import annotations

import struct

from ..abc.parser import read_u30
from ..abc.constants import (
    CONSTANT_PRIVATE_NS,
    CONSTANT_PROTECTED_NAMESPACE,
    CONSTANT_STATIC_PROTECTED_NS,
    CONSTANT_PACKAGE_INTERNAL_NS,
)
from ..abc.opcodes import (
    OP_PUSHBYTE, OP_PUSHSHORT, OP_PUSHSTRING, OP_PUSHINT, OP_PUSHUINT,
    OP_PUSHDOUBLE, OP_PUSHNAMESPACE,
    OP_GETSUPER, OP_SETSUPER, OP_DXNS, OP_KILL,
    OP_NEWFUNCTION, OP_NEWCLASS, OP_NEWCATCH,
    OP_FINDPROPSTRICT, OP_FINDPROPERTY, OP_FINDDEF, OP_GETLEX,
    OP_SETPROPERTY, OP_GETLOCAL, OP_SETLOCAL,
    OP_GETSCOPEOBJECT, OP_GETPROPERTY, OP_INITPROPERTY,
    OP_DELETEPROPERTY, OP_GETSLOT, OP_SETSLOT,
    OP_GETGLOBALSLOT, OP_SETGLOBALSLOT,
    OP_COERCE, OP_ASTYPE, OP_ISTYPE,
    OP_INCLOCAL, OP_DECLOCAL, OP_INCLOCAL_I, OP_DECLOCAL_I,
    OP_GETDESCENDANTS,
    OP_DEBUGLINE, OP_DEBUGFILE, OP_DEBUG,
    OP_CALL, OP_CONSTRUCT, OP_APPLYTYPE,
    OP_NEWOBJECT, OP_NEWARRAY, OP_CONSTRUCTSUPER,
    OP_CALLMETHOD, OP_CALLSTATIC, OP_CALLSUPER,
    OP_CALLPROPERTY, OP_CONSTRUCTPROP, OP_CALLPROPLEX,
    OP_CALLSUPERVOID, OP_CALLPROPVOID,
    OP_HASNEXT2,
)


# ── Indentation ─────────────────────────────────────────────────────────────

INDENT_UNIT = "    "
"""Indent unit used throughout AS3 output. 4 spaces by default."""


# ── Stack helpers ───────────────────────────────────────────────────────────

def pop_n(
    stack: list[str],
    n: int,
    error_log: list[str] | None = None,
    pos: str = "",
) -> list[str]:
    """Pop ``n`` items from ``stack`` in argument order (reversed from pop order).

    On stack underflow pushes ``"?"`` placeholders rather than raising, so
    malformed methods still produce partial output. Logs a message to
    ``error_log`` if provided.
    """
    args: list[str] = []
    for _ in range(n):
        if stack:
            args.append(stack.pop())
        else:
            args.append("?")
            if error_log is not None:
                msg = f"Stack underflow (expected {n} items)"
                if pos:
                    msg = f"{msg} at {pos}"
                error_log.append(msg)
    args.reverse()
    return args


# ── Numeric/string formatting ───────────────────────────────────────────────

def fmt_hex(v: int) -> str:
    """Format ``v`` as ``0xNN`` with byte-aligned (even digit count) padding."""
    h = f"{v:X}"
    if len(h) % 2:
        h = "0" + h
    return f"0x{h}"


def fmt_hex_const(v: int) -> str:
    """Format ``v`` as ``0xNNNN`` for constant declarations (min 4 digits)."""
    h = f"{v:X}"
    if len(h) < 4:
        h = h.zfill(4)
    return f"0x{h}"


def to_hex_if_int(s: str) -> str:
    """If ``s`` is a non-negative decimal int literal, return its hex form.

    Otherwise returns ``s`` unchanged. Used by bitwise operator formatting.
    """
    try:
        v = int(s)
        if v >= 0:
            return fmt_hex(v)
    except (ValueError, OverflowError):
        pass
    return s


def escape_str(s: str) -> str:
    """Escape special characters for an AS3 string literal.

    Handles backslash, double-quote, newline, carriage return, tab, NUL,
    form-feed, Unicode line separators (U+2028/2029), and any other
    control character (< 0x20 or 0x7F).
    """
    out: list[str] = []
    for ch in s:
        cp = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif cp == 0:
            out.append("\\0")
        elif ch == "\f":
            out.append("\\f")
        elif cp == 0x2028:
            out.append("\\u2028")
        elif cp == 0x2029:
            out.append("\\u2029")
        elif cp < 0x20 or cp == 0x7F:
            out.append(f"\\x{cp:02X}")
        else:
            out.append(ch)
    return "".join(out)


# ── Expression formatting ───────────────────────────────────────────────────

def fmt_call(obj: str, name: str, args: list[str]) -> str:
    """Format a method call. Omits the receiver when it's implicit/global."""
    joined = ", ".join(args)
    if obj in ("", "global") or obj == name:
        return f"{name}({joined})"
    return f"{obj}.{name}({joined})"


def binop(stack: list[str], op: str) -> None:
    """Apply a binary operator in place on ``stack``.

    Wraps the result in parens to avoid precedence ambiguity; the
    formatter can strip redundant parens at the end.
    """
    b = stack.pop() if stack else "?"
    a = stack.pop() if stack else "?"
    stack.append(f"({a} {op} {b})")


def bitwise_binop(stack: list[str], op: str) -> None:
    """Like :func:`binop` but formats integer-literal operands as hex."""
    b = stack.pop() if stack else "?"
    a = stack.pop() if stack else "?"
    stack.append(f"({to_hex_if_int(a)} {op} {to_hex_if_int(b)})")


# ── Type inference / cast handling ──────────────────────────────────────────

_IMPLICIT_DEFAULTS = {
    "int": "0",
    "uint": "0",
    "Boolean": "false",
}
_PRIMITIVE_TYPES = frozenset({"*", "int", "uint", "Number", "Boolean", "String"})


def is_type_default(ltype: str, value: str) -> bool:
    """Return True if ``value`` is the implicit default for type ``ltype``.

    Used to suppress redundant ``var x:int = 0;`` style initializers.
    """
    default = _IMPLICIT_DEFAULTS.get(ltype)
    if default is not None:
        return value == default
    if ltype not in _PRIMITIVE_TYPES and value == "null":
        return True
    return False


def strip_redundant_cast(ltype: str, value: str) -> str:
    """Strip ``int(...)``/``uint(...)`` when the target is already that type.

    Leaves ``String(...)``, ``Number(...)``, ``Boolean(...)`` alone since
    those casts often carry explicit semantic intent in AS3.
    """
    prefix = {"int": "int(", "uint": "uint("}.get(ltype)
    if not prefix:
        return value
    if not (value.startswith(prefix) and value.endswith(")")):
        return value
    inner = value[len(prefix):-1]
    # Verify the outer parens actually close at the end (not earlier).
    depth = 0
    for ch in inner:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth < 0:
            return value
    return inner if depth == 0 else value


def add_type_cast_if_needed(
    ltype: str,
    value: str,
    local_types: dict[int, str],
    local_names: dict[int, str],
) -> str:
    """Insert an explicit cast when assigned type clearly mismatches ltype.

    Conservative: only wraps in obvious cases to avoid over-casting.

    - ``String var = <numeric var>`` → ``String(...)``
    - ``Number var = <string literal or String var>`` → ``Number(...)``
    - ``Boolean var = <numeric literal>`` → ``Boolean(...)``
    """
    v = value.strip()

    def _type_of_named_var() -> str | None:
        for reg, nm in local_names.items():
            if v == nm:
                return local_types.get(reg)
        return None

    if ltype == "String" and not v.startswith(("String(", '"')):
        t = _type_of_named_var()
        if t in ("Number", "int", "uint"):
            return f"String({value})"
    elif ltype == "Number" and not v.startswith("Number("):
        if v.startswith(('"', "'")):
            return f"Number({value})"
        if _type_of_named_var() == "String":
            return f"Number({value})"
    elif ltype == "Boolean" and not v.startswith("Boolean("):
        if v.lstrip("-").isdigit() and v not in ("true", "false"):
            return f"Boolean({value})"

    return value


# ── Parenthesis / precedence awareness ──────────────────────────────────────

def has_outer_parens(expr: str) -> bool:
    """Return True if ``expr`` is wrapped in matching outer parens."""
    if not (expr.startswith("(") and expr.endswith(")")):
        return False
    depth = 0
    for i, ch in enumerate(expr):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth == 0 and i < len(expr) - 1:
            return False  # First '(' closed before end.
    return True


def needs_ternary_wrap(expr: str) -> bool:
    """Return True if a ternary branch expression needs parens to disambiguate."""
    if has_outer_parens(expr):
        return False
    depth = 0
    in_str = False
    for i, ch in enumerate(expr):
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth == 0 and ch == " ":
            rest = expr[i + 1:]
            for op in ("+", "-", "*", "/", "%", "&&", "||",
                       "==", "!=", "===", "!==",
                       "<", ">", "<=", ">=",
                       "&", "|", "^", "<<", ">>", ">>>"):
                if rest.startswith(op + " ") or rest.startswith(op + "("):
                    return True
    return False


def find_op_outside_parens(expr: str, op: str) -> int:
    """Find the first occurrence of ``op`` at paren depth 0, not inside a string.

    Returns -1 when not found. Handles multi-char operators correctly:
    ``==`` is not matched as part of ``===``, ``<`` not part of ``<<`` etc.
    """
    depth = 0
    i = 0
    oplen = len(op)
    while i <= len(expr) - oplen:
        ch = expr[i]
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth -= 1
            i += 1
            continue
        if ch == '"':
            i += 1
            while i < len(expr) and expr[i] != '"':
                if expr[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        if ch == "'":
            i += 1
            while i < len(expr) and expr[i] != "'":
                if expr[i] == "\\":
                    i += 1
                i += 1
            i += 1
            continue
        if depth == 0 and expr[i:i + oplen] == op:
            # Reject partial matches of longer operators.
            if op in ("==", "!=") and i + oplen < len(expr) and expr[i + oplen] == "=":
                i += 1
                continue
            if op in ("<", ">") and i + oplen < len(expr) and expr[i + oplen] in ("=", "<", ">"):
                i += 1
                continue
            if op == "=" and i > 0 and expr[i - 1] in ("!", "<", ">", "="):
                i += 1
                continue
            return i
        i += 1
    return -1


def wrap_for_logical(expr: str, join_op: str) -> str:
    """Wrap ``expr`` in parens iff it mixes a different logical operator.

    ``(a == b)`` doesn't need wrapping under ``||`` (== binds tighter).
    ``(a && b)`` does need wrapping under ``||``.
    """
    if has_outer_parens(expr):
        return expr
    other_op = "||" if join_op == "&&" else "&&"
    depth = 0
    i = 0
    while i < len(expr) - 1:
        ch = expr[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == '"':
            i += 1
            while i < len(expr) and expr[i] != '"':
                if expr[i] == "\\":
                    i += 1
                i += 1
        elif depth == 0 and expr[i:i + 2] == other_op:
            return f"({expr})"
        i += 1
    return expr


# ── Multi-line statement expansion ──────────────────────────────────────────

def expand_multiline_stmt(stmt: str, base_indent: str) -> list[str]:
    """Split a statement containing object-literal newlines into indented lines.

    Object literals use bare ``\\n`` as separators internally; this function
    adds the right indent on each line, increasing one level per ``{`` and
    returning to the outer level on ``}``.
    """
    if "\n" not in stmt:
        return [f"{base_indent}{stmt}"]

    result: list[str] = []
    leading = len(stmt) - len(stmt.lstrip(" "))
    actual_indent = len(base_indent) + leading
    indent_stack = [actual_indent]
    cur_line = base_indent
    indent_width = len(INDENT_UNIT)

    i = 0
    while i < len(stmt):
        ch = stmt[i]
        if ch == "\n":
            result.append(cur_line)
            # Look ahead: if next non-space is '}', use the outer indent.
            j = i + 1
            while j < len(stmt) and stmt[j] == " ":
                j += 1
            if j < len(stmt) and stmt[j] == "}":
                outer = indent_stack[-2] if len(indent_stack) > 1 else indent_stack[-1]
                cur_line = " " * outer
            else:
                cur_line = " " * indent_stack[-1]
        elif ch == "{":
            cur_line += ch
            indent_stack.append(indent_stack[-1] + indent_width)
        elif ch == "}":
            if len(indent_stack) > 1:
                indent_stack.pop()
            cur_line += ch
        else:
            cur_line += ch
        i += 1

    if cur_line.strip():
        result.append(cur_line)
    return result


# ── Namespace / access modifier helpers ─────────────────────────────────────

def access_modifier(ns_kind: int) -> str:
    """Map an AVM2 namespace kind byte to its AS3 access modifier keyword."""
    if ns_kind == CONSTANT_PRIVATE_NS:
        return "private"
    if ns_kind in (CONSTANT_PROTECTED_NAMESPACE, CONSTANT_STATIC_PROTECTED_NS):
        return "protected"
    if ns_kind == CONSTANT_PACKAGE_INTERNAL_NS:
        return "internal"
    return "public"


def typename_param_indices(data: bytes, count: int) -> list[int]:
    """Decode the packed u30 parameter indices of a TypeName multiname.

    TypeName entries store parameter multiname indices as concatenated u30
    bytes in ``MultinameInfo.data``. This helper iterates them safely.
    """
    params: list[int] = []
    off = 0
    for _ in range(count):
        if off >= len(data):
            break
        idx, off = read_u30(data, off)
        params.append(idx)
    return params


# ── Bytecode operand skipping ───────────────────────────────────────────────
# Used by analysis passes that need to iterate instructions without fully
# decoding them. If the bytecode is malformed the return equals ``len(code)``
# (graceful degradation — caller's loop terminates).

_OPS_ONE_U30 = frozenset({
    OP_PUSHSHORT, OP_PUSHSTRING, OP_PUSHINT, OP_PUSHUINT,
    OP_PUSHDOUBLE, OP_PUSHNAMESPACE,
    OP_GETSUPER, OP_SETSUPER, OP_DXNS, OP_KILL,
    OP_NEWFUNCTION, OP_NEWCLASS, OP_NEWCATCH,
    OP_FINDPROPSTRICT, OP_FINDPROPERTY, OP_FINDDEF, OP_GETLEX,
    OP_SETPROPERTY, OP_GETLOCAL, OP_SETLOCAL,
    OP_GETSCOPEOBJECT, OP_GETPROPERTY, OP_INITPROPERTY,
    OP_DELETEPROPERTY, OP_GETSLOT, OP_SETSLOT,
    OP_GETGLOBALSLOT, OP_SETGLOBALSLOT,
    OP_COERCE, OP_ASTYPE, OP_ISTYPE,
    OP_INCLOCAL, OP_DECLOCAL, OP_INCLOCAL_I, OP_DECLOCAL_I,
    OP_GETDESCENDANTS,
    OP_DEBUGLINE, OP_DEBUGFILE,
    OP_CALL, OP_CONSTRUCT, OP_APPLYTYPE,
    OP_NEWOBJECT, OP_NEWARRAY, OP_CONSTRUCTSUPER,
})

_OPS_TWO_U30 = frozenset({
    OP_CALLMETHOD, OP_CALLSTATIC, OP_CALLSUPER,
    OP_CALLPROPERTY, OP_CONSTRUCTPROP, OP_CALLPROPLEX,
    OP_CALLSUPERVOID, OP_CALLPROPVOID,
    OP_HASNEXT2,
})


def skip_operands(op: int, code: bytes, p: int) -> int:
    """Advance past an instruction's operands, returning the new offset.

    ``p`` is the offset *after* the opcode byte. Returns ``len(code)`` on
    malformed bytecode so the caller's iteration loop terminates safely.
    """
    try:
        if op == OP_PUSHBYTE:
            return p + 1
        if op in _OPS_ONE_U30:
            _, p = read_u30(code, p)
            return p
        if op in _OPS_TWO_U30:
            _, p = read_u30(code, p)
            _, p = read_u30(code, p)
            return p
        if op == OP_DEBUG:
            p += 1                    # debug_type u8
            _, p = read_u30(code, p)  # name string idx
            p += 1                    # register u8
            _, p = read_u30(code, p)  # extra u30
            return p
        return p
    except (IndexError, struct.error, ValueError):
        return len(code)
