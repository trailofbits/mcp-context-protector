#!/usr/bin/env python3
"""
Core guardrail types for context-protector.
Defines the base classes and data structures used by guardrail providers.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

logger = logging.getLogger("guardrail_types")


@dataclass
class ToolResponse:
    """
    Class representing a tool call and its response for guardrail analysis.

    Attributes:
        tool_name: Name of the tool that was called
        tool_input: Input arguments passed to the tool
        tool_output: Output returned by the tool
        context: Optional additional context about the tool call
    """

    tool_name: str
    tool_input: Dict[str, Any]
    tool_output: str
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GuardrailAlert:
    """
    Class representing an alert triggered by a guardrail provider.

    Attributes:
        explanation: Human-readable explanation of why the guardrail was triggered
        data: Arbitrary data associated with the alert
    """

    explanation: str
    data: Dict[str, Any] = field(default_factory=dict)


class GuardrailProvider:
    """Base class for guardrail providers."""

    @property
    def name(self) -> str:
        """Get the provider name."""
        raise NotImplementedError("Guardrail providers must implement the name property")

    def check_server_config(self, config) -> Optional[GuardrailAlert]:
        """
        Check a server configuration against the guardrail.

        Args:
            config: The server configuration to check

        Returns:
            Optional GuardrailAlert if guardrail is triggered, or None if the configuration is safe
        """
        return None

    def check_tool_response(self, tool_response: ToolResponse) -> Optional[GuardrailAlert]:
        """
        Check a tool response against the guardrail.

        Args:
            tool_response: The tool response to check

        Returns:
            Optional GuardrailAlert if guardrail is triggered, or None if the response is safe
        """
        # Default implementation: no checking
        return None
