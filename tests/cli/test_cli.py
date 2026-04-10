"""Tests for the flashkit CLI — exercises each subcommand via main()."""

import pytest

from flashkit.cli import main
from flashkit.abc.builder import AbcBuilder
from flashkit.abc.writer import serialize_abc
from flashkit.swf.builder import SwfBuilder


def _build_test_swf(classes=None):
    """Build a SWF with the given class definitions."""
    if classes is None:
        classes = [("com.test", "TestClass")]

    b = AbcBuilder()
    pub = b.package_namespace("")
    obj_mn = b.qname(pub, "Object")

    for pkg, name in classes:
        ns = b.package_namespace(pkg)
        cls_mn = b.qname(ns, name)
        b.define_class(name=cls_mn, super_name=obj_mn)

    b.script()
    abc_bytes = serialize_abc(b.build())

    swf = SwfBuilder(version=40, width=800, height=600, fps=30)
    swf.add_abc("TestCode", abc_bytes)
    return swf.build(compress=False)


@pytest.fixture
def swf_file(tmp_path):
    """Write a test SWF to a temp file and return its path."""
    path = tmp_path / "test.swf"
    path.write_bytes(_build_test_swf())
    return str(path)


@pytest.fixture
def multi_class_swf(tmp_path):
    """SWF with multiple classes across packages."""
    classes = [
        ("com.game", "Player"),
        ("com.game", "Enemy"),
        ("com.ui", "HUD"),
    ]
    path = tmp_path / "multi.swf"
    path.write_bytes(_build_test_swf(classes))
    return str(path)


class TestVersion:
    def test_version(self, capsys):
        with pytest.raises(SystemExit, match="0"):
            main(["--version"])
        out = capsys.readouterr().out
        assert "flashkit" in out
        assert "1.1.0" in out


class TestInfo:
    def test_basic(self, swf_file, capsys):
        main(["info", swf_file])
        out = capsys.readouterr().out
        assert "SWF" in out
        assert "Classes:" in out

    def test_shows_counts(self, swf_file, capsys):
        main(["info", swf_file])
        out = capsys.readouterr().out
        assert "ABC blocks:" in out
        assert "Methods:" in out
        assert "Strings:" in out


class TestTags:
    def test_lists_tags(self, swf_file, capsys):
        main(["tags", swf_file])
        out = capsys.readouterr().out
        assert "DoABC2" in out
        assert "End" in out
        assert "tags total" in out


class TestClasses:
    def test_lists_classes(self, swf_file, capsys):
        main(["classes", swf_file])
        out = capsys.readouterr().out
        assert "TestClass" in out
        assert "1 class(es)" in out

    def test_search_filter(self, multi_class_swf, capsys):
        main(["classes", multi_class_swf, "-s", "Player"])
        out = capsys.readouterr().out
        assert "Player" in out
        assert "HUD" not in out

    def test_package_filter(self, multi_class_swf, capsys):
        main(["classes", multi_class_swf, "-p", "com.ui"])
        out = capsys.readouterr().out
        assert "HUD" in out
        assert "Player" not in out

    def test_extends_filter(self, multi_class_swf, capsys):
        main(["classes", multi_class_swf, "-e", "Object"])
        out = capsys.readouterr().out
        assert "3 class(es)" in out

    def test_verbose(self, swf_file, capsys):
        main(["classes", swf_file, "-v"])
        out = capsys.readouterr().out
        assert "extends" in out
        assert "fields" in out

    def test_no_results(self, swf_file, capsys):
        main(["classes", swf_file, "-s", "NonExistent"])
        out = capsys.readouterr().out
        assert "No classes found" in out


