"""Core guardrail types for mcp-context-protector.

Defines the base classes and data structures used by guardrail providers.
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .mcp_config import MCPServerConfig

logger = logging.getLogger("guardrail_types")


@dataclass
class ToolResponse:
    """Class representing a tool call and its response for guardrail analysis.

    Attributes
    ----------
        tool_name: Name of the tool that was called
        tool_input: Input arguments passed to the tool
        tool_output: Output returned by the tool
        context: Optional additional context about the tool call

    """

    tool_name: str
    tool_input: dict[str, Any]
    tool_output: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class GuardrailAlert:
    """Class representing an alert triggered by a guardrail provider.

    Attributes
    ----------
        explanation: Human-readable explanation of why the guardrail was triggered
        data: Arbitrary data associated with the alert

    """

    explanation: str
    data: dict[str, Any] = field(default_factory=dict)


class GuardrailProvider:
    """Base class for guardrail providers."""

    @property
    def name(self) -> str:
        """Get the provider name."""
        msg = "Guardrail providers must implement the name property"
        raise NotImplementedError(msg)

    def check_server_config(self, _config: "MCPServerConfig") -> GuardrailAlert | None:
        """Check a server configuration against the guardrail.

        Args:
        ----
            config: The server configuration to check

        Returns:
        -------
            Optional GuardrailAlert if guardrail is triggered, or None if the configuration is safe

        """
        return None

    def check_tool_response(self, _tool_response: ToolResponse) -> GuardrailAlert | None:
        """Check a tool response against the guardrail.

        Args:
        ----
            tool_response: The tool response to check

        Returns:
        -------
            Optional GuardrailAlert if guardrail is triggered, or None if the response is safe

        """
        # Default implementation: no checking
        return None
