# flashkit

Python toolkit for parsing, analyzing, and manipulating Adobe Flash SWF files and AVM2 bytecode. Designed for reverse engineering, deobfuscation, and binary analysis of Flash/AIR applications.

## Features

- **SWF container** — Parse, inspect, and rebuild SWF files (CWS compressed and FWS uncompressed)
- **ABC bytecode** — Full AVM2 bytecode parser and writer with byte-perfect round-trip fidelity
- **Rich class model** — Resolved class/field/method info from raw ABC constant pools
- **Disassembler** — AVM2 instruction decoder
- **Analysis** — Inheritance graph, call graph, cross-references, string index
- **Search** — Query engine for finding classes, methods, strings, and references
- **Zero dependencies** — Standard library only (struct, zlib, dataclasses)

## Install

```bash
pip install -e .
```

## Architecture

```
flashkit/
├── swf/                        # SWF container format
│   ├── parser.py               # Parse SWF → header + tags
│   ├── builder.py              # Rebuild SWF from header + tags
│   └── tags.py                 # SWFTag dataclass + tag type constants
│
├── abc/                        # AVM2 bytecode layer
│   ├── parser.py               # Parse ABC binary → AbcFile + LEB128 codecs
│   ├── writer.py               # Serialize AbcFile → bytes (round-trip safe)
│   ├── disasm.py               # AVM2 instruction decoder
│   ├── constants.py            # Opcodes, multiname kinds, namespace kinds, trait kinds
│   └── types.py                # Dataclasses: AbcFile, InstanceInfo, TraitInfo, etc.
│
├── info/                       # Rich model layer (resolved names from constant pools)
│   ├── class_info.py           # ClassInfo: name, super, interfaces, fields, methods
│   ├── member_info.py          # FieldInfo, MethodInfo (resolved names, types, signatures)
│   └── package_info.py         # PackageInfo: group classes by namespace
│
├── workspace/                  # Loaded binary workspace
│   ├── workspace.py            # Load SWF/SWZ → parse ABC → build ClassInfo index
│   └── resource.py             # Resource: one SWF or SWZ with its ABC tags
│
├── analysis/                   # Analysis services
│   ├── inheritance.py          # InheritanceGraph: parent/child, ancestors, descendants
│   ├── call_graph.py           # CallGraph: method → method edges from bytecode opcodes
│   ├── references.py           # ReferenceIndex: field type users, instantiations, callers
│   └── strings.py              # StringIndex: which classes use which string constants
│
└── search/                     # Query engine
    └── search.py               # Find by type ref, string, inheritance, call pattern
```

## Usage

### Parse a SWF file

```python
from flashkit.swf import parse_swf, print_tags

with open("application.swf", "rb") as f:
    header, tags, version, length = parse_swf(f.read())

print(f"SWF version: {version}")
print(f"Tags: {len(tags)}")
print_tags(tags)
```

### Parse ABC bytecode

```python
from flashkit.swf import parse_swf, TAG_DO_ABC, TAG_DO_ABC2
from flashkit.abc import parse_abc, serialize_abc

header, tags, version, length = parse_swf(swf_bytes)

for tag in tags:
    if tag.tag_type == TAG_DO_ABC2:
        # DoABC2: 4-byte flags + null-terminated name + ABC data
        null_idx = tag.payload.index(0, 4)
        abc_data = tag.payload[null_idx + 1:]
    elif tag.tag_type == TAG_DO_ABC:
        # DoABC: raw ABC data
        abc_data = tag.payload
    else:
        continue

    abc = parse_abc(abc_data)
    print(f"Classes:    {len(abc.instances)}")
    print(f"Methods:    {len(abc.methods)}")
    print(f"Strings:    {len(abc.string_pool)}")
    print(f"Multinames: {len(abc.multiname_pool)}")

    # Round-trip: serialize back produces identical bytes
    assert serialize_abc(abc) == abc_data
```

### Inspect the constant pool

```python
from flashkit.abc import parse_abc

abc = parse_abc(abc_data)

# All strings in the ABC
for i, s in enumerate(abc.string_pool):
    if s:  # skip empty string at index 0
        print(f"  [{i}] {s!r}")

# All class names (via multiname → string resolution)
from flashkit.abc.constants import CONSTANT_QName
for inst in abc.instances:
    mn = abc.multiname_pool[inst.name]
    if mn.kind == CONSTANT_QName:
        name = abc.string_pool[mn.name]
        ns = abc.namespace_pool[mn.ns]
        package = abc.string_pool[ns.name]
        print(f"  {package}.{name}" if package else f"  {name}")
```

### Inspect class hierarchy

