"""Tests for flashkit.analysis.strings — StringIndex."""

import pytest

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.parser import parse_abc
from flashkit.abc.writer import serialize_abc
from flashkit.abc.constants import TRAIT_Method
from flashkit.info.class_info import build_all_classes
from flashkit.analysis.strings import StringIndex


def _build_string_index(string_values):
    """Build a StringIndex from a class whose method pushes the given strings.

    Args:
        string_values: List of strings to push via OP_pushstring.

    Returns:
        (StringIndex, classes)
    """
    b = AbcBuilder()
    pub = b.package_namespace("")
    priv = b.private_namespace()
    cls_mn = b.qname(pub, "StringUser")

    # Build code that pushes each string
    code_parts = [b.op_getlocal_0(), b.op_pushscope()]
    for s in string_values:
        str_idx = b.string(s)
        code_parts.append(b.op_pushstring(str_idx))
        code_parts.append(b.op_pop())
    code_parts.append(b.op_returnvoid())

    m = b.method()
    b.method_body(m, code=b.asm(*code_parts),
                  max_stack=2, local_count=1)

    method_mn = b.qname(priv, "doStuff")
    b.define_class(
        name=cls_mn, super_name=0,
        instance_traits=[b.trait_method(method_mn, m)])
    b.script()

    abc = b.build()
    raw = serialize_abc(abc)
    abc2 = parse_abc(raw)
    classes = build_all_classes(abc2)
    index = StringIndex.from_abc(abc2, classes)
    return index, classes


class TestStringIndexSearch:
    def test_search_substring(self):
        idx, _ = _build_string_index(["hello world", "goodbye"])
        results = idx.search("hello")
        assert "hello world" in results

    def test_search_case_insensitive(self):
        idx, _ = _build_string_index(["Hello World"])
        results = idx.search("hello")
        assert "Hello World" in results

    def test_search_regex(self):
        idx, _ = _build_string_index(["config.xml", "data.json", "style.css"])
        results = idx.search(r"\.json$", regex=True)
        assert "data.json" in results
        assert "config.xml" not in results

    def test_search_no_match(self):
        idx, _ = _build_string_index(["abc"])
        results = idx.search("xyz")
        assert results == []


class TestStringIndexPool:
    def test_pool_strings(self):
        idx, _ = _build_string_index(["test"])
        # Pool should contain at least the strings used by the class
        assert "test" in idx.pool_strings

    def test_search_pool(self):
        idx, _ = _build_string_index(["alpha"])
        results = idx.search_pool("alpha")
        assert "alpha" in results


class TestStringIndexUsages:
    def test_classes_using_string(self):
        idx, _ = _build_string_index(["marker"])
        classes = idx.classes_using_string("marker")
        assert "StringUser" in classes

    def test_strings_in_class(self):
        idx, _ = _build_string_index(["foo", "bar"])
        strings = idx.strings_in_class("StringUser")
        assert "foo" in strings
        assert "bar" in strings

    def test_unique_string_count(self):
        idx, _ = _build_string_index(["a", "b", "c"])
        assert idx.unique_string_count >= 3

    def test_total_usages(self):
        idx, _ = _build_string_index(["x", "y"])
        assert idx.total_usages >= 2


class TestStringIndexClassifiers:
    def test_url_strings(self):
        idx, _ = _build_string_index([
            "http://example.com",
            "https://api.test.com",
            "regular string",
        ])
        urls = idx.url_strings()
        assert "http://example.com" in urls
        assert "https://api.test.com" in urls
        assert "regular string" not in urls

    def test_debug_markers(self):
        idx, _ = _build_string_index([
            "Main.as",
            "Sprite.hx",
            "not a debug file",
        ])
        markers = idx.debug_markers()
        assert "Main.as" in markers
        assert "Sprite.hx" in markers

    def test_ui_strings(self):
        idx, _ = _build_string_index([
            "Click to continue",
            "x",
            "http://example.com",
        ])
        ui = idx.ui_strings()
        assert "Click to continue" in ui
        assert "x" not in ui
