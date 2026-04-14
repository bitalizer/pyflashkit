"""
String pool analysis and search.

Provides filtered views into the ABC string pool and tracks where each
string constant is used in method bodies via OP_pushstring instructions.

Usage::

    from flashkit.workspace import Workspace
    from flashkit.analysis.strings import StringIndex

    ws = Workspace()
    ws.load_swf("application.swf")
    idx = StringIndex.from_workspace(ws)

    results = idx.search("config")
    classes = idx.classes_using_string("http://")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..workspace.workspace import Workspace

from ..abc.types import AbcFile
from ..abc.disasm import scan_relevant_opcodes
from ..abc.constants import OP_pushstring, OP_debugfile
from ..info.member_info import resolve_multiname, build_method_body_map

_STRING_SCAN_OPS = frozenset({OP_pushstring, OP_debugfile})
from ..info.class_info import ClassInfo


@dataclass(slots=True)
class StringUsage:
    """A single occurrence of a string constant in bytecode.

    Attributes:
        string: The string value.
        class_name: Qualified name of the owning class.
        method_name: Method name where the string is pushed.
        method_index: Index into AbcFile.methods.
        offset: Bytecode offset of the OP_pushstring instruction.
        opcode: The opcode (OP_pushstring or OP_debugfile).
    """
    string: str
    class_name: str
    method_name: str
    method_index: int
    offset: int
    opcode: int = OP_pushstring


@dataclass(slots=True)
class StringIndex:
    """Index of string constant usage across all method bodies.

    Attributes:
        usages: All string usage entries.
        by_string: Map of string value → list of usages.
        by_class: Map of class name → list of usages.
        all_strings: Set of all unique string values found in code.
        pool_strings: Set of all strings in all string pools (superset).
    """
    usages: list[StringUsage] = field(default_factory=list)
    by_string: dict[str, list[StringUsage]] = field(
        default_factory=lambda: defaultdict(list))
    by_class: dict[str, list[StringUsage]] = field(
        default_factory=lambda: defaultdict(list))
    all_strings: set[str] = field(default_factory=set)
    pool_strings: set[str] = field(default_factory=set)

    def _add(self, usage: StringUsage) -> None:
        """Add a string usage to all indexes."""
        self.usages.append(usage)
        self.by_string[usage.string].append(usage)
        self.by_class[usage.class_name].append(usage)
        self.all_strings.add(usage.string)

    @classmethod
    def from_workspace(cls, workspace: Workspace) -> StringIndex:
        """Build a StringIndex from a Workspace.

        Walks all method bodies, decodes instructions, and collects
        OP_pushstring and OP_debugfile references.

        Args:
            workspace: A Workspace instance.

        Returns:
            Populated StringIndex.
        """
        ws = workspace

        index = cls()

        # Collect all pool strings
        for abc in ws.abc_blocks:
            for s in abc.string_pool:
                if s:
                    index.pool_strings.add(s)

        for abc in ws.abc_blocks:
            index._index_abc(abc, ws.classes)

        return index

    @classmethod
    def from_abc(cls, abc: AbcFile,
                 classes: list[ClassInfo] | None = None) -> StringIndex:
        """Build a StringIndex from a single AbcFile.

        Args:
            abc: The AbcFile to analyze.
            classes: Optional class list for method name resolution.

        Returns:
            Populated StringIndex.
        """
        index = cls()
        for s in abc.string_pool:
            if s:
                index.pool_strings.add(s)
        index._index_abc(abc, classes or [])
        return index

    def _index_abc(self, abc: AbcFile, classes: list[ClassInfo]) -> None:
        """Walk all method bodies in an AbcFile and index string usages."""
        method_owner_map = _build_method_owner_map(abc, classes)
        method_name_map = _build_method_name_map(abc, classes)
        string_pool = abc.string_pool
        string_pool_len = len(string_pool)

        for body in abc.method_bodies:
            owner_class = method_owner_map.get(body.method, "")
            method_name = method_name_map.get(
                body.method, f"method_{body.method}")

            try:
                hits = scan_relevant_opcodes(body.code, _STRING_SCAN_OPS)
            except Exception:
                continue

            for offset, op, operand in hits:
                if 0 < operand < string_pool_len:
                    self._add(StringUsage(
                        string=string_pool[operand],
                        class_name=owner_class,
                        method_name=method_name,
                        method_index=body.method,
                        offset=offset,
                        opcode=op,
                    ))

    def search(self, pattern: str, regex: bool = False) -> list[str]:
        """Search for strings matching a pattern.

        Args:
            pattern: Substring to search for, or regex if regex=True.
            regex: If True, treat pattern as a regular expression.

        Returns:
            List of matching string values (from code usage).
        """
        if regex:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error:
                return []
            return sorted(s for s in self.all_strings if compiled.search(s))
        else:
            pattern_lower = pattern.lower()
            return sorted(
                s for s in self.all_strings if pattern_lower in s.lower())

    def search_pool(self, pattern: str, regex: bool = False) -> list[str]:
        """Search all string pool entries (not just those used in code).

        Args:
            pattern: Substring or regex pattern.
            regex: If True, treat as regex.

        Returns:
            List of matching strings from the pool.
        """
        if regex:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error:
                return []
            return sorted(s for s in self.pool_strings if compiled.search(s))
        else:
            pattern_lower = pattern.lower()
            return sorted(
                s for s in self.pool_strings if pattern_lower in s.lower())

    def strings_in_class(self, class_name: str) -> list[str]:
        """Get all unique strings referenced by a class.

        Args:
            class_name: Qualified or simple class name.

        Returns:
            Sorted list of unique string values.
        """
        usages = self.by_class.get(class_name, [])
        if not usages:
            # Try simple name match
            for key, u_list in self.by_class.items():
                if key.endswith(f".{class_name}") or key == class_name:
                    usages = u_list
                    break
        return sorted(set(u.string for u in usages))

    def classes_using_string(self, string: str) -> list[str]:
        """Get all classes that reference a specific string.

        Args:
            string: The exact string value.

        Returns:
            Sorted list of unique class qualified names.
        """
        return sorted(set(
            u.class_name for u in self.by_string.get(string, [])
            if u.class_name
        ))

    def debug_markers(self) -> list[str]:
        """Find strings that look like debug source markers (e.g. ``[Foo.hx]``).

        Returns:
            Sorted list of matching strings.
        """
        return sorted(
            s for s in self.all_strings
            if s.endswith(".hx") or s.endswith(".as")
            or (s.startswith("[") and s.endswith("]"))
        )

    def url_strings(self) -> list[str]:
        """Find strings that look like URLs or file paths.

        Returns:
            Sorted list of matching strings.
        """
        return sorted(
            s for s in self.all_strings
            if s.startswith("http://") or s.startswith("https://")
            or s.startswith("file://") or s.startswith("/")
            or ".xml" in s or ".json" in s or ".swf" in s
        )

    def ui_strings(self) -> list[str]:
        """Find strings that likely represent UI labels (contain spaces, mixed case).

        Returns:
            Sorted list of matching strings.
        """
        return sorted(
            s for s in self.all_strings
            if " " in s and len(s) > 3 and not s.startswith("http")
            and not s.endswith(".hx") and not s.endswith(".as")
        )

    @property
    def unique_string_count(self) -> int:
        return len(self.all_strings)

    @property
    def total_usages(self) -> int:
        return len(self.usages)


def _build_method_owner_map(abc: AbcFile,
                            classes: list[ClassInfo]) -> dict[int, str]:
    """Map method_index → owning class qualified name."""
    owner: dict[int, str] = {}
    for ci in classes:
        owner[ci.constructor_index] = ci.qualified_name
        owner[ci.static_init_index] = ci.qualified_name
        for m in ci.all_methods:
            owner[m.method_index] = ci.qualified_name
    return owner


def _build_method_name_map(abc: AbcFile,
                           classes: list[ClassInfo]) -> dict[int, str]:
    """Map method_index → readable method name."""
    name_map: dict[int, str] = {}
    for ci in classes:
        name_map[ci.constructor_index] = "<init>"
        name_map[ci.static_init_index] = "<cinit>"
        for m in ci.all_methods:
            name_map[m.method_index] = m.name
    return name_map
