"""``flashkit fields`` — show field read/write access patterns."""

from __future__ import annotations

import argparse

from ._util import load, bold, dim, cyan


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "fields",
        help="Show field read/write access patterns for a class",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  flashkit fields game.swf PlayerManager\n"
            "  flashkit fields game.swf PlayerManager -f mHealth\n"
            "  flashkit fields game.swf PlayerManager -m takeDamage\n"
            "  flashkit fields game.swf PlayerManager -c"
        ),
    )
    p.add_argument("file", help="SWF or SWZ file")
    p.add_argument("name", help="Class name")
    p.add_argument("--field", "-f", metavar="NAME",
                   help="Show access for a specific field")
    p.add_argument("--method", "-m", metavar="NAME",
                   help="Show fields accessed by a specific method")
    p.add_argument("--constructor", "-c", action="store_true",
                   help="Show constructor field assignments")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    ws = load(args.file)

    if args.constructor:
        _show_constructor(ws, args.name)
    elif args.field:
        _show_field(ws, args.name, args.field)
    elif args.method:
        _show_method(ws, args.name, args.method)
    else:
        _show_summary(ws, args.name)


def _show_constructor(ws, class_name: str) -> None:
    assignments = ws.constructor_assignments(class_name)
    reads = ws.constructor_reads(class_name)
    if not assignments and not reads:
        print(f"No constructor field accesses found for '{class_name}'.")
        return
    print(bold(f"Constructor of '{class_name}'"))
    if assignments:
        print(f"\n  Assignments ({len(assignments)}):")
        for f in assignments:
            print(f"    {f}")
    if reads:
        print(f"\n  Reads ({len(reads)}):")
        for f in reads:
            print(f"    {f}")


def _show_field(ws, class_name: str, field_name: str) -> None:
    readers = ws.field_readers(class_name, field_name)
    writers = ws.field_writers(class_name, field_name)
    count = ws.field_access_count(class_name, field_name)
    if not readers and not writers:
        print(f"No accesses found for '{class_name}.{field_name}'.")
        return
    print(bold(f"Field '{class_name}.{field_name}'")
          + f"  ({count} total accesses)")
    if writers:
        print(f"\n  Writers ({len(writers)}):")
        for m in writers:
            print(f"    {m}")
    if readers:
        print(f"\n  Readers ({len(readers)}):")
        for m in readers:
            print(f"    {m}")


def _show_method(ws, class_name: str, method_name: str) -> None:
    read = ws.fields_read_by(class_name, method_name)
    written = ws.fields_written_by(class_name, method_name)
    if not read and not written:
        print(f"No field accesses found in '{class_name}.{method_name}'.")
        return
    print(bold(f"Method '{class_name}.{method_name}'"))
    if written:
        print(f"\n  Writes ({len(written)}):")
        for f in written:
            print(f"    {f}")
    if read:
        print(f"\n  Reads ({len(read)}):")
        for f in read:
            print(f"    {f}")


def _show_summary(ws, class_name: str) -> None:
    summary = ws.field_access_summary(class_name)
    if not summary:
        print(f"No field accesses found for '{class_name}'.")
        return
    print(bold(f"Field access summary for '{class_name}'")
          + f"  ({len(summary)} fields)")
    for field_name in sorted(summary.keys()):
        info = summary[field_name]
        r_count = len(info["readers"])
        w_count = len(info["writers"])
        print(f"  {field_name:30s}  "
              f"{cyan(f'{r_count}R')} / {cyan(f'{w_count}W')}")
