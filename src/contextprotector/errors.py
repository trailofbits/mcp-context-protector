"""Typed exception hierarchy for the MCP context protector.

This module replaces the bare ``ValueError`` and ``ConnectionError`` raises
scattered across the codebase with a hierarchy rooted at
``ContextProtectorError``. Each category maps to a distinct caller recovery
action:

- config errors -> fix the configuration and retry,
- connection errors -> retry the connection or check the downstream server,
- ``ToolBlockedError`` -> surface the approval UI to the user,
- ``ServerPinMismatchError`` -> abort and re-approve the changed server,
- ``QuarantineError`` -> surface the quarantine review flow.

``ConfigValidationError`` and ``ConnectionConfigError`` also subclass
``ValueError`` (multiple inheritance) so existing ``except ValueError``
handlers keep working unchanged.

This module deliberately imports nothing from the rest of the package, so
low-level modules (``mcp_wrapper``, ``mcp_config``, ...) can import from it
without creating import cycles.
"""


class ContextProtectorError(Exception):
    """Base class for all errors raised by the context protector."""


class ConfigValidationError(ContextProtectorError, ValueError):
    """Raised when a configuration value fails validation.

    Subclasses ``ValueError`` so existing ``except ValueError`` handlers keep
    working; new code should catch this type directly.
    """


class ConfigLoadError(ContextProtectorError):
    """Raised when a configuration file cannot be loaded or accessed."""


class ConfigConversionError(ContextProtectorError):
    """Raised when a configuration cannot be converted between schemas.

    Covers schema detection, environment/project resolution, and unwrapping
    context-protector command patterns back to plain server commands.
    """


class ConnectionConfigError(ContextProtectorError, ValueError):
    """Raised when connection settings are missing or inconsistent.

    Subclasses ``ValueError`` so existing ``except ValueError`` handlers keep
    working; new code should catch this type directly.
    """


class ConnectionFailedError(ContextProtectorError):
    """Raised when the downstream server connection fails or yields nothing."""


class ChildServerNotConnectedError(ContextProtectorError, ConnectionError):
    """Raised when the child MCP server is not connected.

    Previously defined in ``mcp_wrapper``; moved here so the shared type does
    not live in a low-level module. Still subclasses ``ConnectionError``, and
    the fixed message is unchanged.
    """

    def __init__(self) -> None:
        """Initialize error message."""
        super().__init__("Child MCP server not connected")


class ToolBlockedError(ContextProtectorError):
    """Raised when a tool call is blocked by the approval or guardrail system.

    The blocking detail is carried as structured attributes (``tool_name`` and
    ``reason``) rather than embedded in the message, so programmatic callers
    (approval UI, logging) do not have to re-parse the exception text.
    """

    def __init__(self, message: str, *, tool_name: str, reason: str) -> None:
        """Initialize the block error.

        Args:
        ----
            message: Human-readable description of the block.
            tool_name: Name of the tool whose call was blocked.
            reason: Machine-usable reason for the block.

        """
        super().__init__(message)
        self.tool_name = tool_name
        self.reason = reason


class ServerPinMismatchError(ContextProtectorError):
    """Raised when a pinned server's definition no longer matches its approval.

    The caller should abort the current operation and re-run server approval
    before the server can be used again.
    """


class QuarantineError(ContextProtectorError):
    """Raised for quarantine lookup and release failures."""
