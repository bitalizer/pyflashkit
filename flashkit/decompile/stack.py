"""Per-basic-block AVM2 stack simulator.

``BlockStackSim(abc).run(bb)`` walks the instructions of one basic
block, maintains an abstract expression stack, and returns a
``BlockSimResult`` with:

- ``statements``: AST statements produced by side-effecting opcodes
  (assignments, void-return, throw, callpropvoid, top-level setlocal).
- ``stack``: expressions still live at block exit.
- ``terminator``: one of ``"fall_through"``, ``"jump"``, ``"if"``,
  ``"switch"``, ``"return"``, ``"throw"``.
- ``branch_condition``: the expression consumed by a conditional
  branch, rewritten so "branch taken" corresponds to the condition
  being truthy (``iffalse`` is converted by negating its input).
- ``switch_targets``: for ``"switch"`` terminators, the list of target
  offsets from the ``lookupswitch`` operand.

Design notes:

- The simulator is strictly one-block. Cross-block data flow (phi,
  conditional values) is the structurer's problem, not ours.
- We never assume a non-empty stack at block entry; if a successor
  depends on a value produced in a predecessor we preserve it by
  treating the entry as empty and leaving values past block exit on
  ``result.stack``. The structurer wires these up when it fuses
  blocks.
- Unknown opcodes become a placeholder ``Identifier`` so the sim
  never crashes — we log a warning at debug level but continue. This
  matches how ffdec's own simulator handles obscure ops.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal as _Lit

from ..abc.opcodes import (
    OP_ADD, OP_ADD_I, OP_ASTYPE, OP_ASTYPELATE,
    OP_BITAND, OP_BITNOT, OP_BITOR, OP_BITXOR,
    OP_CALL, OP_CALLMETHOD, OP_CALLPROPERTY, OP_CALLPROPLEX,
    OP_CALLPROPVOID, OP_CALLSTATIC, OP_CALLSUPER, OP_CALLSUPERVOID,
    OP_COERCE, OP_COERCE_A, OP_COERCE_B, OP_COERCE_D, OP_COERCE_I,
    OP_COERCE_O, OP_COERCE_S, OP_COERCE_U,
    OP_CONSTRUCT, OP_CONSTRUCTPROP, OP_CONSTRUCTSUPER,
    OP_CONVERT_B, OP_CONVERT_D, OP_CONVERT_I, OP_CONVERT_O,
    OP_CONVERT_S, OP_CONVERT_U,
    OP_DECREMENT, OP_DECREMENT_I, OP_DIVIDE, OP_DUP,
    OP_EQUALS, OP_FINDPROPERTY, OP_FINDPROPSTRICT,
    OP_GETLEX, OP_GETLOCAL, OP_GETLOCAL_0, OP_GETLOCAL_1,
    OP_GETLOCAL_2, OP_GETLOCAL_3, OP_GETPROPERTY, OP_GETSLOT,
    OP_GETSUPER, OP_GREATEREQUALS, OP_GREATERTHAN,
    OP_IFEQ, OP_IFFALSE, OP_IFGE, OP_IFGT, OP_IFLE, OP_IFLT,
    OP_IFNE, OP_IFNGE, OP_IFNGT, OP_IFNLE, OP_IFNLT,
    OP_IFSTRICTEQ, OP_IFSTRICTNE, OP_IFTRUE,
    OP_IN, OP_INCREMENT, OP_INCREMENT_I, OP_INITPROPERTY,
    OP_INSTANCEOF, OP_ISTYPE, OP_ISTYPELATE,
    OP_JUMP, OP_KILL, OP_LESSEQUALS, OP_LESSTHAN,
    OP_LOOKUPSWITCH, OP_LSHIFT, OP_MODULO, OP_MULTIPLY,
    OP_MULTIPLY_I, OP_NEGATE, OP_NEGATE_I, OP_NEWACTIVATION,
    OP_NEWARRAY, OP_NEWCATCH, OP_NEWFUNCTION, OP_NEWOBJECT,
    OP_NEXTNAME, OP_NEXTVALUE, OP_NOT, OP_POP, OP_POPSCOPE,
    OP_PUSHBYTE, OP_PUSHDOUBLE, OP_PUSHFALSE, OP_PUSHINT,
    OP_PUSHNAN, OP_PUSHNULL, OP_PUSHSCOPE, OP_PUSHSHORT,
    OP_PUSHSTRING, OP_PUSHTRUE, OP_PUSHUINT, OP_PUSHUNDEFINED,
    OP_PUSHWITH, OP_RETURNVALUE, OP_RETURNVOID, OP_RSHIFT,
    OP_SETLOCAL, OP_SETLOCAL_0, OP_SETLOCAL_1, OP_SETLOCAL_2,
    OP_SETLOCAL_3, OP_SETPROPERTY, OP_SETSLOT, OP_STRICTEQUALS,
    OP_SUBTRACT, OP_SUBTRACT_I, OP_SWAP, OP_THROW, OP_TYPEOF,
    OP_URSHIFT,
    OP_HASNEXT, OP_HASNEXT2, OP_GETGLOBALSCOPE, OP_GETSCOPEOBJECT,
    OP_LABEL, OP_NOP, OP_DEBUG, OP_DEBUGLINE, OP_DEBUGFILE,
)
from ..abc.types import AbcFile
from ..info.member_info import resolve_multiname
from .ast.nodes import (
    ArrayLiteral, AssignExpr, BinaryOp, CastExpr, Expression,
    ExpressionStmt, Identifier, IndexAccess, IsExpr, AsExpr, InExpr,
    Literal, MemberAccess, MethodCall, NewExpr, ObjectLiteral,
    ObjectProperty, ReturnStmt, Statement, ThrowStmt, TypeofExpr,
    UnaryOp,
)

log = logging.getLogger(__name__)


TerminatorKind = _Lit[
    "fall_through", "jump", "if", "switch", "return", "throw",
]


@dataclass
class BlockSimResult:
    """Output of simulating one basic block.

    Attributes:
        statements: AST statements produced by side-effecting opcodes.
        stack: Expression trees still live at block exit.
        terminator: Which kind of branch/return ends the block.
        branch_condition: For ``"if"`` terminators, the condition the
            structurer should test to decide "branch-taken"; for other
            terminators, ``None``. The condition is always in
            "branch-taken-when-truthy" form — ``iffalse`` compiles its
            operand to ``!operand`` so downstream code doesn't have to
            care about opcode polarity.
        switch_targets: For ``"switch"`` terminators, the absolute
            bytecode offsets of (default, case_0, case_1, ...); else
            ``[]``.
    """
    statements: list[Statement] = field(default_factory=list)
    stack: list[Expression] = field(default_factory=list)
    terminator: TerminatorKind = "fall_through"
    branch_condition: Expression | None = None
    switch_targets: list[int] = field(default_factory=list)


# ── opcode groupings ──────────────────────────────────────────────────────

_BINARY_OP_TABLE: dict[int, str] = {
    OP_ADD: "+", OP_ADD_I: "+",
    OP_SUBTRACT: "-", OP_SUBTRACT_I: "-",
    OP_MULTIPLY: "*", OP_MULTIPLY_I: "*",
    OP_DIVIDE: "/", OP_MODULO: "%",
    OP_LSHIFT: "<<", OP_RSHIFT: ">>", OP_URSHIFT: ">>>",
    OP_BITAND: "&", OP_BITOR: "|", OP_BITXOR: "^",
    OP_EQUALS: "==", OP_STRICTEQUALS: "===",
    OP_LESSTHAN: "<", OP_LESSEQUALS: "<=",
    OP_GREATERTHAN: ">", OP_GREATEREQUALS: ">=",
}

_COERCE_TYPE_NAMES: dict[int, str] = {
    OP_CONVERT_I: "int", OP_COERCE_I: "int",
    OP_CONVERT_U: "uint", OP_COERCE_U: "uint",
    OP_CONVERT_D: "Number", OP_COERCE_D: "Number",
    OP_CONVERT_B: "Boolean", OP_COERCE_B: "Boolean",
    OP_CONVERT_S: "String", OP_COERCE_S: "String",
}

_CONDITIONAL_BRANCH_BUILDERS: dict[int, Any] = {
    # For branches that consume a boolean on the stack.
    OP_IFTRUE: "truthy",
    OP_IFFALSE: "falsy",
    # For compare-and-branch: consume two values, synthesise the binop.
    OP_IFEQ: "==", OP_IFNE: "!=",
    OP_IFSTRICTEQ: "===", OP_IFSTRICTNE: "!==",
    OP_IFLT: "<", OP_IFLE: "<=", OP_IFGT: ">", OP_IFGE: ">=",
    OP_IFNLT: "!<", OP_IFNLE: "!<=", OP_IFNGT: "!>", OP_IFNGE: "!>=",
}


# ── simulator ──────────────────────────────────────────────────────────────


class BlockStackSim:
    """One instance per method. Holds the ``AbcFile`` for constant-pool
    resolution plus optional per-method context for nicer local names.

    Args:
        abc: The parsed ABC file.
        param_count: Number of parameters on the method being
            simulated. Locals ``1..param_count`` are named
            ``_arg_1``..``_arg_N`` to match the AS3 parameter
            convention; locals past that range keep the generic
            ``_loc{reg}_`` naming. Defaults to ``0`` when the caller
            doesn't know (generic local names throughout).
        local0_name: Name to use for local-register-0. Defaults to
            ``"this"``. Static methods pass the class name (the class
            object lives in local-0 for static dispatch).
    """

    def __init__(self, abc: AbcFile, *,
                 param_count: int = 0,
                 local0_name: str = "this"):
        self.abc = abc
        self.param_count = param_count
        self.local0_name = local0_name

    def run(self, bb, entry_stack: list[Expression] | None = None) -> BlockSimResult:
        """Simulate one basic block.

        Args:
            bb: A ``BasicBlock`` whose ``instructions`` will be walked.
            entry_stack: Optional abstract expression stack on entry.
                When supplied, operands missing from the block's own
                pushes can be satisfied from incoming predecessors'
                exit stacks — this is what keeps cross-block
                conditionals (``iftrue`` whose operand was pushed in
                the fall-through predecessor) from falling back to
                ``Identifier("_unknown")``. ``None`` means "start
                empty"; the driver in ``method.py`` populates it from
                the forward dataflow pass.

        Returns:
            A ``BlockSimResult``.
        """
        stack: list[Expression] = list(entry_stack) if entry_stack else []
        statements: list[Statement] = []
        result = BlockSimResult(statements=statements, stack=stack)

        for instr in bb.instructions:
            if self._handle(instr, stack, statements, result):
                # Handler set a terminator; subsequent instructions in
                # the same block should not exist in well-formed code
                # but we still walk them so strange bytecode doesn't
                # lose statements.
                pass

        return result

    # ── dispatch ───────────────────────────────────────────────────────────

    def _handle(self, instr, stack, statements, result) -> bool:
        """Dispatch one instruction. Returns True if the instruction
        was a terminator (for future use; callers ignore for now)."""
        op = instr.opcode

        # Pure no-ops and debug instructions
        if op in (OP_NOP, OP_LABEL, OP_DEBUG, OP_DEBUGLINE, OP_DEBUGFILE,
                  OP_NEWACTIVATION):
            return False

        # Scope stack is opaque to the AST — track nothing.
        if op in (OP_PUSHSCOPE, OP_POPSCOPE, OP_PUSHWITH, OP_GETGLOBALSCOPE,
                  OP_GETSCOPEOBJECT):
            if op == OP_PUSHSCOPE or op == OP_PUSHWITH:
                if stack:
                    stack.pop()
            elif op == OP_GETGLOBALSCOPE:
                stack.append(Identifier("global"))
            elif op == OP_GETSCOPEOBJECT:
                stack.append(Identifier(f"_scope{instr.operands[0]}_"))
            return False

        # Push constants
        if op == OP_PUSHBYTE:
            # pushbyte reads a u8 operand and sign-extends to int
            val = instr.operands[0]
            if val >= 0x80:
                val -= 0x100
            stack.append(Literal(val))
            return False
        if op == OP_PUSHSHORT:
            stack.append(Literal(instr.operands[0]))
            return False
        if op == OP_PUSHINT:
            idx = instr.operands[0]
            if 0 < idx < len(self.abc.int_pool):
                stack.append(Literal(self.abc.int_pool[idx]))
            else:
                stack.append(Literal(0))
            return False
        if op == OP_PUSHUINT:
            idx = instr.operands[0]
            if 0 < idx < len(self.abc.uint_pool):
                stack.append(Literal(self.abc.uint_pool[idx]))
            else:
                stack.append(Literal(0))
            return False
        if op == OP_PUSHDOUBLE:
            idx = instr.operands[0]
            if 0 < idx < len(self.abc.double_pool):
                stack.append(Literal(self.abc.double_pool[idx]))
            else:
                stack.append(Literal(0.0))
            return False
        if op == OP_PUSHSTRING:
            idx = instr.operands[0]
            val = self.abc.string_pool[idx] if 0 < idx < len(self.abc.string_pool) else ""
            stack.append(Literal(val))
            return False
        if op == OP_PUSHTRUE:
            stack.append(Literal(True)); return False
        if op == OP_PUSHFALSE:
            stack.append(Literal(False)); return False
        if op == OP_PUSHNULL:
            stack.append(Literal(None)); return False
        if op == OP_PUSHUNDEFINED:
            stack.append(Identifier("undefined")); return False
        if op == OP_PUSHNAN:
            import math as _m
            stack.append(Literal(_m.nan)); return False

        # Locals
        if op == OP_GETLOCAL_0:
            stack.append(Identifier(self._local_name(0))); return False
        if op in (OP_GETLOCAL_1, OP_GETLOCAL_2, OP_GETLOCAL_3):
            reg = op - OP_GETLOCAL_0
            stack.append(Identifier(self._local_name(reg))); return False
        if op == OP_GETLOCAL:
            reg = instr.operands[0]
            stack.append(Identifier(self._local_name(reg))); return False
        if op in (OP_SETLOCAL_0, OP_SETLOCAL_1, OP_SETLOCAL_2,
                  OP_SETLOCAL_3):
            reg = op - OP_SETLOCAL_0
            self._emit_setlocal(stack, statements, reg); return False
        if op == OP_SETLOCAL:
            self._emit_setlocal(stack, statements, instr.operands[0]); return False
        if op == OP_KILL:
            return False  # kill is a hint for the verifier; no AST effect

        # Stack manipulation
        if op == OP_POP:
            if stack:
                val = stack.pop()
                # If the popped value has side effects (a call) we
                # emit an ExpressionStmt; otherwise drop silently.
                if self._has_side_effects(val):
                    statements.append(ExpressionStmt(val))
            return False
        if op == OP_DUP:
            if stack:
                stack.append(stack[-1])
            return False
        if op == OP_SWAP:
            if len(stack) >= 2:
                stack[-1], stack[-2] = stack[-2], stack[-1]
            return False

        # Binary arithmetic / comparison
        if op in _BINARY_OP_TABLE:
            if len(stack) >= 2:
                right = stack.pop()
                left = stack.pop()
                stack.append(BinaryOp(_BINARY_OP_TABLE[op], left, right))
            return False

        # Unary ops
        if op in (OP_NEGATE, OP_NEGATE_I):
            if stack:
                stack.append(UnaryOp("-", stack.pop()))
            return False
        if op == OP_NOT:
            if stack:
                stack.append(UnaryOp("!", stack.pop()))
            return False
        if op == OP_BITNOT:
            if stack:
                stack.append(UnaryOp("~", stack.pop()))
            return False
        if op in (OP_INCREMENT, OP_INCREMENT_I):
            if stack:
                stack.append(BinaryOp("+", stack.pop(), Literal(1)))
            return False
        if op in (OP_DECREMENT, OP_DECREMENT_I):
            if stack:
                stack.append(BinaryOp("-", stack.pop(), Literal(1)))
            return False
        if op == OP_TYPEOF:
            if stack:
                stack.append(TypeofExpr(stack.pop()))
            return False

        # Coercion / conversion
        if op in _COERCE_TYPE_NAMES:
            if stack:
                type_name = _COERCE_TYPE_NAMES[op]
                stack.append(CastExpr(type_name, stack.pop()))
            return False
        if op in (OP_COERCE_A, OP_COERCE_O, OP_CONVERT_O):
            # Coerce-to-any / coerce-to-object: pass through
            return False
        if op == OP_COERCE:
            # Coerce to named type — operand is multiname index
            if stack:
                name = resolve_multiname(self.abc, instr.operands[0])
                stack.append(CastExpr(name, stack.pop()))
            return False
        if op in (OP_ASTYPE, OP_ASTYPELATE):
            if op == OP_ASTYPELATE and len(stack) >= 2:
                ref = stack.pop()
                val = stack.pop()
                stack.append(AsExpr(val, ref))
            elif op == OP_ASTYPE and stack:
                name = resolve_multiname(self.abc, instr.operands[0])
                stack.append(AsExpr(stack.pop(), Identifier(name)))
            return False
        if op in (OP_ISTYPE, OP_ISTYPELATE):
            if op == OP_ISTYPELATE and len(stack) >= 2:
                ref = stack.pop()
                val = stack.pop()
                stack.append(IsExpr(val, ref))
            elif op == OP_ISTYPE and stack:
                name = resolve_multiname(self.abc, instr.operands[0])
                stack.append(IsExpr(stack.pop(), Identifier(name)))
            return False
        if op == OP_INSTANCEOF:
            if len(stack) >= 2:
                ref = stack.pop()
                val = stack.pop()
                stack.append(BinaryOp("instanceof", val, ref))
            return False
        if op == OP_IN:
            if len(stack) >= 2:
                obj = stack.pop()
                key = stack.pop()
                stack.append(InExpr(key, obj))
            return False

        # Property access
        if op == OP_GETLEX:
            name = resolve_multiname(self.abc, instr.operands[0])
            stack.append(Identifier(name))
            return False
        if op == OP_FINDPROPERTY or op == OP_FINDPROPSTRICT:
            # Push a "scope" marker resolving to the named identifier.
            # We approximate as Identifier(name) so subsequent
            # getproperty/callproperty produces ``name.foo()`` or
            # ``name()``.
            name = resolve_multiname(self.abc, instr.operands[0])
            stack.append(Identifier(name))
            return False
        if op == OP_GETPROPERTY:
            if stack:
                target = stack.pop()
                name = resolve_multiname(self.abc, instr.operands[0])
                if isinstance(target, Identifier) and target.name == name:
                    # findpropstrict+getproperty is the standard idiom
                    # to load a lexical name — collapse to the name
                    # itself rather than ``name.name``.
                    stack.append(target)
                else:
                    stack.append(MemberAccess(target, name))
            return False
        if op == OP_SETPROPERTY or op == OP_INITPROPERTY:
            if len(stack) >= 2:
                value = stack.pop()
                target = stack.pop()
                name = resolve_multiname(self.abc, instr.operands[0])
                if isinstance(target, Identifier) and target.name == name:
                    # findpropstrict + setproperty on the same name:
                    # collapse to ``name = value`` rather than
                    # ``name.name = value``. Mirrors the same idiom
                    # recognised on the getproperty side.
                    lhs: Expression = target
                else:
                    lhs = MemberAccess(target, name)
                statements.append(ExpressionStmt(AssignExpr(lhs, value)))
            return False
        if op == OP_GETSLOT:
            if stack:
                target = stack.pop()
                stack.append(MemberAccess(target, f"_slot{instr.operands[0]}_"))
            return False
        if op == OP_SETSLOT:
            if len(stack) >= 2:
                value = stack.pop()
                target = stack.pop()
                statements.append(ExpressionStmt(AssignExpr(
                    MemberAccess(target, f"_slot{instr.operands[0]}_"),
                    value,
                )))
            return False
        if op == OP_GETSUPER:
            if stack:
                target = stack.pop()
                name = resolve_multiname(self.abc, instr.operands[0])
                stack.append(MemberAccess(Identifier("super"), name))
            return False

        # Calls
        if op in (OP_CALLPROPERTY, OP_CALLPROPLEX, OP_CALLPROPVOID):
            mn_idx, arg_count = instr.operands
            args = self._pop_args(stack, arg_count)
            if stack:
                receiver = stack.pop()
                name = resolve_multiname(self.abc, mn_idx)
                if isinstance(receiver, Identifier) and receiver.name == name:
                    callee: Expression = Identifier(name)
                else:
                    callee = MemberAccess(receiver, name)
                call = MethodCall(callee, args)
                if op == OP_CALLPROPVOID:
                    statements.append(ExpressionStmt(call))
                else:
                    stack.append(call)
            return False
        if op in (OP_CALLSUPER, OP_CALLSUPERVOID):
            mn_idx, arg_count = instr.operands
            args = self._pop_args(stack, arg_count)
            if stack:
                stack.pop()  # discard 'this'
                name = resolve_multiname(self.abc, mn_idx)
                call = MethodCall(
                    MemberAccess(Identifier("super"), name), args,
                )
                if op == OP_CALLSUPERVOID:
                    statements.append(ExpressionStmt(call))
                else:
                    stack.append(call)
            return False
        if op == OP_CALL:
            arg_count = instr.operands[0]
            args = self._pop_args(stack, arg_count)
            if len(stack) >= 2:
                stack.pop()       # receiver (unused in AS3 source)
                callee = stack.pop()
                stack.append(MethodCall(callee, args))
            return False
        if op == OP_CALLSTATIC:
            # Rare. Treat as pop(arg_count + 1) and push a placeholder.
            method_idx, arg_count = instr.operands
            args = self._pop_args(stack, arg_count)
            if stack:
                stack.pop()
            stack.append(MethodCall(
                Identifier(f"_method{method_idx}_"), args,
            ))
            return False
        if op == OP_CALLMETHOD:
            # dispid-indexed call — rare in compiler output
            disp_id, arg_count = instr.operands
            args = self._pop_args(stack, arg_count)
            if stack:
                receiver = stack.pop()
                stack.append(MethodCall(
                    MemberAccess(receiver, f"_m{disp_id}_"), args,
                ))
            return False
        if op == OP_CONSTRUCT:
            arg_count = instr.operands[0]
            args = self._pop_args(stack, arg_count)
            if stack:
                callee = stack.pop()
                stack.append(NewExpr(callee, args))
            return False
        if op == OP_CONSTRUCTPROP:
            mn_idx, arg_count = instr.operands
            args = self._pop_args(stack, arg_count)
            if stack:
                stack.pop()  # discard scope receiver
                name = resolve_multiname(self.abc, mn_idx)
                stack.append(NewExpr(Identifier(name), args))
            return False
        if op == OP_CONSTRUCTSUPER:
            arg_count = instr.operands[0]
            args = self._pop_args(stack, arg_count)
            if stack:
                stack.pop()
                statements.append(ExpressionStmt(MethodCall(
                    Identifier("super"), args,
                )))
            return False
        if op == OP_NEWFUNCTION:
            # Push placeholder — AS3 source will come from a later pass
            # that knows how to decompile nested functions.
            stack.append(Identifier(f"_func{instr.operands[0]}_"))
            return False

        # Object/array creation
        if op == OP_NEWARRAY:
            count = instr.operands[0]
            elements = self._pop_args(stack, count)
            stack.append(ArrayLiteral(elements))
            return False
        if op == OP_NEWOBJECT:
            count = instr.operands[0]
            # pairs: [k0, v0, k1, v1, ...] on stack (oldest at bottom)
            props: list[ObjectProperty] = []
            popped = self._pop_args(stack, count * 2)
            for i in range(count):
                k = popped[2 * i]
                v = popped[2 * i + 1]
                key_str = k.value if isinstance(k, Literal) and isinstance(k.value, str) else str(k)
                props.append(ObjectProperty(key=key_str, value=v))
            stack.append(ObjectLiteral(props))
            return False
        if op == OP_NEWCATCH:
            stack.append(Identifier(f"_catch{instr.operands[0]}_"))
            return False

        # Iteration opcodes — push placeholders; Phase 8 will detect
        # for-in / for-each patterns.
        if op == OP_HASNEXT or op == OP_HASNEXT2 or op == OP_NEXTNAME \
                or op == OP_NEXTVALUE:
            # Consume the spec'd number of operands and push a marker.
            if op == OP_HASNEXT2:
                # Registers specified by operand, no stack consumption.
                reg1, reg2 = instr.operands
                stack.append(MethodCall(
                    Identifier("_hasnext2"),
                    [Identifier(self._local_name(reg1)),
                     Identifier(self._local_name(reg2))],
                ))
            elif op == OP_HASNEXT:
                if len(stack) >= 2:
                    idx = stack.pop()
                    obj = stack.pop()
                    stack.append(MethodCall(Identifier("_hasnext"),
                                            [obj, idx]))
            elif op == OP_NEXTNAME:
                if len(stack) >= 2:
                    idx = stack.pop()
                    obj = stack.pop()
                    stack.append(MethodCall(Identifier("_nextname"),
                                            [obj, idx]))
            elif op == OP_NEXTVALUE:
                if len(stack) >= 2:
                    idx = stack.pop()
                    obj = stack.pop()
                    stack.append(MethodCall(Identifier("_nextvalue"),
                                            [obj, idx]))
            return False

        # Terminators
        if op == OP_RETURNVOID:
            statements.append(ReturnStmt(None))
            result.terminator = "return"
            return True
        if op == OP_RETURNVALUE:
            value = stack.pop() if stack else Identifier("undefined")
            statements.append(ReturnStmt(value))
            result.terminator = "return"
            return True
        if op == OP_THROW:
            value = stack.pop() if stack else Identifier("undefined")
            statements.append(ThrowStmt(value))
            result.terminator = "throw"
            return True
        if op == OP_JUMP:
            result.terminator = "jump"
            return True
        if op in _CONDITIONAL_BRANCH_BUILDERS:
            self._record_conditional_branch(op, stack, result)
            return True
        if op == OP_LOOKUPSWITCH:
            # switch_targets = [default, case_0, ..., case_N]
            default_delta = instr.operands[0]
            case_count = instr.operands[1]
            base = instr.offset
            targets = [base + default_delta]
            for i in range(case_count + 1):
                targets.append(base + instr.operands[2 + i])
            result.switch_targets = targets
            result.terminator = "switch"
            if stack:
                result.branch_condition = stack.pop()
            return True

        # Fallback: opcode we don't model yet. Drop a placeholder so
        # structure is preserved but source will contain it literally.
        log.debug("stack-sim: unhandled opcode 0x%02X (%s) at 0x%X",
                  op, instr.mnemonic, instr.offset)
        return False

    # ── small helpers ──────────────────────────────────────────────────────

    def _emit_setlocal(self, stack, statements, reg: int) -> None:
        if not stack:
            return
        value = stack.pop()
        statements.append(ExpressionStmt(
            AssignExpr(Identifier(self._local_name(reg)), value),
        ))

    def _local_name(self, reg: int) -> str:
        """Return the source-visible name for local register ``reg``.

        Register 0 is ``this`` (or the class name for static methods).
        Registers ``1..param_count`` are ``_arg_1..._arg_N`` to match
        the AS3 parameter naming convention; higher registers fall
        back to the generic ``_loc{reg}_`` form."""
        if reg == 0:
            return self.local0_name
        if 1 <= reg <= self.param_count:
            return f"_arg_{reg}"
        return f"_loc{reg}_"

    def _pop_args(self, stack, n: int) -> list[Expression]:
        """Pop ``n`` arguments off the stack in call order
        (oldest first)."""
        if n == 0:
            return []
        if len(stack) < n:
            # Underflow: take what's there.
            n = len(stack)
        args = stack[-n:]
        del stack[-n:]
        return args

    def _has_side_effects(self, expr: Expression) -> bool:
        if isinstance(expr, (MethodCall, NewExpr, AssignExpr)):
            return True
        if isinstance(expr, (MemberAccess, IndexAccess)):
            return self._has_side_effects(expr.target)
        return False

    def _record_conditional_branch(self, op, stack, result) -> None:
        """Set ``result.terminator = "if"`` and populate
        ``branch_condition`` based on the opcode's polarity."""
        kind = _CONDITIONAL_BRANCH_BUILDERS[op]
        if kind == "truthy":
            cond = stack.pop() if stack else Identifier("_unknown")
        elif kind == "falsy":
            cond_inner = stack.pop() if stack else Identifier("_unknown")
            cond = UnaryOp("!", cond_inner)
        else:
            # compare-and-branch
            right = stack.pop() if stack else Identifier("_unknown")
            left = stack.pop() if stack else Identifier("_unknown")
            if kind.startswith("!"):
                cond = UnaryOp("!", BinaryOp(kind[1:], left, right))
            else:
                cond = BinaryOp(kind, left, right)
        result.terminator = "if"
        result.branch_condition = cond
