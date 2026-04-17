"""
AVM2 bytecode parsing and serialization.

This package handles the ABC (ActionScript Byte Code) format — the bytecode
that runs on Adobe's AVM2 virtual machine inside Flash Player and Adobe AIR.

Quick start::

    from flashkit.abc import parse_abc, serialize_abc, AbcFile

    abc = parse_abc(raw_bytes)
    print(f"Classes: {len(abc.instances)}")
    output = serialize_abc(abc)
    assert output == raw_bytes  # round-trip fidelity
"""

from .types import (
    AbcFile,
    NamespaceInfo,
    NsSetInfo,
    MultinameInfo,
    MethodInfo,
    MetadataInfo,
    TraitInfo,
    InstanceInfo,
    AbcClassInfo,
    ClassInfo,  # legacy alias for AbcClassInfo
    ScriptInfo,
    ExceptionInfo,
    MethodBodyInfo,
)
from .parser import (
    parse_abc,
    read_u30,
    read_s32,
    write_u30,
    write_s32,
    s24,
    read_u8,
    read_u16,
    read_u32,
    read_d64,
)
from .writer import serialize_abc
from .disasm import Instruction, ResolvedInstruction, decode_instructions, resolve_instructions, scan_relevant_opcodes
from .builder import AbcBuilder

__all__ = [
    # Types
    "AbcFile",
    "NamespaceInfo",
    "NsSetInfo",
    "MultinameInfo",
    "MethodInfo",
    "MetadataInfo",
    "TraitInfo",
    "InstanceInfo",
    "AbcClassInfo",
    "ClassInfo",  # legacy alias
    "ScriptInfo",
    "ExceptionInfo",
    "MethodBodyInfo",
    # Parser
    "parse_abc",
    "read_u30",
    "read_s32",
    "write_u30",
    "write_s32",
    "s24",
    "read_u8",
    "read_u16",
    "read_u32",
    "read_d64",
    # Writer
    "serialize_abc",
    # Disassembler
    "Instruction",
    "ResolvedInstruction",
    "decode_instructions",
    "resolve_instructions",
    "scan_relevant_opcodes",
    # Builder
    "AbcBuilder",
]
