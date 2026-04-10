"""``flashkit callees`` — find calls made from a method."""

from __future__ import annotations

import argparse

from ._util import load, bold, dim


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("callees", help="Find calls from a method")
    p.add_argument("file", help="SWF or SWZ file")
    p.add_argument("name", help="Method name (e.g. Class.method)")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    ws = load(args.file)
    edges = ws.callees(args.name)

    if not edges:
        print(f"No callees found for '{args.name}'.")
        return

    print(bold(f"Callees from '{args.name}'") + f"  ({len(edges)} edges)")
    for e in edges:
        print(f"  -> {e.target}  {dim(e.mnemonic)}  @ 0x{e.offset:04X}")
