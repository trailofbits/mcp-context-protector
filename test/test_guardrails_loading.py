"""
Tests for the guardrails provider loading functionality.
"""

import sys
from pathlib import Path

import pytest

from contextprotector.guardrails import get_provider, get_provider_names
from test.logging_config import configure_logging

# Add the project root to the path if not already there
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logger = configure_logging()
logger.info("Starting guardrails loading test")


def test_load_guardrail_providers() -> None:
    """Test that guardrail providers can be loaded correctly."""
    # Get provider names
    providers = get_provider_names()

    # We should have at least one provider (LlamaFirewall)
    assert "LlamaFirewall" in providers, "LlamaFirewall provider not found"

    # Try to get a provider instance
    provider = get_provider("LlamaFirewall")
    assert provider is not None, "Failed to instantiate LlamaFirewall provider"
    assert provider.name == "LlamaFirewall"


def test_get_nonexistent_provider() -> None:
    """Test that trying to get a non-existent provider returns None."""
    provider = get_provider("Non-Existent Provider")
    assert provider is None, "Should return None for non-existent provider"


def test_provider_check_server_config() -> None:
    """Test that a provider can check a server config and log the results."""
    from contextprotector.mcp_config import MCPServerConfig, MCPToolDefinition

    # Get the LlamaFirewall provider
    provider = get_provider("LlamaFirewall")
    assert provider is not None, "Failed to get LlamaFirewall provider"
    logger.info("Got provider: %s", provider.name)

    # Create a simple config to check
    config = MCPServerConfig()
    config.add_tool(MCPToolDefinition(name="test_tool", description="A test tool", parameters=[]))
    logger.info("Created test config with %d tools", len(config.tools))

    # Check the config and log the result
    logger.info("Checking server config with provider...")
    result = provider.check_server_config(config)

    if result:
        logger.info("Provider returned alert: %s", result.explanation)
        logger.info("Alert data: %s", result.data)
    else:
        logger.info("Provider returned no alert (config is safe)")

    # We don't assert any specific result here since we're just testing logging


if __name__ == "__main__":
    pytest.main([__file__])
