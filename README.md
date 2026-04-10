# flashkit

Parse, analyze, and manipulate Adobe Flash SWF files and AVM2 bytecode.

## Install

```bash
pip install pyflashkit
```

Or from source:

```bash
git clone https://github.com/bitalizer/pyflashkit.git
cd pyflashkit
pip install -e .
```

## Quick start

```python
from flashkit.workspace import Workspace

ws = Workspace()
ws.load_swf("application.swf")

# Find all classes extending Sprite
for cls in ws.find_classes(extends="Sprite"):
    print(f"{cls.qualified_name} — {len(cls.fields)} fields, {len(cls.methods)} methods")

# Inspect a specific class
player = ws.get_class("PlayerManager")
print(player.super_name)    # "EventDispatcher"
print(player.interfaces)    # ["IDisposable", "ITickable"]
print(player.fields[0].name, player.fields[0].type_name)  # "mHealth", "Number"

# Search strings used in bytecode
for s in ws.search_strings("config"):
    print(s)
```

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

### `flashkit classes`

```bash
flashkit classes app.swf                # all classes
flashkit classes app.swf -s Manager     # search by name
flashkit classes app.swf -p com.game    # filter by package
flashkit classes app.swf -e Sprite      # filter by superclass
flashkit classes app.swf -i             # interfaces only
flashkit classes app.swf -v             # verbose output
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

### `flashkit strings`

```bash
flashkit strings app.swf                # list all
flashkit strings app.swf -s config      # search
flashkit strings app.swf -s config -v   # with usage locations
flashkit strings app.swf -s "\\d+" -r   # regex
flashkit strings app.swf -c             # classify (URLs, debug)
```

### `flashkit tags`

```bash
flashkit tags app.swf
```

### `flashkit disasm`

```bash
flashkit disasm app.swf --class PlayerManager
flashkit disasm app.swf --method-index 42
```

### `flashkit tree`

```bash
flashkit tree app.swf BaseEntity              # show descendants
flashkit tree app.swf PlayerManager -a        # show ancestors
```

### `flashkit callers` / `flashkit callees`

```bash
flashkit callers app.swf toString
flashkit callees app.swf PlayerManager.init
```

### `flashkit refs`

```bash
flashkit refs app.swf Point
```

### `flashkit fields`

```bash
flashkit fields app.swf PlayerManager              # field access summary (R/W counts)
flashkit fields app.swf PlayerManager -c            # constructor assignments in order
flashkit fields app.swf PlayerManager -f mHealth    # who reads/writes a specific field
flashkit fields app.swf PlayerManager -m takeDamage # what fields a method accesses
```

### `flashkit packages` / `flashkit extract` / `flashkit build`

```bash
flashkit packages app.swf                     # list packages
flashkit extract app.swf -o ./output          # extract ABC blocks
flashkit build app.swf -o rebuilt.swf         # rebuild (compressed)
flashkit build app.swf -o out.swf -d          # rebuild (decompressed)
```

---

## Library

### Load and query

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

### Search and analysis

All analysis is accessed directly through the Workspace — no separate imports needed.

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

<details>
<summary><strong>Parse SWF and ABC directly</strong></summary>

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

</details>

<details>
<summary><strong>Build SWF programmatically</strong></summary>

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

</details>

<details>
<summary><strong>Disassemble method bodies</strong></summary>

```python
from flashkit.abc import decode_instructions

for body in abc.method_bodies:
    for instr in decode_instructions(body.code):
        print(f"0x{instr.offset:04X}  {instr.mnemonic}  {instr.operands}")
```

</details>

---

## Project structure

```
flashkit/
  cli/           CLI (one module per command)
  swf/           SWF container (parse, build, tags)
  abc/           AVM2 bytecode (parse, write, disasm, builder)
  info/          Resolved class model (ClassInfo, FieldInfo, MethodInfo)
  workspace/     File loading and class index
  analysis/      Inheritance, call graph, references, strings, field access
```

## References

- [AVM2 Overview (Adobe)](https://www.adobe.com/content/dam/acom/en/devnet/pdf/avm2overview.pdf)
- [SWF File Format Specification](https://open-flash.github.io/mirrors/swf-spec-19.pdf)

## License

MIT
