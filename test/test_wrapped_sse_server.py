"""
Tests for MCP wrapper with SSE downstream server.

Tests the integration between the MCP wrapper and the SSE server using HTTP transport.
"""

import json
import logging
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiofiles
import pytest
from mcp import ClientSession, types

from .sse_server_utils import sse_server_fixture  # noqa: F401
from .test_utils import approve_server_config_using_review as _approve_config


# Local helper function for backward compatibility
async def approve_server_config_using_review(url: str, config_path: str) -> None:
    """
    Run the --review-server process to approve a server configuration.

    Args:
        url: The URL of the downstream server
        config_path: Path to the configuration file
    """
    await _approve_config("sse", url, config_path)


# Import global SERVER_PORT from sse_server_utils


# Helper function to run tests with the SSE server
async def _run_with_sse_server(
    callback: Callable[[ClientSession], Awaitable[None]], config_path: str
) -> None:
    """Helper to run tests with the SSE server at the detected port."""
    from . import sse_server_utils
    from .test_utils import run_with_sse_downstream_server

    # Make sure we have a valid port
    assert (
        sse_server_utils.SERVER_PORT is not None
    ), "Server port must be detected before connecting"

    logging.warning("Connecting wrapper to SSE server at port: %s", sse_server_utils.SERVER_PORT)

    # Use the shared utility function
    await run_with_sse_downstream_server(callback, sse_server_utils.SERVER_PORT, config_path)


@pytest.mark.asyncio()
async def test_echo_tool_through_wrapper(sse_server_fixture: any) -> None:  # noqa: F811 ARG001
    """Test that the echo tool correctly works through the MCP wrapper using SSE transport."""

    async def callback(session: ClientSession) -> None:
        input_message = "Hello from Wrapped SSE Server!"

        # List available tools
        tools = await session.list_tools()

        # Should only have the context-protector-block tool when config is unapproved
        assert sorted([t.name for t in tools.tools]) == ["context-protector-block"]

        # First try calling the echo tool - expect to get blocked
        result = await session.call_tool(name="echo", arguments={"message": input_message})
        assert len(result.content) == 1
        assert isinstance(result.content[0], types.TextContent)
        result_dict = json.loads(result.content[0].text)

        # Check that the call was blocked due to unapproved config
        assert isinstance(result_dict, dict)
        assert result_dict["status"] == "blocked"
        # Note: server_config is no longer included to prevent information leakage

    async def callback2(session: ClientSession) -> None:
        input_message = "Hello from Wrapped SSE Server!"
        # After approval, reconnect and try again

        # Call the echo tool again - should work now
        result = await session.call_tool(name="echo", arguments={"message": input_message})
        assert isinstance(result, types.CallToolResult)
        assert len(result.content) == 1
        assert isinstance(result.content[0], types.TextContent)

        # Parse the response
        response_json = json.loads(result.content[0].text)
        assert response_json["status"] == "completed"

        # The actual echo response should be in the response field
        response_data = json.loads(response_json["response"])
        assert response_data["echo_message"] == input_message

        # Try with a different message to ensure consistent behavior
        second_message = "Testing with a second message"
        result2 = await session.call_tool(name="echo", arguments={"message": second_message})
        response_json2 = json.loads(result2.content[0].text)
        response_data2 = json.loads(response_json2["response"])
        assert response_data2["echo_message"] == second_message

    # Run the test with a temporary config file
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    await _run_with_sse_server(callback, temp_file.name)
    # Build the URL for the SSE server to be used in the review process
    from . import sse_server_utils

    sse_url = f"http://localhost:{sse_server_utils.SERVER_PORT}/sse"

    # Now we need to run the review process to approve this config
    await approve_server_config_using_review(sse_url, temp_file.name)

    async with aiofiles.open(temp_file.name, "r") as f:
        logging.exception(await f.read())
    from contextprotector.mcp_config import MCPConfigDatabase

    cdb = MCPConfigDatabase(temp_file.name)
    conf = cdb.get_server_config("sse", sse_url)
    assert conf is not None, "couldn't find approved config"

    await _run_with_sse_server(callback2, temp_file.name)

    Path(temp_file.name).unlink()


@pytest.mark.asyncio()
async def test_invalid_tool_through_wrapper(sse_server_fixture: any) -> None:  # noqa: F811 ARG001
    """Test error handling for invalid tools through the MCP wrapper using SSE transport."""

    async def callback(session: ClientSession) -> None:
        # First try calling any tool to get blocked and receive the config
        result = await session.call_tool(name="echo", arguments={"message": "Test"})
        assert len(result.content) == 1
        result_dict = json.loads(result.content[0].text)
        assert result_dict["status"] == "blocked"

    async def callback2(session: ClientSession) -> None:
        # Now try to call a tool that doesn't exist
        result = await session.call_tool(name="nonexistent_tool", arguments={"foo": "bar"})
        assert isinstance(result, types.CallToolResult)
        response_json = json.loads(result.content[0].text)

        # The wrapper should return a formatted error response
        assert response_json["status"] == "completed" or "error" in response_json

        # If status is completed, check the error message from the downstream server
        if response_json["status"] == "completed":
            assert (
                "Unknown tool" in response_json["response"]
                or "not found" in response_json["response"]
            )

        # Make sure a missing required parameter is properly handled
        result = await session.call_tool(name="echo", arguments={})
        response_json = json.loads(result.content[0].text)

        # The wrapper should again return a formatted response
        assert response_json["status"] == "completed" or "error" in response_json

        # Check that the error message mentions the missing parameter
        if response_json["status"] == "completed":
            assert (
                "missing" in response_json["response"].lower()
                or "required" in response_json["response"].lower()
            )

    # Run the test with a temporary config file
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    await _run_with_sse_server(callback, temp_file.name)
    # Build the URL for the SSE server to be used in the review process
    from . import sse_server_utils

    sse_url = f"http://localhost:{sse_server_utils.SERVER_PORT}/sse"

    # Run the review process to approve this config
    await approve_server_config_using_review(sse_url, temp_file.name)
    await _run_with_sse_server(callback2, temp_file.name)
    Path(temp_file.name).unlink()
