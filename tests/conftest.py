"""Shared test fixtures and helpers."""

import struct
import pytest
from pathlib import Path

from flashkit.abc.parser import parse_abc, write_u30, write_s32
from flashkit.abc.types import AbcFile
from flashkit.abc.constants import (
    CONSTANT_QName, CONSTANT_PackageNamespace, CONSTANT_PrivateNs,
    TRAIT_Slot, TRAIT_Method, TRAIT_Const,
    INSTANCE_Sealed,
    METHOD_HasParamNames,
)


def build_abc_bytes(
    strings: list[str] | None = None,
    with_class: bool = False,
) -> bytes:
    """Build synthetic ABC bytecode for unit tests.

    Args:
        strings: Extra strings to put in the string pool.
        with_class: If True, include a simple class with a field and method.

    Returns:
        Raw ABC bytes that parse_abc() can consume.
    """
    strings = strings or []

    # Collect all strings we'll need
    all_strings = list(strings)
    if with_class:
        # Ensure we have the class-related strings
        for s in ["TestClass", "com.test", "Object", "",
                   "myField", "int", "doStuff", "void", "arg0", "String"]:
            if s not in all_strings:
                all_strings.append(s)

    out = bytearray()
    out += struct.pack("<HH", 16, 46)  # ABC version 46.16

    # int pool — empty (count 0)
    out += write_u30(0)
    # uint pool — empty
    out += write_u30(0)
    # double pool — empty
    out += write_u30(0)

    # string pool
    if all_strings:
        out += write_u30(len(all_strings) + 1)  # +1 for default ""
        for s in all_strings:
            encoded = s.encode("utf-8")
            out += write_u30(len(encoded))
            out += encoded
    else:
        out += write_u30(0)

    # Build string index helper
    def sidx(s: str) -> int:
        """Get 1-based string pool index."""
        return all_strings.index(s) + 1 if s in all_strings else 0

    if with_class:
        # namespace pool: [default, package "com.test", private ""]
        out += write_u30(3)
        # ns[1] = PackageNamespace("com.test")
        out += bytes([CONSTANT_PackageNamespace])
        out += write_u30(sidx("com.test"))
        # ns[2] = PrivateNs("")
        out += bytes([CONSTANT_PrivateNs])
        out += write_u30(sidx(""))

        # ns_set pool — empty
        out += write_u30(0)

        # multiname pool: [default, QName(ns1,"TestClass"), QName(ns1,"Object"),
        #                   QName(ns2,"myField"), QName(ns1,"int"),
        #                   QName(ns2,"doStuff"), QName(ns1,"void"),
        #                   QName(ns1,"String")]
        mn_entries = [
            (1, "TestClass"),  # mn[1]
            (1, "Object"),     # mn[2]
            (2, "myField"),    # mn[3]
            (1, "int"),        # mn[4]
            (2, "doStuff"),    # mn[5]
            (1, "void"),       # mn[6]
            (1, "String"),     # mn[7]
        ]
        out += write_u30(len(mn_entries) + 1)
        for ns_idx, name in mn_entries:
            out += bytes([CONSTANT_QName])
            out += write_u30(ns_idx)
            out += write_u30(sidx(name))

        # methods: [0] = constructor (no params), [1] = doStuff(String):void
        out += write_u30(3)  # 3 methods: constructor, doStuff, cinit

        # method[0]: constructor () -> *
        out += write_u30(0)   # param_count
        out += write_u30(0)   # return_type (*)
        out += write_u30(0)   # name
        out += bytes([0])     # flags

        # method[1]: doStuff(String arg0) -> void
        out += write_u30(1)   # param_count
        out += write_u30(6)   # return_type = mn[6] = void
        out += write_u30(7)   # param_types[0] = mn[7] = String
        out += write_u30(0)   # name
        out += bytes([METHOD_HasParamNames])  # flags
        out += write_u30(sidx("arg0"))  # param_names[0]

        # method[2]: static init () -> *
        out += write_u30(0)
        out += write_u30(0)
        out += write_u30(0)
        out += bytes([0])

        # metadata — none
        out += write_u30(0)

        # instances (1 class)
        out += write_u30(1)
        # instance[0]:
        out += write_u30(1)          # name = mn[1] = TestClass
        out += write_u30(2)          # super_name = mn[2] = Object
        out += bytes([INSTANCE_Sealed])  # flags
        out += write_u30(0)          # interface count
        out += write_u30(0)          # iinit = method[0]

        # instance traits: 1 field + 1 method
        out += write_u30(2)  # trait count

        # trait[0]: field myField:int (TRAIT_Slot)
        out += write_u30(3)              # name = mn[3] = myField
        out += bytes([TRAIT_Slot])       # kind
        out += write_u30(1)              # slot_id
        out += write_u30(4)              # type = mn[4] = int
        out += write_u30(0)              # vindex (no default)

        # trait[1]: method doStuff (TRAIT_Method)
        out += write_u30(5)              # name = mn[5] = doStuff
        out += bytes([TRAIT_Method])     # kind
        out += write_u30(0)              # disp_id
        out += write_u30(1)              # method = method[1]

        # classes (static side)
        # class[0]:
        out += write_u30(2)   # cinit = method[2]
        out += write_u30(0)   # 0 static traits

        # scripts — 1 empty script
        out += write_u30(1)
        out += write_u30(0)   # init = method[0]
        out += write_u30(0)   # 0 traits

        # method bodies — constructor + doStuff + cinit
        out += write_u30(3)

        # body for method[0] (constructor): getlocal_0, pushscope, returnvoid
        code0 = bytes([0xD0, 0x30, 0x47])
        out += write_u30(0)   # method
        out += write_u30(1)   # max_stack
        out += write_u30(1)   # local_count
        out += write_u30(0)   # init_scope_depth
        out += write_u30(1)   # max_scope_depth
        out += write_u30(len(code0))
        out += code0
        out += write_u30(0)   # exception count
        out += write_u30(0)   # trait count

        # body for method[1] (doStuff): getlocal_0, pushscope,
        #   pushstring "hello", pop, returnvoid
        code1 = bytes([0xD0, 0x30, 0x2C]) + write_u30(sidx("TestClass")) + bytes([0x29, 0x47])
        out += write_u30(1)
        out += write_u30(2)
        out += write_u30(2)
        out += write_u30(0)
        out += write_u30(1)
        out += write_u30(len(code1))
        out += code1
        out += write_u30(0)
        out += write_u30(0)

        # body for method[2] (cinit): returnvoid
        code2 = bytes([0x47])
        out += write_u30(2)
        out += write_u30(0)
        out += write_u30(1)
        out += write_u30(0)
        out += write_u30(0)
        out += write_u30(len(code2))
        out += code2
        out += write_u30(0)
        out += write_u30(0)

    else:
        # No classes — minimal pools
        # namespace pool — empty
        out += write_u30(0)
        # ns_set pool — empty
        out += write_u30(0)
        # multiname pool — empty
        out += write_u30(0)
        # methods
        out += write_u30(0)
        # metadata
        out += write_u30(0)
        # instances
        out += write_u30(0)
        # scripts
        out += write_u30(0)
        # method bodies
        out += write_u30(0)

    return bytes(out)


