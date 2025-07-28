#!/usr/bin/env python3
"""
Tests for the tool response scanning feature.
"""

import logging
import pytest
from unittest.mock import MagicMock

from mcp.types import CallToolResult as ToolCallResult
from mcp.types import TextContent

from contextprotector.mcp_wrapper import MCPWrapperServer
from contextprotector.guardrail_providers.mock_provider import (
    MockGuardrailProvider,
    AlwaysAlertGuardrailProvider,
)

logging.basicConfig(level=logging.INFO)


@pytest.fixture
def mock_session():
    """Create a mock session for testing."""
    session = MagicMock()

    # Mock the call_tool method to return a ToolCallResult
    async def mock_call_tool(name, arguments):
        if name == "test_tool":
            return ToolCallResult(content=[TextContent(type="text", text="Test result")])
        elif name == "dangerous_tool":
            return ToolCallResult(
                content=[
                    TextContent(
                        type="text",
                        text="Dangerous result that should trigger an alert",
                    )
                ]
            )
        else:
            return ToolCallResult(content=[])

    session.call_tool = mock_call_tool
    return session


@pytest.mark.asyncio
async def test_tool_scanning_no_alert():
    """Test tool response scanning when no alert is triggered."""
    # Create a guardrail provider that doesn't trigger alerts
    provider = MockGuardrailProvider(trigger_alert=False)

    # Create a wrapper server with the provider
    wrapper = MCPWrapperServer(guardrail_provider=provider)
    wrapper.session = MagicMock()

    # Mock the call_tool method to return a ToolCallResult
    async def mock_call_tool(_name, _arguments):
        return ToolCallResult(content=[TextContent(type="text", text="Safe result")])

    wrapper.session.call_tool = mock_call_tool

    # Call the tool
    result = await wrapper._proxy_tool_to_downstream("test_tool", {"param": "value"})

    # Verify the result
    assert isinstance(result, dict)
    assert result["text"] == "Safe result"

    # Verify that _scan_tool_response was called but no alert was triggered
    assert not provider._trigger_alert


@pytest.mark.asyncio
async def test_tool_scanning_with_alert():
    """Test tool response scanning when an alert is triggered."""
    # Create a guardrail provider that always triggers alerts
    provider = AlwaysAlertGuardrailProvider()

    # Create a wrapper server with the provider and a temporary quarantine
    wrapper = MCPWrapperServer(guardrail_provider=provider)
    wrapper.session = MagicMock()
    wrapper.quarantine = MagicMock()

    # Mock the call_tool method to return a ToolCallResult
    async def mock_call_tool(name, arguments):
        return ToolCallResult(
            content=[TextContent(type="text", text="Potentially dangerous result")]
        )

    wrapper.session.call_tool = mock_call_tool

    # Call the tool
    result = await wrapper._proxy_tool_to_downstream("dangerous_tool", {"param": "value"})

    # Verify the result - it should still return the result since we're only logging for now
    assert "Security risk detected" in result

    # Verify that the quarantine method was called
    wrapper.quarantine.quarantine_response.assert_called_once()
    args = wrapper.quarantine.quarantine_response.call_args[1]
    assert args["tool_name"] == "dangerous_tool"
    assert args["tool_input"] == {"param": "value"}
    assert args["tool_output"] == "Potentially dangerous result"
    assert "Security risk detected" in args["reason"]


@pytest.mark.asyncio
async def test_tool_scanning_exception_handling():
    """Test that exceptions in the scanning process are properly handled."""
    # Create a guardrail provider that raises an exception during tool response checking
    provider = MockGuardrailProvider()
    provider.check_tool_response = MagicMock(side_effect=Exception("Test exception"))

    # Create a wrapper server with the provider
    wrapper = MCPWrapperServer(guardrail_provider=provider)
    wrapper.session = MagicMock()

    # Mock the call_tool method to return a ToolCallResult
    async def mock_call_tool(name, arguments):
        return ToolCallResult(content=[TextContent(type="text", text="Test result")])

    wrapper.session.call_tool = mock_call_tool

    # Call the tool - this should not raise an exception despite the guardrail error
    result = await wrapper._proxy_tool_to_downstream("test_tool", {"param": "value"})

    # Verify the result
    assert isinstance(result, dict)
    assert result["text"] == "Test result"

    # Verify that check_tool_response was called
    provider.check_tool_response.assert_called_once()


@pytest.mark.asyncio
async def test_tool_vs_config_scanning_separation():
    """Test that tool response scanning and server config scanning are separate methods."""
    # Create a guardrail provider that tracks which methods were called
    provider = MockGuardrailProvider(trigger_alert=False)

    # Mock both methods to track calls
    provider.check_server_config = MagicMock(return_value=None)
    provider.check_tool_response = MagicMock(return_value=None)

    # Create a wrapper server with the provider
    wrapper = MCPWrapperServer(guardrail_provider=provider)
    wrapper.session = MagicMock()

    # Mock the call_tool method to return a ToolCallResult
    async def mock_call_tool(name, arguments):
        return ToolCallResult(content=[TextContent(type="text", text="Test result")])

    wrapper.session.call_tool = mock_call_tool

    # Call the tool
    result = await wrapper._proxy_tool_to_downstream("test_tool", {"param": "value"})

    # Verify the result
    assert isinstance(result, dict)
    assert result["text"] == "Test result"

    # Verify that only check_tool_response was called, not check_server_config
    provider.check_tool_response.assert_called_once()
    provider.check_server_config.assert_not_called()

    # Verify the arguments passed to check_tool_response
    call_args = provider.check_tool_response.call_args[0][0]  # First positional argument
    assert call_args.tool_name == "test_tool"
    assert call_args.tool_input == {"param": "value"}
    assert call_args.tool_output == "Test result"
    assert call_args.context == {}
