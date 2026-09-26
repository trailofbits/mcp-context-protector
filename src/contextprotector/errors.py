"""Exception hierarchy for mcp-context-protector.

Each subclass also inherits from `ValueError` so existing callers that
catch/expect `ValueError` (including tests using `pytest.raises(ValueError)`)
keep working unchanged, while callers that want to distinguish failure modes
can catch the specific type instead of pattern-matching on error text.
"""

from __future__ import annotations


class ContextProtectorError(Exception):
    """Base class for all mcp-context-protector-specific errors."""


class ConfigValidationError(ContextProtectorError, ValueError):
    """A configuration value, file, or command-line invocation is invalid.

    Covers malformed server specs, malformed JSON config data, unsupported
    schema shapes, and wrapped command-line invocations that can't be parsed
    back into their original form.
    """


class ConnectionConfigError(ContextProtectorError, ValueError):
    """Connection parameters (connection type, url, command) are missing or invalid."""


class ChildServerProtocolError(ContextProtectorError, ValueError):
    """The downstream child server connected but didn't behave as expected.

    For example, it returned no tools when tools were required.
    """


class QuarantineError(ContextProtectorError, ValueError):
    """The quarantine subsystem was used incorrectly (uninitialized, unknown UUID, etc.)."""


class ToolCallBlockedError(ContextProtectorError, ValueError):
    """A tool call was blocked by the approval/guardrail policy."""
