"""Mock guardrail providers for testing guardrail functionality."""

import logging

from contextprotector.guardrail_types import GuardrailAlert, GuardrailProvider, ToolResponse
from contextprotector.mcp_config import MCPServerConfig

logger = logging.getLogger("mock_guardrail_provider")


class MockGuardrailProvider(GuardrailProvider):
    """A configurable mock guardrail provider for testing.

    This provider can be manually set to trigger alerts for testing purposes.
    Only available when running tests.
    """

    def __init__(self) -> None:
        """Initialize the mock guardrail provider."""
        logger.info("Initializing MockGuardrailProvider")
        super().__init__()
        self._trigger_alert = False
        self._alert_text = None

    @property
    def name(self) -> str:
        """Get the provider name."""
        return "Mock Guardrail Provider"

    def set_trigger_alert(self, alert_text: str | None = None) -> None:
        """Configure the provider to trigger an alert.

        Args:
        ----
            alert_text: Optional new alert text to use

        """
        logger.info("Setting trigger_alert to True")
        self._trigger_alert = True
        if alert_text is not None:
            self._alert_text = alert_text
            logger.info("Setting alert_text to '%s'", alert_text)

    def unset_trigger_alert(self) -> None:
        """Configure the provider to not trigger an alert."""
        logger.info("Setting trigger_alert to False")
        self._trigger_alert = False
        self._alert_text = None

    def check_server_config(self, config: MCPServerConfig) -> GuardrailAlert | None:
        """Check the server configuration based on the current trigger setting.

        Args:
        ----
            config: The server configuration to check

        Returns:
        -------
            GuardrailAlert if trigger is set, None otherwise

        """
        logger.info("Checking server config with %d tools", len(config.tools))
        logger.info("Trigger alert is set to: %s", self._trigger_alert)

        if self._trigger_alert:
            logger.info("Triggering alert with text: %s", self._alert_text)
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

    def check_tool_response(self, tool_response: ToolResponse) -> GuardrailAlert | None:
        """Check the tool response based on the current trigger setting.

        Args:
        ----
            tool_response: The tool response to check

        Returns:
        -------
            GuardrailAlert if trigger is set, None otherwise

        """
        logger.info("Checking tool response for tool: %s", tool_response.tool_name)
        logger.info("Trigger alert is set to: %s", self._trigger_alert)

        if self._trigger_alert:
            logger.info("Triggering alert with text: %s", self._alert_text)
            return GuardrailAlert(
                explanation=self._alert_text,
                data={
                    "mock_data": "This is mock data for testing tool responses",
                    "tool_name": tool_response.tool_name,
                    "tool_input": tool_response.tool_input,
                    "tool_output_length": len(tool_response.tool_output),
                    "is_test": True,
                },
            )

        logger.info("No alert triggered")
        return None


class AlwaysAlertGuardrailProvider(GuardrailProvider):
    """A mock guardrail provider that always triggers an alert.

    Useful for testing guardrail blocking behavior.
    """

    def __init__(self, alert_text: str = "Security risk detected") -> None:
        """Initialize the always-alert provider.

        Args:
        ----
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
        """Return a pre-written guardrail alert regardless of the config.

        Args:
        ----
            config: The server configuration to check

        Returns:
        -------
            GuardrailAlert with the configured text

        """
        logger.info("Always triggering alert with text: %s", self._alert_text)
        return GuardrailAlert(
            explanation=self._alert_text,
            data={
                "mock_data": "This is mock data for always-alert testing",
                "config_tools_count": len(config.tools),
                "is_always_alert": True,
            },
        )

    def check_tool_response(self, tool_response: ToolResponse) -> GuardrailAlert:
        """Return a pre-written guardrail alert regardless of the tool response.

        Args:
        ----
            tool_response: The tool response to check

        Returns:
        -------
            GuardrailAlert with the configured text

        """
        logger.info("Always triggering alert for tool: %s", tool_response.tool_name)
        return GuardrailAlert(
            explanation=self._alert_text,
            data={
                "mock_data": "This is mock data for always-alert testing tool responses",
                "tool_name": tool_response.tool_name,
                "tool_input": tool_response.tool_input,
                "tool_output_length": len(tool_response.tool_output),
                "is_always_alert": True,
            },
        )


class NeverAlertGuardrailProvider(GuardrailProvider):
    """A mock guardrail provider that never triggers an alert.

    Useful for testing normal operation without guardrails.
    """

    def __init__(self) -> None:
        """Initialize the never-alert provider."""
        logger.info("Initializing NeverAlertGuardrailProvider")
        super().__init__()

    @property
    def name(self) -> str:
        """Get the provider name."""
        return "Never Alert Provider"

    def check_server_config(self, _config: MCPServerConfig) -> None:
        """Return None, indicating no guardrail alert.

        Args:
        ----
            config: The server configuration to check

        Returns:
        -------
            None, indicating no guardrail alert

        """
        logger.info("Never triggering alert, returning None")
