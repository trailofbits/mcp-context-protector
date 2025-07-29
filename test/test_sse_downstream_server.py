"""
Tests for the SSE downstream MCP server.
"""

import json

import pytest
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import CallToolResult, TextContent

from .sse_server_utils import sse_server  # noqa: F401


async def run_with_sse_client(callback) -> None:
    """
    Run a test with a client that connects to the SSE downstream server.
    """
    from . import sse_server_utils

    # Make sure we have a valid port
    assert (
        sse_server_utils.SERVER_PORT is not None
    ), "Server port must be detected before connecting"

    # Use the dynamically determined port
    server_url = f"http://localhost:{sse_server_utils.SERVER_PORT}/sse"
    print(f"Connecting to SSE server at: {server_url}")

    async with sse_client(server_url) as (read, write):
        assert read is not None
        assert write is not None

        async with ClientSession(read, write) as session:
            assert session is not None
            await session.initialize()
            await callback(session)


@pytest.mark.asyncio()
async def test_list_tools_via_sse(sse_server: any) -> None: # noqa: ARG001
    """Test that the tool listing works correctly via SSE transport."""

    async def callback(session: ClientSession) -> None:
        # List available tools
        tools = await session.list_tools()

        # Verify we have our echo tool
        assert len(tools.tools) == 1
        assert tools.tools[0].name == "echo"

        # Verify the tool schema
        tool = tools.tools[0]
        assert tool.description.strip().startswith(
            "Echo handler function that returns the input message."
        )
        assert "properties" in tool.inputSchema
        assert "message" in tool.inputSchema["properties"]
        assert tool.inputSchema["properties"]["message"]["type"] == "string"
        assert "required" in tool.inputSchema
        assert "message" in tool.inputSchema["required"]

    await run_with_sse_client(callback)


@pytest.mark.asyncio()
async def test_echo_tool_via_sse(sse_server: any) -> None: # noqa: ARG001
    """Test that the echo tool works correctly via SSE transport."""

    async def callback(session: ClientSession) -> None:
        # Test message to echo
        input_message = "Hello SSE MCP Server!"

        # Call the echo tool
        result = await session.call_tool(name="echo", arguments={"message": input_message})

        # Verify the result
        assert isinstance(result, CallToolResult)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)

        # Parse the response JSON
        response = json.loads(result.content[0].text)
        assert response["echo_message"] == input_message

        # Try another message
        second_message = "Testing SSE with a different message!"
        result2 = await session.call_tool(name="echo", arguments={"message": second_message})
        response2 = json.loads(result2.content[0].text)
        assert response2["echo_message"] == second_message

    await run_with_sse_client(callback)


@pytest.mark.asyncio()
async def test_invalid_tool_call_via_sse(sse_server: any) -> None: # noqa: ARG001
    """Test error handling when an invalid tool is called via SSE transport."""

    async def callback(session: ClientSession) -> None:
        # Try to call a tool that doesn't exist
        result = await session.call_tool(name="nonexistent_tool", arguments={"foo": "bar"})
        assert result.content
        assert len(result.content) == 1
        assert result.content[0].text.startswith("Unknown tool")

        # Make sure a missing required parameter causes an error
        result = await session.call_tool(name="echo", arguments={})
        assert result.content
        assert len(result.content) == 1
        text = result.content[0].text.lower()
        assert "error" in text
        assert ("missing" in text or "required" in text)

    await run_with_sse_client(callback)
