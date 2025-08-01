"""Llama Firewall guardrail provider for mcp-context-protector.

Provides server configuration checking capabilities.
"""

import logging

from llamafirewall import (
    LlamaFirewall,
    Role,
    ScanDecision,
    ScannerType,
    ToolMessage,
    UserMessage,
)

from contextprotector.guardrail_types import GuardrailAlert, GuardrailProvider, ToolResponse
from contextprotector.mcp_config import MCPServerConfig

logger = logging.getLogger("llama_firewall_provider")


class LlamaFirewallProvider(GuardrailProvider):
    """Llama Firewall guardrail provider.

    Checks server configurations against Llama Firewall guardrails.
    """

    def __init__(self) -> None:
        """Initialize the Llama Firewall provider."""
        logger.info("Initializing LlamaFirewallProvider")
        super().__init__()

    @property
    def name(self) -> str:
        """Get the provider name."""
        return "Llama Firewall"

    def check_server_config(self, config: MCPServerConfig) -> GuardrailAlert | None:
        """Check the provided server configuration against Llama Firewall guardrails.

        Args:
        ----
            config: The MCPServerConfig to check

        Returns:
        -------
            Optional GuardrailAlert if guardrail is triggered, or None if the configuration is safe

        """
        logger.info("LlamaFirewallProvider checking config with %d tools", len(config.tools))

        try:
            lf = LlamaFirewall(
                scanners={
                    Role.USER: [ScannerType.PROMPT_GUARD],
                    Role.SYSTEM: [ScannerType.PROMPT_GUARD],
                }
            )

            config_str = str(config)
            logger.info("Config string length: %d characters", len(config_str))

            message = UserMessage(content=config_str)
            logger.info("Created UserMessage for scanning")

            logger.info("Scanning config with Llama Firewall...")
            result = lf.scan(message)

            logger.info("Scan result decision: %s", result.decision)
            if hasattr(result, "reason") and result.reason:
                logger.info("Scan result reason: %s", result.reason)
            else:
                logger.info("No reason provided in scan result")

            if result.decision == ScanDecision.ALLOW:
                logger.info("Scan decision is ALLOW - no guardrail alert triggered")
                return None

            logger.warning("Guardrail alert triggered: %s", result.reason)
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
            logger.info("Returning alert with explanation: %s", alert.explanation)

        except Exception as e:
            logger.exception("Error in LlamaFirewallProvider.check_server_config")
            return GuardrailAlert(
                explanation=f"Error checking configuration: {e!s}",
                data={"error": str(e)},
            )

        return alert

    def check_tool_response(self, tool_response: ToolResponse) -> GuardrailAlert | None:
        """Check the provided tool response against Llama Firewall guardrails.

        Args:
        ----
            tool_response: The ToolResponse to check

        Returns:
        -------
            Optional GuardrailAlert if guardrail is triggered, or None if the response is safe

        """
        logger.info(
            "LlamaFirewallProvider checking tool response from: %s", tool_response.tool_name
        )

        try:
            lf = LlamaFirewall(scanners={Role.TOOL: [ScannerType.PROMPT_GUARD]})

            message = ToolMessage(content=tool_response.tool_output)

            logger.info("Scanning tool response with Llama Firewall...")
            result = lf.scan(message)

            logger.info("Scan result decision: %s", result.decision)
            if hasattr(result, "reason") and result.reason:
                logger.info("Scan result reason: %s", result.reason)
            else:
                logger.info("No reason provided in scan result")

            if result.decision == ScanDecision.ALLOW:
                logger.info("Scan decision is ALLOW - no guardrail alert triggered")
                return None

            logger.warning("Tool response guardrail alert triggered: %s", result.reason)
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
            logger.info("Returning tool response alert with explanation: %s", alert.explanation)

        except Exception as e:
            logger.exception("Error in LlamaFirewallProvider.check_tool_response")
            return GuardrailAlert(
                explanation=f"Error checking tool response: {e!s}",
                data={
                    "error": str(e),
                    "tool_name": tool_response.tool_name,
                },
            )
        return alert
