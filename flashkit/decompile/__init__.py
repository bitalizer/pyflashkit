"""
AS3 decompilation — convert AVM2 bytecode back into ActionScript 3 source.

The decompiler consumes a parsed :class:`~flashkit.abc.types.AbcFile` and
produces readable AS3 source at three granularities:

- :func:`decompile_method_body` — just the body of one method.
- :func:`decompile_method` — method signature + body.
- :func:`decompile_class` — full ``package { class { ... } }`` source.

All entry points accept either a parsed ``AbcFile`` or a
:class:`~flashkit.workspace.Workspace`. Classes are identified by index
or by name. Use :class:`DecompilerCache` to decompile multiple classes /
methods from the same SWF without re-parsing.

The decompiler is a heavy import. It is lazy-loaded via module
``__getattr__`` so ``import flashkit`` stays fast for callers that never
decompile anything.

Usage::

    from flashkit import parse_abc
    from flashkit.decompile import decompile_class, decompile_method

    abc = parse_abc(abc_bytes)

    src = decompile_class(abc, name="com.game.Player")
    src = decompile_method(abc, class_name="com.game.Player", name="update")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:
    from ..abc.types import AbcFile
    from ..workspace.workspace import Workspace
    from .cache import DecompilerCache


__all__ = [
    "decompile_method",
    "decompile_method_body",
    "decompile_class",
    "list_classes",
    "ClassSummary",
    "DecompilerCache",
]


from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClassSummary:
    """One row of metadata about a class inside a parsed ABC.

    Returned by :func:`list_classes`. Supports dict-style subscript
    (``c["name"]``) for backwards compatibility with code written
    before the typed row existed.
    """
    index: int
    name: str
    package: str
    full_name: str
    super: str
    is_interface: bool
    trait_count: int

    def __getitem__(self, key: str):
        try:
            return getattr(self, key)
        except AttributeError as exc:
            raise KeyError(key) from exc

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self) -> tuple[str, ...]:
        return ("index", "name", "package", "full_name",
                "super", "is_interface", "trait_count")


# ── Internal ───────────────────────────────────────────────────────────────

def _resolve_abc(source) -> tuple:
    """Normalize a source into an (AbcView, AS3Decompiler) pair.

    ``source`` may be:
      * a parsed :class:`AbcFile`
      * a :class:`Workspace` (uses its first loaded resource's ABC)
      * already an ``AbcView`` (internal use)
    """
    from ._adapter import AbcView
    from .class_ import AS3Decompiler
    from ..abc.types import AbcFile

    # Workspace: grab its first resource's first ABC block.
    workspace_cls = None
    try:
        from ..workspace.workspace import Workspace
        workspace_cls = Workspace
    except ImportError:
        pass

    if isinstance(source, AbcView):
        view = source
    elif isinstance(source, AbcFile):
        view = AbcView(source)
    elif workspace_cls is not None and isinstance(source, workspace_cls):
        for resource in source.resources.values():
            if resource.abc_files:
                view = AbcView(resource.abc_files[0])
                break
        else:
            raise ValueError(
                "Workspace has no loaded ABC; call .load_swf() first")
    else:
        raise TypeError(
            f"Expected AbcFile or Workspace, got {type(source).__name__}")

    return view, AS3Decompiler(view)


def _find_class_index(dec, class_index: Optional[int], name: Optional[str]) -> int:
    if class_index is not None:
        return class_index
    if name is None:
        raise ValueError("Pass either class_index or name")
    matches_full: list[int] = []
    matches_short: list[int] = []
    for c in dec.list_classes():
        if c["full_name"] == name:
            matches_full.append(c["index"])
        elif c["name"] == name:
            matches_short.append(c["index"])
    if matches_full:
        return matches_full[0]
    if len(matches_short) == 1:
        return matches_short[0]
    if len(matches_short) > 1:
        raise ValueError(
            f"Class name {name!r} is ambiguous; "
            f"pass the fully-qualified name (e.g. com.pkg.{name})")
    raise KeyError(f"Class not found: {name!r}")


# ── Public API ─────────────────────────────────────────────────────────────

def list_classes(source) -> list[ClassSummary]:
    """Return one :class:`ClassSummary` per class in the ABC.

    The rows are plain dataclasses — access fields as attributes
    (``c.name``) or, for backwards compatibility with pre-1.3 code,
    as dict keys (``c["name"]``). Supported keys match the
    ``ClassSummary`` field names: ``index``, ``name``, ``package``,
    ``full_name``, ``super``, ``is_interface``, ``trait_count``.
    """
    _, dec = _resolve_abc(source)
    return dec.list_classes()


def decompile_class(
    source,
    class_index: Optional[int] = None,
    name: Optional[str] = None,
) -> str:
    """Decompile one class to full AS3 source (package + class block).

    Args:
        source: An ``AbcFile`` or ``Workspace``.
        class_index: Index into ``AbcFile.instances``.
        name: Short or fully-qualified class name (alternative to index).

    Returns:
        AS3 source as a string.
    """
    _, dec = _resolve_abc(source)
    idx = _find_class_index(dec, class_index, name)
    return dec.decompile_class(idx)


def decompile_method(
    source,
    class_index: Optional[int] = None,
    class_name: Optional[str] = None,
    method_idx: Optional[int] = None,
    name: Optional[str] = None,
    include_signature: bool = True,
) -> str:
    """Decompile a single method.

    Supply either ``method_idx`` (AVM2 method table index) or a
    ``(class_index|class_name, name)`` pair to find it by member name.

    Args:
        include_signature: If True, wrap the body with the method signature
            (e.g. ``public function update(dt:Number):void { ... }``).
            If False, returns just the body.
    """
    view, dec = _resolve_abc(source)
    from .method import MethodDecompiler

    resolved_class_idx = -1
    if class_index is not None or class_name is not None:
        resolved_class_idx = _find_class_index(dec, class_index, class_name)

    if method_idx is None:
        if resolved_class_idx < 0 or name is None:
            raise ValueError(
                "Pass method_idx, or (class_index|class_name + name)")
        inst = view.instances[resolved_class_idx]
        cls = view.classes[resolved_class_idx]
        found = None
        for t in list(inst.traits) + list(cls.traits):
            if view.mn_name(t.name_idx) == name and t.method_idx:
                found = t.method_idx
                break
        if found is None:
            raise KeyError(
                f"Method {name!r} not found on class index {resolved_class_idx}")
        method_idx = found

    md = MethodDecompiler(view)
    body = md.decompile(method_idx, class_idx=resolved_class_idx)
    if include_signature:
        # Wrap body with function signature derived from MethodInfo.
        m = view.methods[method_idx]
        ret = view.type_name(m.return_type)
        # Prefer real parameter names from the MethodInfo debug table
        # (set when the METHOD_HAS_PARAM_NAMES flag is present); fall
        # back to the AVM2 ``_arg_N`` convention only when the slot
        # is missing or resolves to an empty string.
        raw_abc = getattr(view, "_abc", view)
        raw_names: list[str] = []
        for pn in (getattr(m, "param_names", None) or []):
            if 0 < pn < len(raw_abc.string_pool):
                raw_names.append(raw_abc.string_pool[pn])
            else:
                raw_names.append("")
        param_parts: list[str] = []
        for i, pt in enumerate(m.param_types):
            label = raw_names[i] if i < len(raw_names) and raw_names[i] else f"_arg_{i + 1}"
            param_parts.append(f"{label}:{view.type_name(pt)}")
        sig = f"function {name or 'method_' + str(method_idx)}({', '.join(param_parts)}):{ret}"
        return f"{sig}\n{body}"
    return body


def decompile_method_body(
    source,
    method_idx: int,
) -> str:
    """Decompile just the body of a method (no signature wrapper).

    Args:
        source: An ``AbcFile`` or ``Workspace``.
        method_idx: Index into ``AbcFile.methods``.
    """
    return decompile_method(source, method_idx=method_idx, include_signature=False)


def __getattr__(name: str):
    if name == "DecompilerCache":
        from .cache import DecompilerCache
        return DecompilerCache
    raise AttributeError(f"module 'flashkit.decompile' has no attribute {name!r}")
