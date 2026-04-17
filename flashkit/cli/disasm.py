"""``flashkit disasm`` — disassemble method bytecode."""

from __future__ import annotations

import argparse

from ._util import load, bold


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("disasm", help="Disassemble method bytecode")
    p.add_argument("file", help="SWF or SWZ file")
    p.add_argument("--class", dest="class_name",
                   help="Class to disassemble")
    p.add_argument("--method-index", type=int,
                   help="Method index to disassemble")
    p.add_argument("--raw", action="store_true",
                   help="Show raw pool indices instead of resolved names")
    p.set_defaults(func=run)


def _render(mb, abc, resolve: bool) -> None:
    from ..abc.disasm import decode_instructions, resolve_instructions

    instrs = decode_instructions(mb.code)
    if resolve:
        for r in resolve_instructions(abc, instrs):
            ops = ", ".join(r.operands) if r.operands else ""
            print(f"  0x{r.offset:04X}  {r.mnemonic:<24s} {ops}")
    else:
        for instr in instrs:
            ops = ", ".join(str(o) for o in instr.operands)
            print(f"  0x{instr.offset:04X}  {instr.mnemonic:<24s} {ops}")


def run(args: argparse.Namespace) -> None:
    ws = load(args.file)
    resolve = not args.raw

    if args.method_index is not None:
        for abc in ws.abc_blocks:
            for mb in abc.method_bodies:
                if mb.method == args.method_index:
                    print(bold(f"Method {mb.method}") +
                          f"  (max_stack={mb.max_stack}, "
                          f"locals={mb.local_count}, "
                          f"code={len(mb.code)} bytes)")
                    _render(mb, abc, resolve)
                    return
        print(f"Method index {args.method_index} not found.")
        return

    if args.class_name:
        cls = ws.get_class(args.class_name)
        if cls is None:
            matches = ws.find_classes(name=args.class_name)
            if len(matches) == 1:
                cls = matches[0]
            else:
                print(f"Class '{args.class_name}' not found.")
                return

        for abc in ws.abc_blocks:
            method_indices = set()
            for m in cls.all_methods:
                method_indices.add(m.method_index)
            method_indices.add(cls.constructor_index)

            for mb in abc.method_bodies:
                if mb.method in method_indices:
                    mname = f"method_{mb.method}"
                    if mb.method == cls.constructor_index:
                        mname = f"{cls.name}()"
                    else:
                        for m in cls.all_methods:
                            if m.method_index == mb.method:
                                mname = m.name
                                break

                    print(bold(f"{cls.name}.{mname}") +
                          f"  ({len(mb.code)} bytes)")
                    _render(mb, abc, resolve)
                    print()
        return

    print("Specify --class or --method-index.")
