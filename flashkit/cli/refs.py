"""``flashkit refs`` — find cross-references to a name."""

from __future__ import annotations

import argparse

from ._util import load, bold, dim


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("refs", help="Find cross-references to a name")
    p.add_argument("file", help="SWF or SWZ file")
    p.add_argument("name", help="Target name")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    ws = load(args.file)
    results = ws.references_to(args.name)

    if not results:
        print(f"No references to '{args.name}'.")
        return

    print(bold(f"References to '{args.name}'") + f"  ({len(results)} refs)")
    for r in results:
        loc = f"{r.source_class}.{r.source_member}" if r.source_member else r.source_class
        print(f"  {loc}  {dim(r.ref_kind)}")