```python
from flashkit.abc import parse_abc
from flashkit.abc.constants import CONSTANT_QName

abc = parse_abc(abc_data)

def resolve_name(multiname_idx):
    """Resolve a multiname index to a string name."""
    if multiname_idx == 0:
        return "Object"
    mn = abc.multiname_pool[multiname_idx]
    if mn.kind == CONSTANT_QName and mn.name > 0:
        return abc.string_pool[mn.name]
    return f"multiname[{multiname_idx}]"

for inst in abc.instances:
    name = resolve_name(inst.name)
    super_name = resolve_name(inst.super_name)
    interfaces = [resolve_name(i) for i in inst.interfaces]
    print(f"  {name} extends {super_name}", end="")
    if interfaces:
        print(f" implements {', '.join(interfaces)}", end="")
    print(f"  ({len(inst.traits)} traits)")
```

### Inspect class traits (fields and methods)

```python
from flashkit.abc import parse_abc
from flashkit.abc.constants import (
    TRAIT_Slot, TRAIT_Const, TRAIT_Method, TRAIT_Getter, TRAIT_Setter,
    CONSTANT_QName,
)

abc = parse_abc(abc_data)

def resolve_name(idx):
    if idx == 0:
        return "*"
    mn = abc.multiname_pool[idx]
    if mn.kind == CONSTANT_QName and mn.name > 0:
        return abc.string_pool[mn.name]
    return f"[{idx}]"

# Pick a class
inst = abc.instances[0]
print(f"Class: {resolve_name(inst.name)}")

for trait in inst.traits:
    name = resolve_name(trait.name)
    if trait.kind in (TRAIT_Slot, TRAIT_Const):
        kind = "const" if trait.kind == TRAIT_Const else "var"
        print(f"  {kind} {name}")
    elif trait.kind == TRAIT_Method:
        print(f"  function {name}()")
    elif trait.kind == TRAIT_Getter:
        print(f"  get {name}")
    elif trait.kind == TRAIT_Setter:
        print(f"  set {name}")
```

### Rebuild a modified SWF

```python
from flashkit.swf import parse_swf, rebuild_swf, make_doabc2_tag
from flashkit.abc import parse_abc, serialize_abc

header, tags, version, length = parse_swf(swf_bytes)

# Modify ABC content
abc = parse_abc(abc_data)
abc.string_pool.append("injected_string")
modified_abc = serialize_abc(abc)

# Inject as a new DoABC2 tag (before the End tag)
new_tag = make_doabc2_tag("CustomCode", modified_abc)
tags.insert(-1, new_tag)

# Rebuild compressed SWF
output = rebuild_swf(header, tags, compress=True)
with open("modified.swf", "wb") as f:
    f.write(output)
```

### Workspace — load and query

```python
from flashkit.workspace import Workspace

# Load one or more files
ws = Workspace()
ws.load_swf("application.swf")
ws.load_swz("module.swz")

print(ws.summary())
# Workspace: 2 resource(s)
#   application.swf: 800 classes, 14000 methods, 35000 strings
#   module.swz: 22 classes, 180 methods, 4308 strings
# Total: 822 classes, 8 interfaces, 13 packages

# Look up a class by name
cls = ws.get_class("MyClass")
print(cls.name)            # "MyClass"
print(cls.super_name)      # "EventDispatcher"
print(cls.interfaces)      # ["IDisposable", "ITickable"]
print(cls.fields)          # list of FieldInfo (name, type, static, const)
print(cls.methods)         # list of MethodInfo (name, params, return type)

# Find classes matching criteria (all filters are AND-combined)
ws.find_classes(extends="Sprite")
ws.find_classes(package="com.example", is_interface=True)
ws.find_classes(name="Manager", implements="IDisposable")
```

### Disassemble method bodies

```python
from flashkit.abc import parse_abc, decode_instructions

abc = parse_abc(abc_data)
body = abc.method_bodies[0]

for instr in decode_instructions(body.code):
    print(f"0x{instr.offset:04X}  {instr.mnemonic:20s}  {instr.operands}")
```

### Inheritance graph

```python
from flashkit.analysis import InheritanceGraph

graph = InheritanceGraph.from_classes(ws.classes)
graph.get_parent("MyClass")               # direct superclass
graph.get_children("BaseClass")            # direct subclasses
graph.get_all_children("BaseClass")        # all descendants (transitive)
graph.get_all_parents("MyClass")           # ancestor chain to root
graph.get_implementors("ISerializable")    # classes implementing an interface
graph.get_siblings("MyClass")              # classes sharing same parent
graph.is_subclass("MyClass", "Sprite")     # check inheritance
```

### Call graph

```python
from flashkit.analysis import CallGraph

graph = CallGraph.from_workspace(ws)
print(f"{graph.edge_count} edges, {graph.unique_targets} targets")

graph.get_callers("toString")              # all edges calling toString
graph.get_callees("MyClass.init")          # all calls from MyClass.init
graph.get_instantiators("Point")           # who calls new Point()
graph.get_unique_callers("serialize")      # unique caller names
```

