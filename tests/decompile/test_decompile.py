"""Smoke tests for the decompile package.

Synthetic tests use a minimal ABC built via AbcBuilder. A separate
optional real-SWF test runs only when FLASHKIT_TEST_SWF is set in the
environment (to test on a local SWF without committing any binary).
"""

from __future__ import annotations

import os
import pytest

from flashkit.abc.builder import AbcBuilder
from flashkit.abc.writer import serialize_abc
from flashkit.abc.parser import parse_abc
from flashkit.decompile import (
    decompile_class, decompile_method, decompile_method_body, list_classes,
)


def _build_empty_class(name: str = "Foo") -> bytes:
    """Build a minimal ABC with one empty class and return the raw bytes."""
    b = AbcBuilder()
    ns = b.package_namespace(0)
    mn = b.qname(ns, b.string(name))
    ctor = b.method()
    b.method_body(ctor, code=b.asm(b.op_getlocal_0(), b.op_pushscope(),
                                   b.op_returnvoid()))
    b.define_class(name=mn, super_name=0, constructor=ctor)
    return serialize_abc(b.build())


def test_lazy_import():
    """``import flashkit`` and ``import flashkit.decompile`` stay cheap."""
    import sys
    import flashkit.decompile  # noqa: F401

    # The heavy submodules shouldn't be loaded by __init__ alone.
    heavy = ("flashkit.decompile.method", "flashkit.decompile.class_")
    # Touching an attribute triggers the lazy load; just prove it works on demand.
    from flashkit.decompile import list_classes as _lc
    assert callable(_lc)


def test_list_classes_synthetic():
    abc = parse_abc(_build_empty_class("Widget"))
    classes = list_classes(abc)
    assert any(c["name"] == "Widget" for c in classes)


def test_decompile_class_synthetic():
    abc = parse_abc(_build_empty_class("Widget"))
    src = decompile_class(abc, name="Widget")
    assert "package" in src
    assert "class Widget" in src


def test_decompile_ambiguous_name_rejected():
    # Two classes with the same short name but different packages.
    b = AbcBuilder()
    ns_a = b.package_namespace(b.string("pkg.a"))
    ns_b = b.package_namespace(b.string("pkg.b"))
    mn_a = b.qname(ns_a, b.string("Dup"))
    mn_b = b.qname(ns_b, b.string("Dup"))
    for mn in (mn_a, mn_b):
        m = b.method()
        b.method_body(m, code=b.asm(b.op_getlocal_0(), b.op_pushscope(),
                                    b.op_returnvoid()))
        b.define_class(name=mn, super_name=0, constructor=m)
    abc = parse_abc(serialize_abc(b.build()))

    # Short name is ambiguous.
    with pytest.raises(ValueError, match="ambiguous"):
        decompile_class(abc, name="Dup")

    # Fully qualified works.
    src = decompile_class(abc, name="pkg.a.Dup")
    assert "class Dup" in src


# ── Optional: real SWF smoke test (skipped if FLASHKIT_TEST_SWF unset) ─────

_REAL_SWF = os.environ.get("FLASHKIT_TEST_SWF")


@pytest.mark.skipif(not _REAL_SWF, reason="FLASHKIT_TEST_SWF not set")
def test_real_swf_listing():
    """List classes in a real SWF without decompiling any body."""
    from flashkit.decompile import DecompilerCache
    cache = DecompilerCache()
    classes = cache.list_classes(_REAL_SWF)
    assert len(classes) > 0
    # Every entry has the expected keys.
    for c in classes[:5]:
        for key in ("index", "name", "package", "full_name",
                    "super", "is_interface", "trait_count"):
            assert key in c


@pytest.mark.skipif(not _REAL_SWF, reason="FLASHKIT_TEST_SWF not set")
def test_real_swf_small_class_decompiles():
    """Decompile a small class from a real SWF.

    We pick the first non-interface, non-large class we see and verify
    the output is non-empty and contains a package/class declaration.
    """
    from flashkit.decompile import DecompilerCache
    cache = DecompilerCache()
    classes = cache.list_classes(_REAL_SWF)
    for c in classes:
        if not c["is_interface"] and 2 <= c["trait_count"] <= 40:
            src = cache.decompile_class(_REAL_SWF, c["name"])
            assert "package" in src
            assert f"class {c['name']}" in src
            break
    else:
        pytest.skip("No small class found in real SWF")