def build_swf_bytes(abc_data: bytes | None = None) -> bytes:
    """Build a minimal FWS (uncompressed) SWF containing one DoABC2 tag.

    Args:
        abc_data: Optional ABC bytes. If None, builds a minimal ABC.

    Returns:
        Complete SWF file bytes.
    """
    if abc_data is None:
        abc_data = build_abc_bytes()

    # DoABC2 payload: 4-byte flags + null-terminated name + ABC data
    abc_name = b"test\x00"
    abc_payload = struct.pack("<I", 1) + abc_name + abc_data

    # Build tags
    tags_bytes = bytearray()

    # DoABC2 tag (type 82, long header)
    tag_type = 82
    tags_bytes += struct.pack("<H", (tag_type << 6) | 0x3F)
    tags_bytes += struct.pack("<I", len(abc_payload))
    tags_bytes += abc_payload

    # End tag (type 0)
    tags_bytes += struct.pack("<H", 0)

    # SWF header
    # RECT: 5 bits for nbits=0 → 1 byte (just 0x00)
    rect = bytes([0x00])
    frame_rate = struct.pack("<H", 24 << 8)  # 24 fps
    frame_count = struct.pack("<H", 1)
    header_body = rect + frame_rate + frame_count

    file_length = 8 + len(header_body) + len(tags_bytes)

    swf = bytearray()
    swf += b"FWS"
    swf += bytes([40])  # version 40
    swf += struct.pack("<I", file_length)
    swf += header_body
    swf += tags_bytes

    return bytes(swf)


@pytest.fixture
def abc_data() -> bytes:
    """Minimal ABC with no classes."""
    return build_abc_bytes()


@pytest.fixture
def abc_with_class() -> bytes:
    """ABC with one class (TestClass), one field, one method."""
    return build_abc_bytes(with_class=True)


@pytest.fixture
def swf_data() -> bytes:
    """Minimal SWF containing a DoABC2 tag."""
    return build_swf_bytes()


@pytest.fixture
def swf_with_class() -> bytes:
    """SWF containing an ABC block with one class."""
    return build_swf_bytes(build_abc_bytes(with_class=True))
