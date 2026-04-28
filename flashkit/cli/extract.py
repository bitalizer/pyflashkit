"""``flashkit extract`` — extract ABC bytecode from a SWF."""

from __future__ import annotations

import argparse
from pathlib import Path

from ._util import load


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "extract",
        help="Extract ABC blocks from SWF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  flashkit extract game.swf\n"
            "  flashkit extract game.swf -o ./abc_dump"
        ),
    )
    p.add_argument("file", help="SWF or SWZ file")
    p.add_argument("-o", "--output", help="Output directory")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    ws = load(args.file)
    res = ws.resources[0]
    out_dir = Path(args.output) if args.output else Path(".")

    if not res.abc_blocks:
        print("No ABC blocks found.")
        return

    from ..abc.writer import serialize_abc

    for i, abc in enumerate(res.abc_blocks):
        raw = serialize_abc(abc)
        name = f"abc_{i}.abc"
        dest = out_dir / name
        dest.write_bytes(raw)
        print(f"  Wrote {dest} ({len(raw)} bytes)")

    print(f"\nExtracted {len(res.abc_blocks)} ABC block(s)")
