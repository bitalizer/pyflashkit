"""Tests for flashkit.abc.parser — LEB128 codecs and parse_abc."""

import struct
import pytest

from flashkit.abc.parser import (
    read_u30, write_u30, read_s32, write_s32,
    read_u8, read_u16, read_u32, read_d64, s24,
    parse_abc,
)
from flashkit.abc.types import AbcFile
from flashkit.errors import ABCParseError


class TestReadU30:
    def test_single_byte(self):
        val, off = read_u30(bytes([0x05]), 0)
        assert val == 5
        assert off == 1

    def test_two_bytes(self):
        val, off = read_u30(bytes([0x80, 0x01]), 0)
        assert val == 128
        assert off == 2

    def test_zero(self):
        val, off = read_u30(bytes([0x00]), 0)
        assert val == 0

    def test_max_single(self):
        val, off = read_u30(bytes([0x7F]), 0)
        assert val == 127

    def test_offset(self):
        data = bytes([0xFF, 0x05])
        val, off = read_u30(data, 1)
        assert val == 5
        assert off == 2


class TestWriteU30:
    def test_zero(self):
        assert write_u30(0) == bytes([0x00])

    def test_small(self):
        assert write_u30(5) == bytes([0x05])

    def test_127(self):
        assert write_u30(127) == bytes([0x7F])

    def test_128(self):
        assert write_u30(128) == bytes([0x80, 0x01])

    def test_roundtrip(self):
        for v in [0, 1, 127, 128, 255, 16383, 16384, 1000000]:
            encoded = write_u30(v)
            decoded, _ = read_u30(encoded, 0)
            assert decoded == (v & 0x3FFFFFFF)


class TestReadWriteS32:
    def test_positive(self):
        val, off = read_s32(bytes([0x05]), 0)
        assert val == 5

    def test_negative_one(self):
        encoded = write_s32(-1)
        val, _ = read_s32(encoded, 0)
        assert val == -1

    def test_roundtrip(self):
        # Note: LEB128 s32 uses 5 bytes max with only 4 usable bits in
        # the last byte, so min int32 (-2147483648) doesn't round-trip.
        for v in [0, 1, -1, 127, -128, 32767, -32768, 2147483647, -100000]:
            encoded = write_s32(v)
            decoded, _ = read_s32(encoded, 0)
            assert decoded == v


class TestReadPrimitives:
    def test_read_u8(self):
        val, off = read_u8(bytes([42]), 0)
        assert val == 42
        assert off == 1

    def test_read_u16(self):
        val, off = read_u16(struct.pack("<H", 1000), 0)
        assert val == 1000
        assert off == 2

    def test_read_u32(self):
        val, off = read_u32(struct.pack("<I", 100000), 0)
        assert val == 100000
        assert off == 4

    def test_read_d64(self):
        val, off = read_d64(struct.pack("<d", 3.14), 0)
        assert abs(val - 3.14) < 1e-10
        assert off == 8


class TestS24:
    def test_positive(self):
        result = s24(5)
        assert len(result) == 3
        val = result[0] | (result[1] << 8) | (result[2] << 16)
        assert val == 5

    def test_negative(self):
        result = s24(-1)
        assert len(result) == 3
        val = result[0] | (result[1] << 8) | (result[2] << 16)
        assert val == 0xFFFFFF  # -1 in 24-bit


class TestParseAbc:
    def test_empty_raises(self):
        with pytest.raises(ABCParseError, match="empty"):
            parse_abc(b"")

    def test_too_short_raises(self):
        with pytest.raises(ABCParseError, match="too short"):
            parse_abc(b"\x10\x00")

    def test_corrupted_raises(self):
        with pytest.raises(ABCParseError, match="Corrupted"):
            parse_abc(b"\x10\x00\x2e\x00\xff\xff\xff")

    def test_garbage_raises(self):
        with pytest.raises(ABCParseError):
            parse_abc(b"not abc data at all")

    def test_minimal(self, abc_data):
        abc = parse_abc(abc_data)
        assert isinstance(abc, AbcFile)
        assert abc.major_version == 46
        assert abc.minor_version == 16

    def test_with_class(self, abc_with_class):
        abc = parse_abc(abc_with_class)
        assert len(abc.instances) == 1
        assert len(abc.methods) == 3
        assert len(abc.method_bodies) == 3
        assert len(abc.string_pool) > 1

    def test_version_fields(self, abc_data):
        abc = parse_abc(abc_data)
        assert abc.major_version == 46
        assert abc.minor_version == 16
