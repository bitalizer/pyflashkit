"""Smoke test that analysis classmethods declare workspace: Workspace."""
from typing import get_type_hints

from flashkit.workspace.workspace import Workspace
from flashkit.analysis.call_graph import CallGraph
from flashkit.analysis.references import ReferenceIndex
from flashkit.analysis.strings import StringIndex
from flashkit.analysis.field_access import FieldAccessIndex
from flashkit.analysis import unified


def _resolve(func):
    return get_type_hints(func, localns={"Workspace": Workspace})


def test_call_graph_from_workspace_type():
    hints = _resolve(CallGraph.from_workspace)
    assert hints["workspace"] is Workspace


def test_reference_index_from_workspace_type():
    hints = _resolve(ReferenceIndex.from_workspace)
    assert hints["workspace"] is Workspace


def test_string_index_from_workspace_type():
    hints = _resolve(StringIndex.from_workspace)
    assert hints["workspace"] is Workspace


def test_field_access_index_from_workspace_type():
    hints = _resolve(FieldAccessIndex.from_workspace)
    assert hints["workspace"] is Workspace


def test_build_all_indexes_type():
    hints = _resolve(unified.build_all_indexes)
    assert hints["workspace"] is Workspace
