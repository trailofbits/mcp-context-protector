#!/usr/bin/env python3
"""
Tests for the guardrails provider loading functionality.
"""

import sys
from pathlib import Path
import pytest
from tests.logging_config import configure_logging
from ..guardrails import get_provider, get_provider_names

# Add the project root to the path if not already there
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logger = configure_logging()
logger.info("Starting guardrails loading test")


def test_load_guardrail_providers():
    """Test that guardrail providers can be loaded correctly."""
    # Get provider names
    providers = get_provider_names()

    # We should have at least one provider (Llama Firewall)
    assert "Llama Firewall" in providers, "Llama Firewall provider not found"

    # Try to get a provider instance
    provider = get_provider("Llama Firewall")
    assert provider is not None, "Failed to instantiate Llama Firewall provider"
    assert provider.name == "Llama Firewall"


def test_get_nonexistent_provider():
    """Test that trying to get a non-existent provider returns None."""
    provider = get_provider("Non-Existent Provider")
    assert provider is None, "Should return None for non-existent provider"


def test_provider_check_server_config():
    """Test that a provider can check a server config and log the results."""
    from ..mcp_config import MCPServerConfig, MCPToolDefinition

    # Get the Llama Firewall provider
    provider = get_provider("Llama Firewall")
    assert provider is not None, "Failed to get Llama Firewall provider"
    logger.info(f"Got provider: {provider.name}")

    # Create a simple config to check
    config = MCPServerConfig()
    config.add_tool(
        MCPToolDefinition(name="test_tool", description="A test tool", parameters=[])
    )
    logger.info(f"Created test config with {len(config.tools)} tools")

    # Check the config and log the result
    logger.info("Checking server config with provider...")
    result = provider.check_server_config(config)

    if result:
        logger.info(f"Provider returned alert: {result.explanation}")
        logger.info(f"Alert data: {result.data}")
    else:
        logger.info("Provider returned no alert (config is safe)")

    # We don't assert any specific result here since we're just testing logging


if __name__ == "__main__":
    pytest.main([__file__])
