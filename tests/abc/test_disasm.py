"""Tests for flashkit.abc.disasm — AVM2 instruction decoder."""

import pytest

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.disasm import decode_instructions, Instruction
from flashkit.abc.constants import (
    OP_getlocal_0, OP_pushscope, OP_returnvoid, OP_pushstring,
    OP_callpropvoid, OP_pushbyte, OP_jump, OP_debug,
)
from flashkit.errors import ABCParseError


class TestDecodeBasic:
    def test_empty_code(self):
        result = decode_instructions(b"")
        assert result == []

    def test_single_instruction(self):
        result = decode_instructions(bytes([OP_returnvoid]))
        assert len(result) == 1
        assert result[0].mnemonic == "returnvoid"
        assert result[0].offset == 0
        assert result[0].size == 1

    def test_multiple_instructions(self):
        code = bytes([OP_getlocal_0, OP_pushscope, OP_returnvoid])
        result = decode_instructions(code)
        assert len(result) == 3
        assert result[0].mnemonic == "getlocal_0"
        assert result[1].mnemonic == "pushscope"
        assert result[2].mnemonic == "returnvoid"

    def test_offsets_sequential(self):
        code = bytes([OP_getlocal_0, OP_pushscope, OP_returnvoid])
        result = decode_instructions(code)
        assert result[0].offset == 0
        assert result[1].offset == 1
        assert result[2].offset == 2


class TestDecodeOperands:
    def test_pushbyte(self):
        code = bytes([OP_pushbyte, 42])
        result = decode_instructions(code)
        assert len(result) == 1
        assert result[0].mnemonic == "pushbyte"
        assert result[0].operands == [42]

    def test_pushstring_u30(self):
        code = bytes([OP_pushstring, 0x05])  # u30 = 5
        result = decode_instructions(code)
        assert len(result) == 1
        assert result[0].mnemonic == "pushstring"
        assert result[0].operands == [5]

    def test_callpropvoid_two_u30s(self):
        code = bytes([OP_callpropvoid, 0x03, 0x01])  # mn_index=3, arg_count=1
        result = decode_instructions(code)
        assert len(result) == 1
        assert result[0].mnemonic == "callpropvoid"
        assert result[0].operands == [3, 1]

    def test_jump_s24(self):
        # jump with offset +5 → 05 00 00
        code = bytes([OP_jump, 0x05, 0x00, 0x00])
        result = decode_instructions(code)
        assert len(result) == 1
        assert result[0].mnemonic == "jump"
        assert result[0].operands == [5]

    def test_jump_negative_s24(self):
        # jump with offset -1 → FF FF FF
        code = bytes([OP_jump, 0xFF, 0xFF, 0xFF])
        result = decode_instructions(code)
        assert len(result) == 1
        assert result[0].operands == [-1]


class TestDecodeFromBuilder:
    """Decode bytecode produced by AbcBuilder's op_*() methods."""

    def test_builder_method_body(self):
        b = AbcBuilder()
        code = b.asm(
            b.op_getlocal_0(),
            b.op_pushscope(),
            b.op_pushstring(5),
            b.op_pop(),
            b.op_returnvoid(),
        )
        result = decode_instructions(code)
        mnemonics = [i.mnemonic for i in result]
        assert mnemonics == [
            "getlocal_0", "pushscope", "pushstring", "pop", "returnvoid"
        ]

    def test_builder_branch_instructions(self):
        code = AbcBuilder.asm(
            AbcBuilder.op_pushtrue(),
            AbcBuilder.op_iftrue(0),
            AbcBuilder.op_returnvoid(),
        )
        result = decode_instructions(code)
        assert len(result) == 3
        assert result[1].mnemonic == "iftrue"
        assert result[1].operands == [0]


class TestDecodeErrorHandling:
    def test_unknown_opcode_nonstrict(self):
        """Unknown opcode in non-strict mode should produce unknown_ instruction."""
        code = bytes([0x01])  # 0x01 is not a standard opcode
        result = decode_instructions(code, strict=False)
        assert len(result) == 1
        assert "unknown" in result[0].mnemonic

    def test_unknown_opcode_strict(self):
        """Unknown opcode in strict mode should raise ABCParseError."""
        code = bytes([0x01])
        with pytest.raises(ABCParseError, match="Unknown opcode"):
            decode_instructions(code, strict=True)

    def test_truncated_operand_nonstrict(self):
        """Truncated operand in non-strict mode should not crash."""
        # pushstring expects a u30 operand but we give nothing
        code = bytes([OP_pushstring])
        result = decode_instructions(code, strict=False)
        # Should produce a partial instruction or handle gracefully
        assert len(result) >= 0  # doesn't crash

    def test_truncated_operand_strict(self):
        """Truncated operand in strict mode should raise ABCParseError."""
        code = bytes([OP_pushstring])
        with pytest.raises(ABCParseError, match="Truncated"):
            decode_instructions(code, strict=True)
