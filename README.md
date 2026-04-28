# flashkit

Parse, analyze, decompile, and rebuild Adobe Flash SWF files and AVM2 bytecode.

flashkit is a pure-Python toolkit for working with the SWF container format and the AVM2 bytecode that runs ActionScript 3. It covers everything from low-level pool surgery to full AS3 source recovery, with a CLI for one-off questions and a programmatic API for building tools on top.

## Install

```bash
pip install pyflashkit
```

Or from source:

```bash
git clone https://github.com/bitalizer/pyflashkit.git
cd pyflashkit
pip install -e .[dev]   # ``[dev]`` adds pytest + pytest-cov
```

Python 3.10+. No runtime dependencies.

## Quick start

```python
from flashkit.workspace import Workspace
from flashkit.decompile import decompile_class

ws = Workspace()
ws.load_swf("application.swf")

# Inspect a class
player = ws.get_class("PlayerManager")
print(player.super_name)        # "EventDispatcher"
print(player.fields[0].name, player.fields[0].type_name)

# Find every class extending Sprite
for cls in ws.find_classes(extends="Sprite"):
    print(cls.qualified_name)

# Recover AS3 source from bytecode
print(decompile_class(ws, name="PlayerManager"))
```

---

## Features

- **SWF container** — parse, build, and round-trip every standard tag.
- **AVM2 bytecode** — parse to typed dataclasses, modify, write back with byte-perfect fidelity.
- **AS3 decompiler** — CFG-based pipeline (basic blocks → dominators → loop nesting → stack simulation → structuring → idiom rewrites → AS3 source). Cross-block dataflow handles conditionals whose operands cross block boundaries.
- **Disassembler** — raw and resolved instruction views.
- **Workspace** — multi-SWF loading with cached cross-reference, string, field-access, inheritance, and call-graph indexes built in a single bytecode scan.
- **Analysis layer** — register liveness, constant-argument inference at call sites, dead-class / dead-method detection, entry-point candidates, McCabe cyclomatic complexity.
- **CLI** — `flashkit info / classes / class / strings / disasm / decompile / pool / tree / refs / callers / callees / fields / packages / extract / build`.

---

## CLI

### `flashkit info`

```
$ flashkit info application.swf
File: application.swf
  Format:     SWF
  SWF version: 40
  Tags:       142
  ABC blocks: 1
  Classes:    823
  Methods:    14210
  Strings:    35482
  Packages:   47
```

### `flashkit decompile`

```bash
flashkit decompile app.swf --list                       # list classes
flashkit decompile app.swf --class PlayerManager        # AS3 source for one class
flashkit decompile app.swf --class PlayerManager \
                          --method takeDamage           # one method
flashkit decompile app.swf --all --outdir decompiled/   # whole SWF to disk
```

### `flashkit disasm`

```bash
flashkit disasm app.swf --class PlayerManager
flashkit disasm app.swf --method-index 42
flashkit disasm app.swf --class Foo --raw   # raw pool indices instead of names
```

Operands are resolved by default — `getlex DevSettings`, `pushstring "noScale"`, `setproperty scaleMode` — so output reads next to AS3 source. Use `--raw` for pool-index debugging.

### `flashkit pool`

Inspect any ABC constant pool.

```bash
flashkit pool app.swf multinames
flashkit pool app.swf strings -s "level"
flashkit pool app.swf namespaces -s flash
flashkit pool app.swf ints
flashkit pool app.swf doubles
flashkit pool app.swf namespace-sets
```

### `flashkit class`

```
$ flashkit class application.swf PlayerManager
PlayerManager
  Package: com.game
  Extends: EventDispatcher
  Implements: IDisposable, ITickable

  Instance Fields (3)
    mHealth: Number
    mName: String
    mLevel: int

  Instance Methods (5)
    init(): void
    get name(): String
    set name(value: String): void
    takeDamage(amount: Number): void
    serialize(): ByteArray
```

### `flashkit classes`

