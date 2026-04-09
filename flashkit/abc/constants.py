"""
AVM2 constants — multiname kinds, namespace kinds, trait kinds, flags, and opcodes.

All constants follow the naming convention from the AVM2 specification.
Opcode constants use the ``OP_`` prefix and match the mnemonics from
avm2overview.pdf Chapter 5 (AVM2 instructions).

Reference: Adobe AVM2 Overview, Chapters 4.4–4.8, Chapter 5.
"""

# ── Multiname kinds ─────────────────────────────────────────────────────────
# Used in MultinameInfo.kind to determine which fields are valid.

CONSTANT_QName       = 0x07  # Qualified name: namespace + name
CONSTANT_QNameA      = 0x0D  # Qualified name (attribute)
CONSTANT_RTQName     = 0x0F  # Runtime qualified name: name only, ns from stack
CONSTANT_RTQNameA    = 0x10  # Runtime qualified name (attribute)
CONSTANT_RTQNameL    = 0x11  # Runtime qualified name (late-bound): both from stack
CONSTANT_RTQNameLA   = 0x12  # Runtime qualified name (late-bound, attribute)
CONSTANT_Multiname   = 0x09  # Multiname: name + namespace set
CONSTANT_MultinameA  = 0x0E  # Multiname (attribute)
CONSTANT_MultinameL  = 0x1B  # Late-bound multiname: name from stack + ns set
CONSTANT_MultinameLA = 0x1C  # Late-bound multiname (attribute)
CONSTANT_TypeName    = 0x1D  # Parameterized type: Vector.<T>

# ── Namespace kinds ─────────────────────────────────────────────────────────
# Used in NamespaceInfo.kind.

CONSTANT_Namespace          = 0x08  # Regular namespace
CONSTANT_PackageNamespace   = 0x16  # Public package namespace
CONSTANT_PackageInternalNs  = 0x17  # Package-internal namespace
CONSTANT_ProtectedNamespace = 0x18  # Protected namespace (class hierarchy)
CONSTANT_ExplicitNamespace  = 0x19  # Explicit namespace (user-defined)
CONSTANT_StaticProtectedNs  = 0x1A  # Static protected namespace
CONSTANT_PrivateNs          = 0x05  # Private namespace (class-scoped)

# ── Trait kinds ─────────────────────────────────────────────────────────────
# Used in TraitInfo.kind (lower 4 bits of the kind byte).
# Upper 4 bits are trait attributes (ATTR_Final=0x01, ATTR_Override=0x02, ATTR_Metadata=0x04).

TRAIT_Slot     = 0  # Instance variable (field)
TRAIT_Method   = 1  # Method
TRAIT_Getter   = 2  # Getter property
TRAIT_Setter   = 3  # Setter property
TRAIT_Class    = 4  # Class definition
TRAIT_Function = 5  # Function (closure)
TRAIT_Const    = 6  # Constant (final field)

# Trait attribute flags (upper 4 bits of kind byte)
ATTR_Final    = 0x01
ATTR_Override = 0x02
ATTR_Metadata = 0x04

# ── Method flags ────────────────────────────────────────────────────────────
# Bitmask flags in MethodInfo.flags.

METHOD_NeedArguments  = 0x01  # Method uses 'arguments' object
METHOD_NeedActivation = 0x02  # Method needs an activation object
METHOD_NeedRest       = 0x04  # Method uses ...rest parameter
METHOD_HasOptional    = 0x08  # Method has optional parameters
METHOD_SetDxns        = 0x40  # Method sets default XML namespace
METHOD_HasParamNames  = 0x80  # Method has debug parameter names

# ── Instance flags ──────────────────────────────────────────────────────────
# Bitmask flags in InstanceInfo.flags.

INSTANCE_Sealed      = 0x01  # Class is sealed (no dynamic properties)
INSTANCE_Final       = 0x02  # Class is final (cannot be subclassed)
INSTANCE_Interface   = 0x04  # Class is an interface
INSTANCE_ProtectedNs = 0x08  # Class has a protected namespace

