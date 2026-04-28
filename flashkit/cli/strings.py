"""``flashkit strings`` — list or search string constants."""

from __future__ import annotations

import argparse

from ._util import load, bold, dim, green


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "strings",
        help="List or search strings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  flashkit strings game.swf\n"
            "  flashkit strings game.swf -s config\n"
            "  flashkit strings game.swf -s config -v\n"
            "  flashkit strings game.swf -s '\\d+' -r\n"
            "  flashkit strings game.swf -c"
        ),
    )
    p.add_argument("file", help="SWF or SWZ file")
    p.add_argument("-s", "--search", help="Search term")
    p.add_argument("-r", "--regex", action="store_true",
                   help="Treat search term as regex")
    p.add_argument("-c", "--classify", action="store_true",
                   help="Classify strings (URLs, debug markers)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Show usage locations")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    ws = load(args.file)

    if args.search:
        matches = ws.search_strings(args.search, regex=args.regex)
        if not matches:
            print("No matching strings.")
            return

        for s in matches:
            print(f"  {green(repr(s))}")
            if args.verbose:
                classes = ws.classes_using_string(s)
                for cls_name in classes:
                    print(f"    used in {dim(cls_name)}")
        print(f"\n{len(matches)} unique string(s)")
    else:
        all_strings = sorted(ws.all_strings)
        if args.classify:
            urls = ws.url_strings()
            files = ws.debug_markers()
            print(bold("URLs:"))
            for s in urls:
                print(f"  {s}")
            print(f"\n{bold('Debug markers:')}")
            for s in files:
                print(f"  {s}")
            print(f"\n{len(urls)} URL(s), {len(files)} debug marker(s), "
                  f"{len(all_strings)} total strings")
        else:
            for s in all_strings:
                if s:
                    print(f"  {s}")
            print(f"\n{len(all_strings)} string(s)")
