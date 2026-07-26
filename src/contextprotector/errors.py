"""Custom exception classes for MCP Context Protector.

Replaces generic ValueError raises with semantically meaningful exception types
to give callers a stable, type-aware way to handle different failure modes.
"""

from __future__ import annotations

import json


class ContextProtectorError(Exception):
    """Base exception for all MCP Context Protector errors."""


# Configuration errors ----------------------------------------------------


class ConfigValidationError(ContextProtectorError, ValueError):
    """Configuration parameters are missing, invalid, or inconsistent."""


class ConfigLoadError(ContextProtectorError, ValueError):
    """Configuration file could not be loaded or parsed."""

    def __init__(self, message: str, *, path: str | None = None) -> None:
        """Create a ConfigLoadError with an optional file path.

        Args:
            message: Human-readable error description.
            path: Optional path to the configuration file that failed to load.

        """
        super().__init__(message)
        self.path = path


class ConfigConversionError(ContextProtectorError, ValueError):
    """Server specification cannot be converted to the requested format."""


# Connection errors -------------------------------------------------------


class ConnectionConfigError(ContextProtectorError, ValueError):
    """Connection parameters are missing or invalid for the requested connection type."""


class ConnectionFailedError(ContextProtectorError, ConnectionError):
    """A connection to the downstream MCP server could not be established."""


class ChildServerNotConnectedError(ConnectionFailedError):
    """Raised when the child MCP server is not connected."""

    def __init__(self) -> None:
        """Initialize with a default message about the unconnected child server."""
        super().__init__("Child MCP server not connected")


# Operational / runtime errors --------------------------------------------


class ToolBlockedError(ContextProtectorError, RuntimeError):
    """A tool invocation was blocked by the guardrail or approval system.

    The message is a JSON-encoded response dict with `status` and `reason` fields
    and can be parsed by the MCP client.
    """

    def __init__(self, blocked_response: str | dict) -> None:
        """Create a ToolBlockedError from a JSON string or dict.

        Args:
            blocked_response: A JSON-encoded string or dictionary describing
                the blocked tool with `status` and `reason` fields.

        """
        if isinstance(blocked_response, dict):
            blocked_response = json.dumps(blocked_response)
        super().__init__(blocked_response)


class ServerPinMismatchError(ContextProtectorError, RuntimeError):
    """Server configuration has changed since it was last approved."""


class QuarantineError(ContextProtectorError, RuntimeError):
    """A tool response could not be quarantined."""
