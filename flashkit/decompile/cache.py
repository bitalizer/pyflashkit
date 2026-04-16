"""
Caching layer for per-SWF decompilation.

Parsing an ABC block is cheap; the decompiler internally caches method
dispatch tables and type-resolution results. :class:`DecompilerCache`
memoizes parsed AbcFile + AS3Decompiler pairs keyed by SWF path and
mtime, so repeated class lookups on the same SWF skip the parse step.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from ..swf.parser import parse_swf
from ..swf.tags import TAG_DO_ABC, TAG_DO_ABC2
from ..abc.parser import parse_abc
from ._adapter import AbcView


def _extract_first_abc_block(swf_path: str | os.PathLike) -> bytes:
    """Read a SWF file, locate its first DoABC/DoABC2 tag, return ABC bytes."""
    with open(swf_path, "rb") as f:
        swf_bytes = f.read()
    _, tags, _, _ = parse_swf(swf_bytes)
    for tag in tags:
        if tag.tag_type == TAG_DO_ABC2:
            payload = tag.payload
            # Skip flags (u32 LE) + null-terminated name.
            p = 4
            while p < len(payload) and payload[p] != 0:
                p += 1
            return payload[p + 1:]
        if tag.tag_type == TAG_DO_ABC:
            return tag.payload
    raise ValueError(f"No DoABC/DoABC2 tag found in {swf_path}")


class DecompilerCache:
    """Memoizes parsed AbcFile + decompiler per SWF path.

    Cache key is ``(abspath, mtime)`` so a modified SWF is re-parsed.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[str, float], tuple] = {}

    def _get_decompiler(self, swf_path: str | os.PathLike):
        from .class_ import AS3Decompiler
        path = str(Path(swf_path).resolve())
        mtime = os.path.getmtime(path)
        key = (path, mtime)
        entry = self._entries.get(key)
        if entry is not None:
            return entry
        abc_bytes = _extract_first_abc_block(path)
        abc = parse_abc(abc_bytes)
        view = AbcView(abc)
        dec = AS3Decompiler(view)
        self._entries[key] = (abc, view, dec)
        return abc, view, dec

    def decompile_class(self, swf_path: str | os.PathLike, name: str) -> str:
        """Decompile a class (by name or fully-qualified name) from a SWF."""
        _, _, dec = self._get_decompiler(swf_path)
        for c in dec.list_classes():
            if c["name"] == name or c["full_name"] == name:
                return dec.decompile_class(c["index"])
        raise KeyError(f"Class {name!r} not found in {swf_path}")

    def decompile_method(
        self,
        swf_path: str | os.PathLike,
        class_name: str,
        method_name: str,
    ) -> str:
        """Decompile one method by (class_name, method_name) from a SWF.

        Returns the method signature + body, e.g.::

            public function update(dt:Number):void { ... }
        """
        from .class_ import AS3Decompiler
        _, view, dec = self._get_decompiler(swf_path)

        # Find the class index.
        class_idx = -1
        for c in dec.list_classes():
            if c["name"] == class_name or c["full_name"] == class_name:
                class_idx = c["index"]
                break
        if class_idx < 0:
            raise KeyError(f"Class {class_name!r} not found in {swf_path}")

        inst = view.instances[class_idx]
        # Find the method trait by name.
        for t in list(inst.traits) + list(view.classes[class_idx].traits):
            if view.mn_name(t.name_idx) == method_name and t.method_idx:
                from .method import MethodDecompiler
                md = MethodDecompiler(view)
                body = md.decompile(t.method_idx, class_idx=class_idx)
                return body
        raise KeyError(
            f"Method {method_name!r} not found on class {class_name!r}")

    def list_classes(self, swf_path: str | os.PathLike) -> list[dict]:
        """List classes in the SWF's first ABC block."""
        _, _, dec = self._get_decompiler(swf_path)
        return dec.list_classes()
