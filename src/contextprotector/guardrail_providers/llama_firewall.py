#!/usr/bin/env python3
"""
Llama Firewall guardrail provider for context-protector.
Provides server configuration checking capabilities.
"""

import logging
from llamafirewall import (
    LlamaFirewall,
    Role,
    ScanDecision,
    ScannerType,
    UserMessage,
    ToolMessage,
)
from typing import Optional

from ..mcp_config import MCPServerConfig
from ..guardrail_types import GuardrailAlert, GuardrailProvider, ToolResponse

logger = logging.getLogger("llama_firewall_provider")


class LlamaFirewallProvider(GuardrailProvider):
    """
    Llama Firewall guardrail provider.
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
        logger.info(f"LlamaFirewallProvider checking config with {len(config.tools)} tools")

        try:
            lf = LlamaFirewall(
                scanners={
                    Role.USER: [ScannerType.PROMPT_GUARD],
                    Role.SYSTEM: [ScannerType.PROMPT_GUARD],
                }
            )

            config_str = str(config)
            logger.info(f"Config string length: {len(config_str)} characters")

            message = UserMessage(content=config_str)
            logger.info("Created UserMessage for scanning")

            logger.info("Scanning config with Llama Firewall...")
            result = lf.scan(message)

            logger.info(f"Scan result decision: {result.decision}")
            if hasattr(result, "reason") and result.reason:
                logger.info(f"Scan result reason: {result.reason}")
            else:
                logger.info("No reason provided in scan result")

            if result.decision == ScanDecision.ALLOW:
                logger.info("Scan decision is ALLOW - no guardrail alert triggered")
                return None

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
            return GuardrailAlert(
                explanation=f"Error checking configuration: {str(e)}",
                data={"error": str(e)},
            )

    def check_tool_response(self, tool_response: ToolResponse) -> Optional[GuardrailAlert]:
        """
        Check the provided tool response against Llama Firewall guardrails.

        Args:
            tool_response: The ToolResponse to check

        Returns:
            Optional GuardrailAlert if guardrail is triggered, or None if the response is safe
        """
        logger.info(f"LlamaFirewallProvider checking tool response from: {tool_response.tool_name}")

        try:
            lf = LlamaFirewall(scanners={Role.TOOL: [ScannerType.PROMPT_GUARD]})

            message = ToolMessage(content=tool_response.tool_output)

            logger.info("Scanning tool response with Llama Firewall...")
            result = lf.scan(message)

            logger.info(f"Scan result decision: {result.decision}")
            if hasattr(result, "reason") and result.reason:
                logger.info(f"Scan result reason: {result.reason}")
            else:
                logger.info("No reason provided in scan result")

            if result.decision == ScanDecision.ALLOW:
                logger.info("Scan decision is ALLOW - no guardrail alert triggered")
                return None

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
            logger.info(f"Returning tool response alert with explanation: {alert.explanation}")
            return alert

        except Exception as e:
            logger.error(
                f"Error in LlamaFirewallProvider.check_tool_response: {e}",
                exc_info=True,
            )
            return GuardrailAlert(
                explanation=f"Error checking tool response: {str(e)}",
                data={
                    "error": str(e),
                    "tool_name": tool_response.tool_name,
                },
            )
