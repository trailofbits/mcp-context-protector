"""
Integration tests for the tool response quarantine functionality.
"""

import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from mcp.types import CallToolResult, TextContent

from contextprotector.guardrail_providers.mock_provider import AlwaysAlertGuardrailProvider
from contextprotector.mcp_wrapper import MCPWrapperServer
from contextprotector.quarantine import ToolResponseQuarantine


@pytest.fixture()
def temp_quarantine_file() -> Generator[str, None, None]:
    """Create a temporary quarantine file for testing."""
    tmp_file = tempfile.NamedTemporaryFile(delete=False)
    tmp_file.close()
    yield tmp_file.name
    if Path(tmp_file.name).exists():
        Path(tmp_file.name).unlink()


@pytest.mark.asyncio()
async def test_quarantine_integration(temp_quarantine_file: str) -> None:
    """Test that tool responses flagged by guardrails are properly quarantined."""
    # Create a guardrail provider that always triggers alerts
    provider = AlwaysAlertGuardrailProvider()

    # Create a wrapper server with the provider and a temporary quarantine
    wrapper = MCPWrapperServer(guardrail_provider=provider, quarantine_path=temp_quarantine_file)

    # Create a mock session
    wrapper.session = MagicMock()
    wrapper.config_approved = True

    # Mock the call_tool method to return a ToolCallResult
    original_response = "This is a potentially harmful tool response."

    async def mock_call_tool(_name: Any, _arguments: Any) -> CallToolResult:
        return CallToolResult(content=[TextContent(type="text", text=original_response)])

    wrapper.session.call_tool = mock_call_tool

    # Call the tool (this should trigger quarantine)
    tool_name = "dangerous_tool"
    tool_args = {"param": "value"}

    # Process the tool call
    response = await wrapper._proxy_tool_to_downstream(tool_name, tool_args)

    # Verify that the response was quarantined and replaced with a warning
    assert "quarantined" in response.lower()
    assert "prompt injection" in response.lower()

    # Verify that the quarantine database contains the quarantined response
    quarantine = ToolResponseQuarantine(temp_quarantine_file)
    responses = quarantine.list_responses()

    # We should have one quarantined response
    assert len(responses) == 1

    # Get the full response data
    response_id = responses[0]["id"]
    quarantined_response = quarantine.get_response(response_id)

    # Verify the quarantined response data
    assert quarantined_response.tool_name == tool_name
    assert quarantined_response.tool_input == tool_args
    assert quarantined_response.tool_output == original_response
    assert not quarantined_response.released

    # Release the response
    assert quarantine.release_response(response_id)

    # Verify it was marked as released
    quarantined_response = quarantine.get_response(response_id)
    assert quarantined_response.released
    assert quarantined_response.released_at is not None


@pytest.mark.asyncio()
async def test_quarantine_disabled_when_no_guardrails() -> None:
    """Test that quarantine is not used when guardrails are disabled."""
    # Create a wrapper server without guardrails
    wrapper = MCPWrapperServer()

    # Create a mock session
    wrapper.session = MagicMock()
    wrapper.config_approved = True

    # Mock the call_tool method to return a ToolCallResult
    original_response = "This is a normal tool response."

    async def mock_call_tool(_name: Any, _arguments: Any) -> CallToolResult:
        return CallToolResult(content=[TextContent(type="text", text=original_response)])

    wrapper.session.call_tool = mock_call_tool

    # Call the tool
    response = await wrapper._proxy_tool_to_downstream("normal_tool", {"param": "value"})

    # Verify that the original response is returned in the structured format
    assert isinstance(response, dict)
    assert response["text"] == original_response
    assert response["structured_content"] in [None, {}]

    # Verify that no quarantine database was created
    assert wrapper.quarantine is None
