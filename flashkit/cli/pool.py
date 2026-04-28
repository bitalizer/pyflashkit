"""``flashkit pool`` — dump an ABC constant pool (multinames / ints / uints / doubles)."""

from __future__ import annotations

import argparse

from ._util import load, bold, dim


_KINDS = ("multinames", "namespaces", "namespace-sets",
          "ints", "uints", "doubles")


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "pool",
        help="Dump an ABC constant pool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  flashkit pool game.swf multinames\n"
            "  flashkit pool game.swf multinames -s level\n"
            "  flashkit pool game.swf namespaces -s flash\n"
            "  flashkit pool game.swf ints"
        ),
    )
    p.add_argument("file", help="SWF or SWZ file")
    p.add_argument(
        "kind",
        choices=_KINDS,
        help="Which pool to dump",
    )
    p.add_argument("-s", "--search",
                   help="Only print entries whose resolved form "
                        "contains this substring (case-insensitive)")
    p.add_argument("--abc-index", type=int, default=0,
                   help="Index of the ABC block inside the SWF "
                        "(default: 0; use ``info`` to see how many)")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    ws = load(args.file)
    res = ws.resources[0]
    if not res.abc_blocks:
        print("No ABC blocks in this file.")
        return
    if not (0 <= args.abc_index < len(res.abc_blocks)):
        print(f"abc-index {args.abc_index} out of range "
              f"(0..{len(res.abc_blocks) - 1})")
        return
    abc = res.abc_blocks[args.abc_index]
    needle = (args.search or "").lower()

    if args.kind == "multinames":
        from ..info.member_info import resolve_multiname
        print(bold(f"Multiname pool ({len(abc.multiname_pool)} entries)"))
        for i in range(len(abc.multiname_pool)):
            try:
                name = resolve_multiname(abc, i)
            except Exception:  # noqa: BLE001 — diagnostic dump, never crash
                name = "<error>"
            if needle and needle not in name.lower():
                continue
            print(f"  [{i:5d}]  {name}")
        return

    if args.kind == "namespaces":
        print(bold(f"Namespace pool ({len(abc.namespace_pool)} entries)"))
        for i, ns in enumerate(abc.namespace_pool):
            name = abc.string_pool[ns.name] if 0 < ns.name < len(abc.string_pool) else ""
            line = f"  [{i:5d}]  kind=0x{ns.kind:02X}  {name!r}"
            if needle and needle not in line.lower():
                continue
            print(line)
        return

    if args.kind == "namespace-sets":
        print(bold(f"Namespace-set pool ({len(abc.ns_set_pool)} entries)"))
        for i, ns_set in enumerate(abc.ns_set_pool):
            line = f"  [{i:5d}]  {ns_set.namespaces}"
            if needle and needle not in line.lower():
                continue
            print(line)
        return

    pool = {
        "ints": abc.int_pool,
        "uints": abc.uint_pool,
        "doubles": abc.double_pool,
    }[args.kind]
    print(bold(f"{args.kind.title()} pool ({len(pool)} entries)"))
    for i, v in enumerate(pool):
        line = f"  [{i:5d}]  {v}"
        if needle and needle not in line.lower():
            continue
        print(line)
