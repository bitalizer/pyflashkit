"""Sanity tests for the flashkit public API surface."""
import importlib
import pytest


@pytest.mark.parametrize("module_path", [
    "flashkit",
    "flashkit.abc",
    "flashkit.analysis",
    "flashkit.info",
    "flashkit.swf",
    "flashkit.workspace",
])
def test_all_names_resolve(module_path):
    """Every name in __all__ must be importable from the module."""
    mod = importlib.import_module(module_path)
    for name in getattr(mod, "__all__", []):
        assert hasattr(mod, name), (
            f"{module_path}.__all__ lists {name!r} but module has no such attribute")


def test_version_is_1_2_0():
    import flashkit
    assert flashkit.__version__ == "1.2.0"


def test_workspace_exported():
    from flashkit import Workspace
    assert Workspace is not None


def test_classinfo_exported():
    from flashkit import ClassInfo
    assert ClassInfo is not None


def test_build_class_graph_removed():
    """build_class_graph was removed in 1.2.0."""
    import flashkit.analysis
    assert not hasattr(flashkit.analysis, "build_class_graph"), (
        "build_class_graph should have been removed in 1.2.0")
