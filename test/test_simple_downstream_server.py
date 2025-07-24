"""
Tests for the simple downstream MCP server with echo tool.
"""

import json
import pytest
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from pathlib import Path


async def run_with_session(callback: callable):
    dir = Path(__file__).resolve().parent
    server_params = StdioServerParameters(
        command="python",
        args=[
            str(dir.joinpath("simple_downstream_server.py"))
        ],  # Optional command line arguments
        env=None,  # Optional environment variables
    )

    async with stdio_client(server_params) as (read, write):
        assert read is not None and write is not None
        async with ClientSession(read, write) as session:
            await session.initialize()
            await callback(session)


@pytest.mark.asyncio
async def test_echo_tool():
    """Test that the echo tool correctly echoes the message."""

    async def callback(session):
        input = "Marco (Polo)"

        # List available tools
        tools = await session.list_tools()
        assert len(tools.tools) == 1 and tools.tools[0].name == "echo"

        result = await session.call_tool(name="echo", arguments={"message": input})
        assert type(result) is types.CallToolResult
        assert len(result.content) == 1
        assert type(result.content[0]) is types.TextContent
        assert json.loads(result.content[0].text) == {"echo_message": input}

    await run_with_session(callback)
