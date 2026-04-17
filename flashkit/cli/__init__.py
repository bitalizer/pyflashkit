"""
flashkit CLI — command-line interface for SWF/ABC analysis.

Structured as a package with one module per subcommand.
Entry point is :func:`main`, registered as ``flashkit`` console script.
"""

from __future__ import annotations

import argparse
import sys

from .. import __version__
from ..errors import FlashkitError
from ._util import red


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="flashkit",
        description="SWF/ABC toolkit — inspect, analyze, and manipulate Flash files.",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"flashkit {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # Import each command module — each one registers itself.
    from . import (
        info, tags, classes, class_cmd, strings,
        disasm, decompile, callers, callees, refs, tree,
        packages, extract, build, field_access, pool,
    )

    info.register(sub)
    tags.register(sub)
    classes.register(sub)
    class_cmd.register(sub)
    strings.register(sub)
    disasm.register(sub)
    decompile.register(sub)
    callers.register(sub)
    callees.register(sub)
    refs.register(sub)
    tree.register(sub)
    packages.register(sub)
    extract.register(sub)
    build.register(sub)
    field_access.register(sub)
    pool.register(sub)

    return parser


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    try:
        args.func(args)
    except FlashkitError as e:
        print(f"{red('Error')}: {e}", file=sys.stderr)
        sys.exit(1)
    except BrokenPipeError:
        pass
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
