"""``flashkit callers`` — find callers of a method/property."""

from __future__ import annotations

import argparse

from ._util import load, bold, dim


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("callers", help="Find callers of a method")
    p.add_argument("file", help="SWF or SWZ file")
    p.add_argument("name", help="Method or property name")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    ws = load(args.file)
    edges = ws.callers(args.name)

    if not edges:
        print(f"No callers found for '{args.name}'.")
        return

    print(bold(f"Callers of '{args.name}'") + f"  ({len(edges)} edges)")
    for e in edges:
        print(f"  {e.caller}  {dim(e.mnemonic)}  @ 0x{e.offset:04X}")
