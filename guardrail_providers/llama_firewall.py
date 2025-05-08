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
from typing import Dict, Any, Optional, TYPE_CHECKING, Type

from mcp_config import MCPServerConfig

# Avoid circular imports by importing GuardrailAlert only when needed
if TYPE_CHECKING:
    from guardrails import GuardrailAlert, GuardrailProvider
else:
    # Only import the GuardrailAlert class for runtime use
    from guardrails import GuardrailAlert
    
    # Create a placeholder for GuardrailProvider that will be replaced
    # by the real parent class at runtime
    class GuardrailProvider:
        """Placeholder base class - will be replaced at runtime with real parent."""
        @property
        def name(self) -> str:
            """Get the provider name."""
            return "Base Provider"

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
        logger.info(f"LlamaFirewallProvider checking config with {len(config.tools)} tools")
        
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
            if hasattr(result, 'reason') and result.reason:
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
                explanation=result.reason.split("\n")[0] if result.reason else "Guardrail triggered (no reason provided)",
                data={
                    "full_reason": result.reason,
                    "decision": str(result.decision),
                    "scanner_type": "PROMPT_GUARD"
                }
            )
            logger.info(f"Returning alert with explanation: {alert.explanation}")
            return alert
            
        except Exception as e:
            logger.error(f"Error in LlamaFirewallProvider.check_server_config: {e}", exc_info=True)
            # Return an alert about the error
            return GuardrailAlert(
                explanation=f"Error checking configuration: {str(e)}",
                data={"error": str(e)}
            )