# ── AVM2 opcodes ────────────────────────────────────────────────────────────
# Instruction opcodes for AVM2 bytecode (MethodBodyInfo.code).
# Organized by functional group.

# Control flow
OP_nop            = 0x02
OP_throw          = 0x03
OP_label          = 0x09
OP_jump           = 0x10
OP_iftrue         = 0x11
OP_iffalse        = 0x12
OP_ifeq           = 0x13
OP_ifne           = 0x14
OP_iflt           = 0x15
OP_ifle           = 0x16
OP_ifgt           = 0x17
OP_ifge           = 0x18
OP_ifstricteq     = 0x19
OP_ifstrictne     = 0x1A
OP_lookupswitch   = 0x1B

# Scope management
OP_pushwith       = 0x1C
OP_popscope       = 0x1D
OP_pushscope      = 0x30
OP_getscopeobject = 0x65

# Stack operations
OP_pop            = 0x29
OP_dup            = 0x2A
OP_swap           = 0x2B

# Push constants
OP_pushnull       = 0x20
OP_pushundefined  = 0x21
OP_pushtrue       = 0x26
OP_pushfalse      = 0x27
OP_pushnan        = 0x28
OP_pushbyte       = 0x24
OP_pushshort      = 0x25
OP_pushstring     = 0x2C
OP_pushint        = 0x2D
OP_pushuint       = 0x2E
OP_pushdouble     = 0x2F

# Iteration
OP_nextname       = 0x1E
OP_hasnext        = 0x1F
OP_nextvalue      = 0x23
OP_hasnext2       = 0x32

# Locals
OP_getlocal       = 0x62
OP_setlocal       = 0x63
OP_getlocal_0     = 0xD0
OP_getlocal_1     = 0xD1
OP_getlocal_2     = 0xD2
OP_getlocal_3     = 0xD3
OP_setlocal_0     = 0xD4
OP_setlocal_1     = 0xD5
OP_setlocal_2     = 0xD6
OP_setlocal_3     = 0xD7

# Properties
OP_getproperty    = 0x66
OP_setproperty    = 0x61
OP_initproperty   = 0x68
OP_getlex         = 0x60
OP_findpropstrict = 0x5D

# Calls
OP_call           = 0x41
OP_construct      = 0x42
OP_callproperty   = 0x46
OP_returnvoid     = 0x47
OP_returnvalue    = 0x48
OP_constructsuper = 0x49
OP_constructprop  = 0x4A
OP_callpropvoid   = 0x4F

# Object creation
OP_newfunction    = 0x40
OP_newarray       = 0x56
OP_newclass       = 0x58

# Type conversion
OP_convert_s      = 0x70
OP_convert_i      = 0x73
OP_convert_d      = 0x75
OP_coerce         = 0x80
OP_coerce_a       = 0x82
OP_coerce_s       = 0x85

# Comparison & logic
OP_typeof         = 0x95
OP_not            = 0x96
OP_equals         = 0xAB
OP_strictequals   = 0xAC
OP_lessthan       = 0xAD
OP_lessequals     = 0xAE
OP_greaterthan    = 0xAF
OP_greaterequals  = 0xB0

# Arithmetic
OP_increment      = 0x91
OP_decrement      = 0x93
OP_add            = 0xA0
OP_subtract       = 0xA1
OP_multiply       = 0xA2
OP_divide         = 0xA3
OP_modulo         = 0xA4
OP_increment_i    = 0xC0
OP_decrement_i    = 0xC1

# Bitwise
OP_bitor          = 0xA9
OP_bitand         = 0xA8
OP_bitxor         = 0xAA
OP_lshift         = 0xA5
OP_rshift         = 0xA6
OP_urshift        = 0xA7
OP_bitnot         = 0x97

# Debugging
OP_debug          = 0xEF
OP_debugline      = 0xF0
OP_debugfile      = 0xF1
