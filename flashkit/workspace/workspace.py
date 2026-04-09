"""
Workspace: the top-level container for loaded SWF/SWZ content.

The Workspace loads one or more files, aggregates all ABC content,
and provides unified access to classes, strings, and analysis.

Usage::

    from flashkit.workspace import Workspace

    ws = Workspace()
    ws.load_swf("application.swf")
    ws.load_swz("module.swz")

    for cls in ws.classes:
        print(f"{cls.qualified_name} ({len(cls.fields)} fields)")
"""

from __future__ import annotations

from pathlib import Path

from ..abc.types import AbcFile
from ..info.class_info import ClassInfo
from ..info.package_info import PackageInfo, group_by_package
from .resource import Resource, load_swf, load_swz


class Workspace:
    """Unified workspace for analyzing SWF/SWZ content.

    Load one or more files, then query the aggregated class index.

    Attributes:
        resources: List of loaded Resource objects.
    """

    def __init__(self) -> None:
        self.resources: list[Resource] = []
        self._class_index: dict[str, ClassInfo] = {}
        self._classes: list[ClassInfo] = []
        self._packages: list[PackageInfo] | None = None

    def load_swf(self, path: str | Path) -> Resource:
        """Load a SWF file into the workspace.

        Args:
            path: Path to the SWF file.

        Returns:
            The loaded Resource.
        """
        res = load_swf(path)
        self._add_resource(res)
        return res

    def load_swz(self, path: str | Path) -> Resource:
        """Load a SWZ file into the workspace.

        Args:
            path: Path to the SWZ file.

        Returns:
            The loaded Resource.
        """
        res = load_swz(path)
        self._add_resource(res)
        return res

    def load_swf_bytes(self, data: bytes, name: str = "<memory>") -> Resource:
        """Load a SWF from raw bytes (no file needed).

        Useful for programmatically constructed SWFs or testing.

        Args:
            data: Raw SWF file bytes.
            name: Display name for the resource.

        Returns:
            The loaded Resource.
        """
        from ..swf.parser import parse_swf
        from ..swf.tags import TAG_DO_ABC, TAG_DO_ABC2
        from ..abc.parser import parse_abc
        from ..info.class_info import build_all_classes

        header, tags, version, file_length = parse_swf(data)
        abc_blocks: list[AbcFile] = []
        all_classes: list[ClassInfo] = []

        for tag in tags:
            abc_data = None
            if tag.tag_type == TAG_DO_ABC:
                abc_data = tag.payload
            elif tag.tag_type == TAG_DO_ABC2 and len(tag.payload) > 4:
                try:
                    null_idx = tag.payload.index(0, 4)
                    abc_data = tag.payload[null_idx + 1:]
                except ValueError:
                    pass

            if abc_data and len(abc_data) > 4:
                abc = parse_abc(abc_data)
                abc_blocks.append(abc)
                all_classes.extend(build_all_classes(abc))

        res = Resource(
            path=name,
            kind="swf",
            swf_header=header,
            swf_tags=tags,
            swf_version=version,
            abc_blocks=abc_blocks,
            classes=all_classes,
        )
        self._add_resource(res)
        return res

    def load(self, path: str | Path) -> Resource:
        """Load a file, auto-detecting format by extension.

        Args:
            path: Path to a SWF or SWZ file.

        Returns:
            The loaded Resource.
        """
        p = Path(path)
        if p.suffix.lower() == ".swz":
            return self.load_swz(p)
        else:
            return self.load_swf(p)

    def _add_resource(self, res: Resource) -> None:
        """Add a resource and update indexes."""
        self.resources.append(res)
        for cls in res.classes:
            self._classes.append(cls)
            # Index by both simple name and qualified name
            self._class_index[cls.name] = cls
            if cls.qualified_name != cls.name:
                self._class_index[cls.qualified_name] = cls
        self._packages = None  # invalidate cache

    @property
    def classes(self) -> list[ClassInfo]:
        """All classes across all loaded resources."""
        return self._classes

    @property
    def abc_blocks(self) -> list[AbcFile]:
        """All AbcFile objects across all loaded resources."""
        result: list[AbcFile] = []
        for res in self.resources:
            result.extend(res.abc_blocks)
        return result

    @property
    def packages(self) -> list[PackageInfo]:
        """All packages, computed from the class index."""
        if self._packages is None:
            self._packages = group_by_package(self._classes)
        return self._packages

    def get_class(self, name: str) -> ClassInfo | None:
        """Look up a class by name or qualified name.

        Args:
            name: Simple name (e.g. ``"MyClass"``) or qualified
                  (e.g. ``"com.example.MyClass"``).

        Returns:
            ClassInfo if found, None otherwise.
        """
        return self._class_index.get(name)

    def find_classes(
        self,
        *,
        name: str | None = None,
        extends: str | None = None,
        implements: str | None = None,
        package: str | None = None,
        is_interface: bool | None = None,
    ) -> list[ClassInfo]:
        """Find classes matching the given criteria.

        All criteria are AND-combined.

        Args:
            name: Substring match on class name.
            extends: Exact match on superclass name.
            implements: Exact match on one of the interface names.
            package: Exact match on package name.
            is_interface: Filter by interface flag.

        Returns:
            List of matching ClassInfo objects.
        """
        results = self._classes
        if name is not None:
            results = [c for c in results if name in c.name]
        if extends is not None:
            results = [c for c in results if c.super_name == extends]
        if implements is not None:
            results = [c for c in results if implements in c.interfaces]
        if package is not None:
            results = [c for c in results if c.package == package]
        if is_interface is not None:
            results = [c for c in results if c.is_interface == is_interface]
        return results

    @property
    def class_count(self) -> int:
        return len(self._classes)

    @property
    def interface_count(self) -> int:
        return sum(1 for c in self._classes if c.is_interface)

    def summary(self) -> str:
        """Return a human-readable summary of the workspace."""
        lines = [f"Workspace: {len(self.resources)} resource(s)"]
        for res in self.resources:
            lines.append(
                f"  {res.path}: {res.class_count} classes, "
                f"{res.method_count} methods, {res.string_count} strings")
        lines.append(
            f"Total: {self.class_count} classes, "
            f"{self.interface_count} interfaces, "
            f"{len(self.packages)} packages")
        return "\n".join(lines)
