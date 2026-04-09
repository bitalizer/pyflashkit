"""
flashkit error hierarchy.

All flashkit-specific exceptions inherit from ``FlashkitError`` so
consumers can ``except FlashkitError`` to catch any library error.
"""


class FlashkitError(Exception):
    """Base exception for all flashkit errors."""


class ParseError(FlashkitError):
    """Raised when binary data cannot be parsed.

    Covers both SWF container parsing and ABC bytecode parsing.
    """


class SWFParseError(ParseError):
    """Raised when SWF data is invalid or corrupted."""


class ABCParseError(ParseError):
    """Raised when ABC bytecode is invalid or corrupted."""


class SerializeError(FlashkitError):
    """Raised when an AbcFile cannot be serialized back to bytes."""


class ResourceError(FlashkitError):
    """Raised when a resource file cannot be loaded."""