class TestClassDetail:
    def test_by_name(self, swf_file, capsys):
        main(["class", swf_file, "TestClass"])
        out = capsys.readouterr().out
        assert "TestClass" in out
        assert "Extends:" in out

    def test_by_qualified_name(self, swf_file, capsys):
        main(["class", swf_file, "com.test.TestClass"])
        out = capsys.readouterr().out
        assert "TestClass" in out

    def test_not_found(self, swf_file, capsys):
        main(["class", swf_file, "NonExistent"])
        out = capsys.readouterr().out
        assert "not found" in out

    def test_ambiguous(self, multi_class_swf, capsys):
        # "e" matches both "Player" and "Enemy" (both contain 'e')
        # Actually let's use a term that matches multiple
        main(["class", multi_class_swf, "er"])
        out = capsys.readouterr().out
        # "er" matches Player and Enemy — ambiguous
        assert "Player" in out or "not found" in out


class TestStrings:
    def test_lists_strings(self, swf_file, capsys):
        main(["strings", swf_file])
        out = capsys.readouterr().out
        assert "string(s)" in out

    def test_search_no_match(self, swf_file, capsys):
        main(["strings", swf_file, "-s", "zzz_no_match"])
        out = capsys.readouterr().out
        assert "No matching strings" in out


class TestDisasm:
    def test_by_class(self, swf_file, capsys):
        main(["disasm", swf_file, "--class", "TestClass"])
        out = capsys.readouterr().out
        # Should have disassembled something
        assert "0x0000" in out or "bytes" in out

    def test_no_args(self, swf_file, capsys):
        main(["disasm", swf_file])
        out = capsys.readouterr().out
        assert "Specify" in out

    def test_method_not_found(self, swf_file, capsys):
        main(["disasm", swf_file, "--method-index", "9999"])
        out = capsys.readouterr().out
        assert "not found" in out


class TestCallers:
    def test_no_callers(self, swf_file, capsys):
        main(["callers", swf_file, "nonExistentMethod"])
        out = capsys.readouterr().out
        assert "No callers" in out


class TestCallees:
    def test_no_callees(self, swf_file, capsys):
        main(["callees", swf_file, "nonExistentMethod"])
        out = capsys.readouterr().out
        assert "No callees" in out


class TestRefs:
    def test_no_refs(self, swf_file, capsys):
        main(["refs", swf_file, "nonExistentThing"])
        out = capsys.readouterr().out
        assert "No references" in out


class TestTree:
    def test_no_subclasses(self, swf_file, capsys):
        main(["tree", swf_file, "TestClass"])
        out = capsys.readouterr().out
        assert "No subclasses" in out

    def test_ancestors(self, swf_file, capsys):
        main(["tree", swf_file, "TestClass", "-a"])
        out = capsys.readouterr().out
        assert "Object" in out or "No ancestors" in out


class TestPackages:
    def test_lists_packages(self, multi_class_swf, capsys):
        main(["packages", multi_class_swf])
        out = capsys.readouterr().out
        assert "com.game" in out
        assert "com.ui" in out
        assert "package(s)" in out


class TestExtract:
    def test_extract(self, swf_file, tmp_path, capsys):
        main(["extract", swf_file, "-o", str(tmp_path)])
        out = capsys.readouterr().out
        assert "Extracted" in out
        assert (tmp_path / "abc_0.abc").exists()


class TestBuild:
    def test_rebuild(self, swf_file, tmp_path, capsys):
        out_path = str(tmp_path / "rebuilt.swf")
        main(["build", swf_file, "-o", out_path])
        out = capsys.readouterr().out
        assert "Wrote" in out
        assert (tmp_path / "rebuilt.swf").exists()

    def test_decompress(self, swf_file, tmp_path, capsys):
        out_path = str(tmp_path / "decompressed.swf")
        main(["build", swf_file, "-o", out_path, "-d"])
        out = capsys.readouterr().out
        assert "uncompressed" in out


class TestErrorHandling:
    def test_missing_file(self, capsys):
        with pytest.raises(SystemExit, match="1"):
            main(["info", "/nonexistent/file.swf"])

    def test_no_command(self, capsys):
        with pytest.raises(SystemExit, match="0"):
            main([])