```bash
flashkit classes app.swf                # all classes
flashkit classes app.swf -s Manager     # search by name
flashkit classes app.swf -p com.game    # filter by package
flashkit classes app.swf -e Sprite      # filter by superclass
flashkit classes app.swf -i             # interfaces only
flashkit classes app.swf -v             # verbose output
```

### `flashkit strings`

```bash
flashkit strings app.swf                # list all
flashkit strings app.swf -s config      # search
flashkit strings app.swf -s config -v   # with usage locations
flashkit strings app.swf -s "\\d+" -r   # regex
flashkit strings app.swf -c             # classify (URLs, debug)
```

### `flashkit tree` / `refs` / `callers` / `callees` / `fields`

```bash
flashkit tree app.swf BaseEntity                    # show descendants
flashkit tree app.swf PlayerManager -a              # show ancestors
flashkit refs app.swf Point                         # all references to a name
flashkit callers app.swf toString                   # call graph: who calls X
flashkit callees app.swf PlayerManager.init         # call graph: what X calls
flashkit fields app.swf PlayerManager               # field R/W summary
flashkit fields app.swf PlayerManager -f mHealth    # readers/writers of one field
flashkit fields app.swf PlayerManager -m takeDamage # what fields a method touches
```

### `flashkit packages` / `extract` / `build` / `tags`

```bash
flashkit tags app.swf                         # list raw SWF tags
flashkit packages app.swf                     # list packages
flashkit extract app.swf -o ./output          # extract ABC blocks to disk
flashkit build app.swf -o rebuilt.swf         # rebuild (compressed)
flashkit build app.swf -o out.swf -d          # rebuild (decompressed)
```

---

## Library

### Workspace — load and query

```python
from flashkit.workspace import Workspace

ws = Workspace()
ws.load_swf("application.swf")
ws.load_swz("module.swz")

print(ws.summary())

cls = ws.get_class("MyClass")
print(cls.name, cls.super_name, cls.interfaces)
print(cls.fields)   # list of FieldInfo
print(cls.methods)  # list of MethodInfoResolved

ws.find_classes(extends="Sprite")
ws.find_classes(package="com.example", is_interface=True)
```

### Decompiler

Three granularities, all accept either a `Workspace` or a parsed `AbcFile`:

```python
from flashkit.decompile import (
    decompile_class, decompile_method, decompile_method_body,
    list_classes, ClassSummary, DecompilerCache,
)

src = decompile_class(ws, name="com.game.Player")
src = decompile_method(ws, class_name="com.game.Player", name="update")

# Typed metadata rows (also accept dict-style ``c["name"]`` for legacy code)
for c in list_classes(ws):
    print(c.full_name, c.trait_count)

# Cache parses + decompilers across many lookups on the same SWF
cache = DecompilerCache()
cache.list_classes("game.swf")
cache.decompile_class("game.swf", "Player")
cache.decompile_method("game.swf", "Player", "update")
```

### Analysis

All indexes are built lazily on first access and cached on the workspace. One bytecode scan populates strings, references, and field access together.

```python
# Inheritance
ws.get_subclasses("BaseEntity")
ws.get_descendants("BaseEntity")       # transitive
ws.get_ancestors("PlayerManager")
ws.get_implementors("ISerializable")

# Call graph
ws.callers("toString")
ws.callees("PlayerManager.init")

# References
ws.references_to("Point")
ws.references_from("PlayerManager")
ws.find_instantiators("Point")
ws.find_type_users("ByteArray")

# Strings
ws.search_strings("config")
ws.classes_using_string("http://example.com")
ws.strings_in_class("PlayerManager")

# Field access
ws.field_writers("PlayerManager", "mHealth")
ws.field_readers("PlayerManager", "mHealth")
ws.fields_written_by("PlayerManager", "takeDamage")
ws.fields_read_by("PlayerManager", "takeDamage")
ws.constructor_assignments("PlayerManager")
ws.field_access_summary("PlayerManager")

# Structural
ws.find_classes_with_field_type("ByteArray")
ws.find_methods(return_type="String", name="get")
ws.find_fields(type_name="int")
```

### Deeper analysis

