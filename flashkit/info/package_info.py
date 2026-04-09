"""
Package grouping for ABC classes.

Groups ``ClassInfo`` objects by their namespace (package name),
providing a tree-like view of the class hierarchy similar to what
a class explorer UI would show.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .class_info import ClassInfo


@dataclass
class PackageInfo:
    """A package containing one or more classes.

    Attributes:
        name: Full package name (e.g. ``"flash.display"``), empty for default.
        classes: List of ClassInfo in this package.
    """
    name: str
    classes: list[ClassInfo] = field(default_factory=list)

    @property
    def class_count(self) -> int:
        return len(self.classes)

    def get_class(self, name: str) -> ClassInfo | None:
        """Find a class by simple name within this package."""
        for cls in self.classes:
            if cls.name == name:
                return cls
        return None


def group_by_package(classes: list[ClassInfo]) -> list[PackageInfo]:
    """Group a list of ClassInfo objects by package name.

    Args:
        classes: List of ClassInfo to group.

    Returns:
        List of PackageInfo, sorted by package name.
    """
    by_package: dict[str, list[ClassInfo]] = defaultdict(list)
    for cls in classes:
        by_package[cls.package].append(cls)

    result = []
    for pkg_name in sorted(by_package.keys()):
        pkg = PackageInfo(
            name=pkg_name,
            classes=sorted(by_package[pkg_name], key=lambda c: c.name),
        )
        result.append(pkg)
    return result
