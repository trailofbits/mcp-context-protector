#!/usr/bin/env python3
"""
Mock guardrail providers for testing guardrail functionality.
"""

import logging
from typing import Optional

from ..mcp_config import MCPServerConfig
from ..guardrail_types import GuardrailProvider, GuardrailAlert

# Set up logger
logger = logging.getLogger("mock_guardrail_provider")


class MockGuardrailProvider(GuardrailProvider):
    """
    A configurable mock guardrail provider for testing.
    This provider can be manually set to trigger alerts for testing purposes.
    Only available when running tests.
    """

    def __init__(
        self, trigger_alert: bool = False, alert_text: str = "Test guardrail alert"
    ):
        """
        Initialize the mock guardrail provider.

        Args:
            trigger_alert: Whether to trigger an alert by default
            alert_text: The text to use for the alert
        """
        logger.info("Initializing MockGuardrailProvider")
        super().__init__()
        self._trigger_alert = trigger_alert
        self._alert_text = alert_text

    @property
    def name(self) -> str:
        """Get the provider name."""
        return "Mock Guardrail Provider"

    def set_trigger_alert(
        self, trigger: bool, alert_text: Optional[str] = None
    ) -> None:
        """
        Configure the provider to trigger an alert or not.

        Args:
            trigger: Whether to trigger an alert
            alert_text: Optional new alert text to use
        """
        logger.info(f"Setting trigger_alert to {trigger}")
        self._trigger_alert = trigger
        if alert_text is not None:
            self._alert_text = alert_text
            logger.info(f"Setting alert_text to '{alert_text}'")

    def check_server_config(self, config: MCPServerConfig) -> Optional[GuardrailAlert]:
        """
        Check the server configuration based on the current trigger setting.

        Args:
            config: The server configuration to check

        Returns:
            GuardrailAlert if trigger is set, None otherwise
        """
        logger.info(f"Checking server config with {len(config.tools)} tools")
        logger.info(f"Trigger alert is set to: {self._trigger_alert}")

        if self._trigger_alert:
            logger.info(f"Triggering alert with text: {self._alert_text}")
            return GuardrailAlert(
                explanation=self._alert_text,
                data={
                    "mock_data": "This is mock data for testing",
                    "config_tools_count": len(config.tools),
                    "is_test": True,
                },
            )

        logger.info("No alert triggered")
        return None


class AlwaysAlertGuardrailProvider(GuardrailProvider):
    """
    A mock guardrail provider that always triggers an alert.
    Useful for testing guardrail blocking behavior.
    """

    def __init__(self, alert_text: str = "Security risk detected"):
        """
        Initialize the always-alert provider.

        Args:
            alert_text: The text to use for the alert
        """
        logger.info("Initializing AlwaysAlertGuardrailProvider")
        super().__init__()
        self._alert_text = alert_text

    @property
    def name(self) -> str:
        """Get the provider name."""
        return "Always Alert Provider"

    def check_server_config(self, config: MCPServerConfig) -> GuardrailAlert:
        """
        Always returns a guardrail alert regardless of the config.

        Args:
            config: The server configuration to check

        Returns:
            GuardrailAlert with the configured text
        """
        logger.info(f"Always triggering alert with text: {self._alert_text}")
        return GuardrailAlert(
            explanation=self._alert_text,
            data={
                "mock_data": "This is mock data for always-alert testing",
                "config_tools_count": len(config.tools),
                "is_always_alert": True,
            },
        )


class NeverAlertGuardrailProvider(GuardrailProvider):
    """
    A mock guardrail provider that never triggers an alert.
    Useful for testing normal operation without guardrails.
    """

    def __init__(self):
        """Initialize the never-alert provider."""
        logger.info("Initializing NeverAlertGuardrailProvider")
        super().__init__()

    @property
    def name(self) -> str:
        """Get the provider name."""
        return "Never Alert Provider"

    def check_server_config(self, config: MCPServerConfig) -> None:
        """
        Always returns None, indicating no guardrail alert.

        Args:
            config: The server configuration to check

        Returns:
            None, indicating no guardrail alert
        """
        logger.info("Never triggering alert, returning None")
        return None