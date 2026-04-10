"""``flashkit tree`` — show inheritance tree for a class."""

from __future__ import annotations

import argparse

from ._util import load, bold, green


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("tree", help="Show inheritance tree")
    p.add_argument("file", help="SWF or SWZ file")
    p.add_argument("name", help="Class name")
    p.add_argument("-a", "--ancestors", action="store_true",
                   help="Show ancestors instead of descendants")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    ws = load(args.file)
    name = args.name

    if args.ancestors:
        chain = ws.get_ancestors(name)
        if not chain:
            print(f"No ancestors for '{name}' (root or not found).")
            return
        print(bold(f"Ancestors of {name}:"))
        for i, c in enumerate(chain):
            print(f"  {'  ' * i}{c}")
        print(f"  {'  ' * len(chain)}{green(name)}")
        return

    children = ws.get_descendants(name)
    direct = ws.get_subclasses(name)

    if not children and not direct:
        print(f"No subclasses of '{name}'.")
        return

    def _print_tree(n: str, depth: int = 0) -> None:
        prefix = "  " * depth
        print(f"{prefix}{green(n) if depth == 0 else n}")
        for child in sorted(ws.get_subclasses(n)):
            _print_tree(child, depth + 1)

    _print_tree(name)
    print(f"\n{len(children)} descendant(s)")
