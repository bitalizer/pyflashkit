"""``flashkit classes`` — list all classes with optional filters."""

from __future__ import annotations

import argparse

from ._util import load, bold, dim, cyan, green


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "classes",
        help="List classes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  flashkit classes game.swf\n"
            "  flashkit classes game.swf -s Manager\n"
            "  flashkit classes game.swf -p com.game\n"
            "  flashkit classes game.swf -e Sprite\n"
            "  flashkit classes game.swf -i"
        ),
    )
    p.add_argument("file", help="SWF or SWZ file")
    p.add_argument("-s", "--search", help="Filter by name substring")
    p.add_argument("-p", "--package", help="Filter by package")
    p.add_argument("-e", "--extends", help="Filter by superclass")
    p.add_argument("-i", "--interfaces-only", action="store_true",
                   help="Show only interfaces")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Show detailed info per class")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    ws = load(args.file)
    classes = ws.classes

    if args.package:
        classes = [c for c in classes if c.package == args.package]
    if args.extends:
        classes = [c for c in classes if c.super_name == args.extends]
    if args.interfaces_only:
        classes = [c for c in classes if c.is_interface]
    if args.search:
        term = args.search.lower()
        classes = [c for c in classes if term in c.qualified_name.lower()]

    if not classes:
        print("No classes found.")
        return

    if args.verbose:
        for cls in classes:
            flags = []
            if cls.is_interface:
                flags.append("interface")
            if cls.is_final:
                flags.append("final")
            if cls.is_sealed:
                flags.append("sealed")
            flag_str = f" [{', '.join(flags)}]" if flags else ""

            print(bold(cls.qualified_name) + dim(flag_str))
            print(f"  extends {cyan(cls.super_name)}")
            if cls.interfaces:
                print(f"  implements {', '.join(green(i) for i in cls.interfaces)}")
            print(f"  {len(cls.fields)} fields, {len(cls.methods)} methods"
                  f", {len(cls.static_fields)} static fields"
                  f", {len(cls.static_methods)} static methods")
            print()
    else:
        print(bold(f"{'Class':<50} {'Super':<25} {'Fields':>6} {'Methods':>7}"))
        print("-" * 92)
        for cls in classes:
            name = cls.qualified_name
            prefix = ""
            if cls.is_interface:
                prefix = dim("[I] ")
            print(f"{prefix}{name:<50} {cls.super_name:<25} "
                  f"{len(cls.all_fields):>6} {len(cls.all_methods):>7}")

    print(f"\n{len(classes)} class(es)")