```python
from flashkit.analysis import (
    method_liveness, ConstArgIndex,
    find_dead_classes, find_dead_methods, entrypoint_candidates,
    method_complexity,
)

# Per-method register liveness — useful for ``_loc3_`` rename heuristics
abc = ws.abc_blocks[0]
liv = method_liveness(abc, abc.method_bodies[0])
print(liv.read_counts, liv.write_counts)

# Constant-argument inference at every call site
const_args = ConstArgIndex.from_workspace(ws)
print(const_args.distinct_arg_values("SetFlag", slot=0))   # e.g. {0, 1, 4, 8}

# Dead-code detection (heuristic — AS3 dynamic dispatch can't be proven away)
print(find_dead_classes(ws))
print(find_dead_methods(ws))

# Entry-point candidates — Sprite / MovieClip / EventDispatcher subclasses
print(entrypoint_candidates(ws))

# McCabe cyclomatic complexity per method body
mc = method_complexity(abc, abc.method_bodies[0])
print(mc.complexity, mc.block_count)
```

### Parse SWF and ABC directly

```python
from flashkit.swf import parse_swf, TAG_DO_ABC2
from flashkit.abc import parse_abc, serialize_abc

header, tags, version, length = parse_swf(swf_bytes)

for tag in tags:
    if tag.tag_type == TAG_DO_ABC2:
        null_idx = tag.payload.index(0, 4)
        abc = parse_abc(tag.payload[null_idx + 1:])
        print(f"{len(abc.instances)} classes, {len(abc.methods)} methods")

        # Round-trip fidelity: serialize(parse(data)) == data
        assert serialize_abc(abc) == tag.payload[null_idx + 1:]
```

### Build SWF programmatically

```python
from flashkit.abc import AbcBuilder, serialize_abc
from flashkit.swf import SwfBuilder

b = AbcBuilder()
b.simple_class("Player", package="com.game",
               fields=[("hp", "int"), ("name", "String")])
b.script()
abc_bytes = serialize_abc(b.build())

swf = SwfBuilder(version=40, width=800, height=600, fps=30)
swf.add_abc("GameCode", abc_bytes)
swf_bytes = swf.build(compress=True)
```

### Disassemble method bodies

```python
from flashkit.abc import decode_instructions, resolve_instructions

for body in abc.method_bodies:
    # Raw — pool indices as integers
    for instr in decode_instructions(body.code):
        print(f"0x{instr.offset:04X}  {instr.mnemonic}  {instr.operands}")

    # Resolved — names / strings / literals
    for r in resolve_instructions(abc, decode_instructions(body.code)):
        print(f"0x{r.offset:04X}  {r.mnemonic}  {', '.join(r.operands)}")
```

### AVM2 constants

The structural constants (multiname kinds, trait kinds, attribute flags, method/instance flags) are re-exported at the package level so a TraitInfo can be classified without reaching into the submodule:

```python
from flashkit.abc import (
    CONSTANT_QNAME, CONSTANT_TYPENAME,
    TRAIT_SLOT, TRAIT_METHOD, TRAIT_GETTER,
    ATTR_OVERRIDE, METHOD_HAS_PARAM_NAMES, INSTANCE_INTERFACE,
)
```

---

## Project structure

```
flashkit/
  cli/           CLI (one module per command)
  swf/           SWF container (parse, build, tags)
  abc/           AVM2 bytecode (parse, write, disasm, builder)
  info/          Resolved class model (ClassInfo, FieldInfo, MethodInfo)
  workspace/     File loading and class index
  analysis/      Inheritance, call graph, references, strings,
                 field access, liveness, const-args, dead code,
                 complexity, method fingerprints, class graph
  decompile/     CFG-based AS3 decompiler
  graph/         CFG, dominators, loop detection (used by decompiler)
```

## References

- [AVM2 Overview (Adobe)](https://www.adobe.com/content/dam/acom/en/devnet/pdf/avm2overview.pdf)
- [SWF File Format Specification](https://open-flash.github.io/mirrors/swf-spec-19.pdf)

## License

MIT
