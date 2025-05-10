#!/usr/bin/env python3
"""
Core guardrail types for MCP Context Protector.
Defines the base classes and data structures used by guardrail providers.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

logger = logging.getLogger("guardrail_types")


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
        raise NotImplementedError(
            "Guardrail providers must implement the name property"
        )

    def check_server_config(self, config) -> Optional[GuardrailAlert]:
        """
        Check a server configuration against the guardrail.

        Args:
            config: The server configuration to check

        Returns:
            Optional GuardrailAlert if guardrail is triggered, or None if the configuration is safe
        """
        raise NotImplementedError(
            "Guardrail providers must implement check_server_config method"
        )