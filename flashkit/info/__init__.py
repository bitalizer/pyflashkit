"""
Rich resolved model for ABC class, field, and method information.

This package resolves raw ABC constant pool indices into human-readable
names, types, and signatures.
"""

from .class_info import ClassInfo, build_class_info, build_all_classes
from .member_info import (
    FieldInfo,
    MethodInfoResolved,
    resolve_multiname,
    resolve_multiname_full,
    resolve_traits,
    build_method_body_map,
)
from .package_info import PackageInfo, group_by_package

__all__ = [
    "ClassInfo",
    "build_class_info",
    "build_all_classes",
    "FieldInfo",
    "MethodInfoResolved",
    "resolve_multiname",
    "resolve_multiname_full",
    "resolve_traits",
    "build_method_body_map",
    "PackageInfo",
    "group_by_package",
]
