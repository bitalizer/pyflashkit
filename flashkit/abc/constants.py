"""
AVM2 structural constants — multiname kinds, namespace kinds, trait kinds, flags.

All constants follow the naming convention from the AVM2 specification.
Opcode constants live in :mod:`flashkit.abc.opcodes`.

Reference: Adobe AVM2 Overview, Chapters 4.4–4.8.
"""

# ── Multiname kinds ─────────────────────────────────────────────────────────
# Used in MultinameInfo.kind to determine which fields are valid.

CONSTANT_QNAME       = 0x07  # Qualified name: namespace + name
CONSTANT_QNAME_A      = 0x0D  # Qualified name (attribute)
CONSTANT_RTQNAME     = 0x0F  # Runtime qualified name: name only, ns from stack
CONSTANT_RTQNAME_A    = 0x10  # Runtime qualified name (attribute)
CONSTANT_RTQNAME_L    = 0x11  # Runtime qualified name (late-bound): both from stack
CONSTANT_RTQNAME_LA   = 0x12  # Runtime qualified name (late-bound, attribute)
CONSTANT_MULTINAME   = 0x09  # Multiname: name + namespace set
CONSTANT_MULTINAME_A  = 0x0E  # Multiname (attribute)
CONSTANT_MULTINAME_L  = 0x1B  # Late-bound multiname: name from stack + ns set
CONSTANT_MULTINAME_LA = 0x1C  # Late-bound multiname (attribute)
CONSTANT_TYPENAME    = 0x1D  # Parameterized type: Vector.<T>

# ── Namespace kinds ─────────────────────────────────────────────────────────
# Used in NamespaceInfo.kind.

CONSTANT_NAMESPACE          = 0x08  # Regular namespace
CONSTANT_PACKAGE_NAMESPACE   = 0x16  # Public package namespace
CONSTANT_PACKAGE_INTERNAL_NS  = 0x17  # Package-internal namespace
CONSTANT_PROTECTED_NAMESPACE = 0x18  # Protected namespace (class hierarchy)
CONSTANT_EXPLICIT_NAMESPACE  = 0x19  # Explicit namespace (user-defined)
CONSTANT_STATIC_PROTECTED_NS  = 0x1A  # Static protected namespace
CONSTANT_PRIVATE_NS          = 0x05  # Private namespace (class-scoped)

# ── Trait kinds ─────────────────────────────────────────────────────────────
# Used in TraitInfo.kind (lower 4 bits of the kind byte).
# Upper 4 bits are trait attributes (ATTR_FINAL=0x01, ATTR_OVERRIDE=0x02, ATTR_METADATA=0x04).

TRAIT_SLOT     = 0  # Instance variable (field)
TRAIT_METHOD   = 1  # Method
TRAIT_GETTER   = 2  # Getter property
TRAIT_SETTER   = 3  # Setter property
TRAIT_CLASS    = 4  # Class definition
TRAIT_FUNCTION = 5  # Function (closure)
TRAIT_CONST    = 6  # Constant (final field)

# Trait attribute flags (upper 4 bits of kind byte)
ATTR_FINAL    = 0x01
ATTR_OVERRIDE = 0x02
ATTR_METADATA = 0x04

# ── Method flags ────────────────────────────────────────────────────────────
# Bitmask flags in MethodInfo.flags.

METHOD_NEED_ARGUMENTS  = 0x01  # Method uses 'arguments' object
METHOD_NEED_ACTIVATION = 0x02  # Method needs an activation object
METHOD_NEED_REST       = 0x04  # Method uses ...rest parameter
METHOD_HAS_OPTIONAL    = 0x08  # Method has optional parameters
METHOD_SET_DXNS        = 0x40  # Method sets default XML namespace
METHOD_HAS_PARAM_NAMES  = 0x80  # Method has debug parameter names

# ── Instance flags ──────────────────────────────────────────────────────────
# Bitmask flags in InstanceInfo.flags.

INSTANCE_SEALED      = 0x01  # Class is sealed (no dynamic properties)
INSTANCE_FINAL       = 0x02  # Class is final (cannot be subclassed)
INSTANCE_INTERFACE   = 0x04  # Class is an interface
INSTANCE_PROTECTED_NS = 0x08  # Class has a protected namespace