### Cross-references

```python
from flashkit.analysis import ReferenceIndex

refs = ReferenceIndex.from_workspace(ws)
refs.field_type_users("int")               # fields of type int
refs.method_param_users("String")          # methods taking String param
refs.instantiators("Texture")              # new Texture() sites
refs.string_users("config.xml")            # methods pushing this string
refs.references_from("MyClass")            # all outgoing refs from a class
refs.references_to("Point")               # all incoming refs to Point
```

### String index

```python
from flashkit.analysis import StringIndex

idx = StringIndex.from_workspace(ws)
idx.search("http")                         # strings containing "http"
idx.search(r"config\\.xml", regex=True)    # regex search
idx.strings_in_class("MyClass")            # all strings used by a class
idx.classes_using_string("error")          # classes referencing this string
idx.url_strings()                          # strings that look like URLs
idx.debug_markers()                        # debug source file markers
```

### Unified search engine

```python
from flashkit.search import SearchEngine

engine = SearchEngine(ws)

# Class queries
engine.find_classes(extends="Sprite")
engine.find_subclasses("BaseEntity", transitive=True)
engine.find_implementors("ISerializable")

# Member queries
engine.find_fields(type_name="int", is_static=True)
engine.find_methods(return_type="String", name="get")

# Reference queries
engine.find_instantiators("Point")
engine.find_type_users("PlayerData")
engine.find_callers("serialize")

# String queries
engine.find_by_string("config", regex=False)
engine.find_classes_by_string("http://example.com")

# Structural patterns
engine.find_classes_with_field_type("ByteArray")
engine.find_classes_with_method_returning("XML")
```

## What ClassInfo gives you that raw ABC doesn't

The raw `AbcFile` stores everything as pool indices — you need to chase
`multiname_pool[inst.name] → string_pool[mn.name]` chains to get a class name.
`ClassInfo` resolves all of that upfront:

| Raw ABC | ClassInfo |
|---------|-----------|
| `inst.name = 1247` (multiname index) | `cls.name = "PlayerManager"` |
| `inst.super_name = 89` (multiname index) | `cls.super_name = "EventDispatcher"` |
| `inst.interfaces = [42, 78]` (multiname indices) | `cls.interfaces = ["IDisposable", "ITickable"]` |
| `trait.name = 3201, trait.data = raw bytes` | `field.name = "mHealth", field.type_name = "Number"` |
| `method.return_type = 0` (means any/void) | `method.return_type = "void"` |
| `method_body.code = b"\xd0\x30\x47"` (raw opcodes) | `decode_instructions(body.code)` → structured `Instruction` list |

## Design philosophy

flashkit separates concerns into layers:

| Layer | Package | Purpose |
|-------|---------|---------|
| **Binary I/O** | `swf/`, `abc/` | Parse and serialize SWF containers and ABC bytecode |
| **Class model** | `info/` | Resolve pool indices into usable ClassInfo/FieldInfo/MethodInfo |
| **Loading** | `workspace/` | Load SWF/SWZ files and build a unified class index |
| **Analysis** | `analysis/` | Inheritance graph, call graph, cross-references, string index |
| **Query** | `search/` | Unified search across all analysis indexes |
| **Mappings** | *(consumer)* | Name mappings and deobfuscation live in the consuming application |

## Data types

### AbcFile

The central data structure. Contains all constant pools and definitions:

```python
@dataclass
class AbcFile:
    # Constant pools (index 0 is always the implicit default)
    int_pool: list[int]
    uint_pool: list[int]
    double_pool: list[float]
    string_pool: list[str]
    namespace_pool: list[NamespaceInfo]
    ns_set_pool: list[NsSetInfo]
    multiname_pool: list[MultinameInfo]

    # Definitions
    methods: list[MethodInfo]        # method signatures
    metadata: list[MetadataInfo]     # [SWF(...)] annotations
    instances: list[InstanceInfo]    # instance side of classes
    classes: list[ClassInfo]         # static side of classes
    scripts: list[ScriptInfo]        # entry points
    method_bodies: list[MethodBodyInfo]  # bytecode
```

### SWFTag

A single tag from a parsed SWF file:

```python
@dataclass
class SWFTag:
    tag_type: int       # TAG_DO_ABC2, TAG_SYMBOL_CLASS, etc.
    payload: bytes      # raw tag data
    name: str = ""      # populated for DoABC2 tags
```

## References

- [AVM2 Overview (Adobe)](https://www.adobe.com/content/dam/acom/en/devnet/pdf/avm2overview.pdf) — AVM2 bytecode specification
- [SWF File Format Specification](https://open-flash.github.io/mirrors/swf-spec-19.pdf) — SWF container format

