"""``flashkit decompile`` — decompile AVM2 bytecode to AS3 source."""

from __future__ import annotations

import argparse
import os
import sys


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "decompile",
        help="Decompile AVM2 bytecode to AS3 source",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  flashkit decompile game.swf --list\n"
            "  flashkit decompile game.swf --class PlayerManager\n"
            "  flashkit decompile game.swf --class PlayerManager --method update\n"
            "  flashkit decompile game.swf --all --outdir ./decompiled"
        ),
    )
    p.add_argument("file", help="SWF or SWZ file")
    p.add_argument("--list", action="store_true",
                   help="List all classes instead of decompiling")
    p.add_argument("--class", dest="class_name", metavar="CLASS",
                   help="Class name (short or fully-qualified) to decompile")
    p.add_argument("--method", dest="method_name", metavar="METHOD",
                   help="Method name inside --class to decompile "
                        "(requires --class)")
    p.add_argument("--all", action="store_true",
                   help="Decompile every class to --outdir")
    p.add_argument("--outdir", default="decompiled", metavar="DIR",
                   help="Output directory for --all (default: decompiled/)")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    from ..decompile import DecompilerCache, decompile_method

    cache = DecompilerCache()

    if args.list:
        classes = cache.list_classes(args.file)
        print(f"{'#':>4}  {'Class':<50} {'Super':<30}  Pkg")
        print("-" * 100)
        for c in classes:
            flag = "[I]" if c["is_interface"] else "   "
            print(f"{c['index']:4}  {flag} {c['name']:<46} "
                  f"{c['super']:<30}  {c['package']}")
        print(f"Total: {len(classes)} classes/interfaces")
        return

    if args.method_name and not args.class_name:
        print("error: --method requires --class", file=sys.stderr)
        sys.exit(2)

    if args.method_name:
        src = cache.decompile_method(
            args.file, args.class_name, args.method_name)
        print(src)
        return

    if args.class_name:
        src = cache.decompile_class(args.file, args.class_name)
        print(src)
        return

    if args.all:
        _, _, dec = cache._get_decompiler(args.file)
        outdir = args.outdir
        os.makedirs(outdir, exist_ok=True)
        count = dec.decompile_all(outdir)
        classes = dec.list_classes()
        print(f"Decompiled {count}/{len(classes)} classes to {outdir}/",
              file=sys.stderr)
        return

    # Default: show a short hint.
    classes = cache.list_classes(args.file)
    print(f"{len(classes)} classes found. "
          "Use --list, --class NAME, --class NAME --method NAME, "
          "or --all --outdir PATH.", file=sys.stderr)
