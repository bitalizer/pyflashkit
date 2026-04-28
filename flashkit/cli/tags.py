"""``flashkit tags`` — list all SWF tags."""

from __future__ import annotations

import argparse

from ._util import load, bold


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("tags", help="List SWF tags")
    p.add_argument("file", help="SWF or SWZ file")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    ws = load(args.file)
    res = ws.resources[0]

    if res.swf_tags is None:
        print("No SWF tags (file is SWZ format).")
        return

    print(bold(f"{'#':<6} {'Type':<8} {'Name':<35} {'Size':>10}"))
    print("-" * 62)
    for i, tag in enumerate(res.swf_tags):
        type_str = str(tag.tag_type)
        name = tag.type_name
        size = len(tag.payload)
        print(f"{i:<6} {type_str:<8} {name:<35} {size:>10}")

    print(f"\n{len(res.swf_tags)} tags total")
