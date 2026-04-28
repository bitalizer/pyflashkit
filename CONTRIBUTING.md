# Contributing to flashkit

## Setup

```bash
git clone <repo-url>
cd flashkit
pip install -e ".[dev]"
```

## Running tests

```bash
python -m pytest
python -m pytest -v              # verbose
python -m pytest tests/cli/      # just CLI tests
python -m pytest -k "roundtrip"  # filter by name
```

Real-SWF tests are opt-in via `FLASHKIT_TEST_SWF`. They never ship a
binary fixture in-repo; point the env var at a local file you have
on disk:

```bash
FLASHKIT_TEST_SWF=/path/to/your.swf python -m pytest
```

Coverage:

```bash
python -m pytest --cov=flashkit --cov-report=term-missing
```

## Project layout

```
flashkit/
  cli/           CLI commands (one file per subcommand)
  swf/           SWF container format
  abc/           AVM2 bytecode parsing, writing, disassembly, builder
  info/          Resolved class/field/method model
  workspace/     File loading, resource management
  analysis/      Inheritance, call graph, references, strings,
                 field access, method fingerprints, class graph,
                 liveness, const-args, dead code, complexity
  decompile/     CFG-based AS3 decompiler (method + class)
  graph/         CFG, dominators, loop detection (used by decompiler)
  errors.py      Error hierarchy

tests/
  abc/           ABC parser, writer, builder, disasm tests
  swf/           SWF parser and builder tests
  info/          ClassInfo resolution tests
  workspace/     Workspace loading tests
  analysis/      Analysis module tests
  decompile/     Decompiler structuring + cache tests
  graph/         CFG / dominators / loops tests
  cli/           CLI integration tests
  conftest.py    Shared fixtures (build_abc_bytes, build_swf_bytes)
```

## Writing tests

All tests use programmatically built SWFs via `AbcBuilder` and `SwfBuilder` — no real `.swf` fixture files. This keeps the repo clean and tests fast.

```python
from flashkit.abc.builder import AbcBuilder
from flashkit.abc.writer import serialize_abc
from flashkit.swf.builder import SwfBuilder

b = AbcBuilder()
b.simple_class("Player", package="com.game", fields=[("hp", "int")])
b.script()
abc_bytes = serialize_abc(b.build())

swf = SwfBuilder(version=40, width=800, height=600, fps=30)
swf.add_abc("TestCode", abc_bytes)
swf_bytes = swf.build()
```

## Adding a CLI command

1. Create `flashkit/cli/mycommand.py`:

```python
"""``flashkit mycommand`` — description."""

from __future__ import annotations
import argparse
from ._util import load, bold

def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("mycommand", help="Short help text")
    p.add_argument("file", help="SWF or SWZ file")
    p.set_defaults(func=run)

def run(args: argparse.Namespace) -> None:
    ws = load(args.file)
    # ...
```

2. Import and register it in `flashkit/cli/__init__.py`:

```python
from . import mycommand
mycommand.register(sub)
```

3. Add tests in `tests/cli/test_cli.py`.

## Pull requests

1. Fork the repo and create a branch from `main`.
2. If you added code, add tests. Run `python -m pytest` and make sure everything passes.
3. Keep PRs focused — one feature or fix per PR.
4. Use conventional commit messages for the PR title (`feat: add xyz`, `fix: handle edge case`).
5. Describe **what** changed and **why** in the PR body. If it's a fix, link the issue.
6. Make sure there are no type errors or lint warnings in the code you changed.

## Conventions

- **Zero dependencies.** Standard library only. No Click, no Rich, no Typer.
- **Round-trip fidelity.** `serialize(parse(data)) == data` must hold for unmodified ABC.
- **Conventional commits.** `feat:`, `fix:`, `test:`, `docs:`, `chore:`.
- **Type hints everywhere.** All public functions and methods must have type annotations.
- **No fixture files.** Tests build SWFs programmatically via `AbcBuilder` / `SwfBuilder`.
- **One command per file.** CLI commands live in `flashkit/cli/`, one module each.
- **Errors over silent failures.** Raise specific `FlashkitError` subclasses, never return `None` to signal failure in parsing code.

## Error handling

All public errors inherit from `FlashkitError`:

```
FlashkitError
  ParseError
    SWFParseError
    ABCParseError
  SerializeError
  ResourceError
```

The CLI catches `FlashkitError` at the top level and prints a clean message. Don't let raw exceptions reach the user.
