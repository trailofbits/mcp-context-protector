#!/usr/bin/env python3
"""
Llama Firewall guardrail provider for MCP Context Protector.
Provides server configuration checking capabilities.
"""

import logging
from llamafirewall import (
    LlamaFirewall,
    Role,
    ScanDecision,
    ScannerType,
    UserMessage,
)
from typing import Optional

from ..mcp_config import MCPServerConfig
from ..guardrail_types import GuardrailAlert, GuardrailProvider, ToolResponse

# Set up logger
logger = logging.getLogger("llama_firewall_provider")


class LlamaFirewallProvider(GuardrailProvider):
    """
    Llama Firewall guardrail provider for MCP Context Protector.
    Checks server configurations against Llama Firewall guardrails.
    """

    def __init__(self):
        """Initialize the Llama Firewall provider."""
        logger.info("Initializing LlamaFirewallProvider")
        super().__init__()

    @property
    def name(self) -> str:
        """Get the provider name."""
        return "Llama Firewall"

    def check_server_config(self, config: MCPServerConfig) -> Optional[GuardrailAlert]:
        """
        Check the provided server configuration against Llama Firewall guardrails.

        Args:
            config: The MCPServerConfig to check

        Returns:
            Optional GuardrailAlert if guardrail is triggered, or None if the configuration is safe
        """
        logger.info(
            f"LlamaFirewallProvider checking config with {len(config.tools)} tools"
        )

        try:
            lf = LlamaFirewall(
                scanners={
                    Role.USER: [ScannerType.PROMPT_GUARD],
                    Role.SYSTEM: [ScannerType.PROMPT_GUARD],
                }
            )

            # Convert config to string and log the size
            config_str = str(config)
            logger.info(f"Config string length: {len(config_str)} characters")

            # Create message
            message = UserMessage(content=config_str)
            logger.info("Created UserMessage for scanning")

            # Scan the message
            logger.info("Scanning config with Llama Firewall...")
            result = lf.scan(message)

            # Log the scan result details
            logger.info(f"Scan result decision: {result.decision}")
            if hasattr(result, "reason") and result.reason:
                logger.info(f"Scan result reason: {result.reason}")
            else:
                logger.info("No reason provided in scan result")

            # Process the result
            if result.decision == ScanDecision.ALLOW:
                logger.info("Scan decision is ALLOW - no guardrail alert triggered")
                return None

            # Create and return alert
            logger.warning(f"Guardrail alert triggered: {result.reason}")
            alert = GuardrailAlert(
                explanation=result.reason.split("\n")[0]
                if result.reason
                else "Guardrail triggered (no reason provided)",
                data={
                    "full_reason": result.reason,
                    "decision": str(result.decision),
                    "scanner_type": "PROMPT_GUARD",
                },
            )
            logger.info(f"Returning alert with explanation: {alert.explanation}")
            return alert

        except Exception as e:
            logger.error(
                f"Error in LlamaFirewallProvider.check_server_config: {e}",
                exc_info=True,
            )
            # Return an alert about the error
            return GuardrailAlert(
                explanation=f"Error checking configuration: {str(e)}",
                data={"error": str(e)},
            )

    def check_tool_response(
        self, tool_response: ToolResponse
    ) -> Optional[GuardrailAlert]:
        """
        Check the provided tool response against Llama Firewall guardrails.

        Args:
            tool_response: The ToolResponse to check

        Returns:
            Optional GuardrailAlert if guardrail is triggered, or None if the response is safe
        """
        logger.info(
            f"LlamaFirewallProvider checking tool response from: {tool_response.tool_name}"
        )

        try:
            lf = LlamaFirewall(
                scanners={
                    Role.USER: [ScannerType.PROMPT_GUARD],
                    Role.SYSTEM: [ScannerType.PROMPT_GUARD],
                }
            )

            # Convert tool response to a string for scanning
            tool_response_str = f"Tool: {tool_response.tool_name}\nInput: {tool_response.tool_input}\nOutput: {tool_response.tool_output}"
            logger.info(
                f"Tool response string length: {len(tool_response_str)} characters"
            )

            # Create message
            message = UserMessage(content=tool_response_str)
            logger.info("Created UserMessage for tool response scanning")

            # Scan the message
            logger.info("Scanning tool response with Llama Firewall...")
            result = lf.scan(message)

            # Log the scan result details
            logger.info(f"Scan result decision: {result.decision}")
            if hasattr(result, "reason") and result.reason:
                logger.info(f"Scan result reason: {result.reason}")
            else:
                logger.info("No reason provided in scan result")

            # Process the result
            if result.decision == ScanDecision.ALLOW:
                logger.info("Scan decision is ALLOW - no guardrail alert triggered")
                return None

            # Create and return alert
            logger.warning(f"Tool response guardrail alert triggered: {result.reason}")
            alert = GuardrailAlert(
                explanation=result.reason.split("\n")[0]
                if result.reason
                else "Tool response guardrail triggered (no reason provided)",
                data={
                    "full_reason": result.reason,
                    "decision": str(result.decision),
                    "scanner_type": "PROMPT_GUARD",
                    "tool_name": tool_response.tool_name,
                    "tool_input": tool_response.tool_input,
                    "tool_output_length": len(tool_response.tool_output),
                },
            )
            logger.info(
                f"Returning tool response alert with explanation: {alert.explanation}"
            )
            return alert

        except Exception as e:
            logger.error(
                f"Error in LlamaFirewallProvider.check_tool_response: {e}",
                exc_info=True,
            )
            # Return an alert about the error
            return GuardrailAlert(
                explanation=f"Error checking tool response: {str(e)}",
                data={
                    "error": str(e),
                    "tool_name": tool_response.tool_name,
                },
            )
