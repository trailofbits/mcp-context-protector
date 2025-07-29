"""
Tests for the simple downstream MCP server with echo tool.
"""

import json
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


async def run_with_session(callback: callable) -> None:
    parent_dir = Path(__file__).resolve().parent
    server_params = StdioServerParameters(
        command="python",
        args=[str(parent_dir.joinpath("simple_downstream_server.py"))],  # Optional command line arguments
        env=None,  # Optional environment variables
    )

    async with stdio_client(server_params) as (read, write):
        assert read is not None
        assert write is not None
        async with ClientSession(read, write) as session:
            await session.initialize()
            await callback(session)


@pytest.mark.asyncio()
async def test_echo_tool() -> None:
    """Test that the echo tool correctly echoes the message."""

    async def callback(session: ClientSession) -> None:
        input_data = "Marco (Polo)"

        # List available tools
        tools = await session.list_tools()
        assert len(tools.tools) == 1
        assert tools.tools[0].name == "echo"

        result = await session.call_tool(name="echo", arguments={"message": input_data})
        assert type(result) is types.CallToolResult
        assert len(result.content) == 1
        assert type(result.content[0]) is types.TextContent
        assert json.loads(result.content[0].text) == {"echo_message": input_data}

    await run_with_session(callback)
