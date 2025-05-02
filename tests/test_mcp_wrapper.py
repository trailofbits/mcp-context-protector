"""
Tests for the MCP wrapper server.
"""
import json
import os
import tempfile
import pytest
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from pathlib import Path
from ..mcp_config import MCPServerConfig

async def run_with_wrapper_session(callback, config_path=None):
    """
    Run a test with a wrapper session that connects to the simple downstream server.
    """
    config_path = config_path or MCPServerConfig.get_default_config_path()
    dir = Path(__file__).resolve().parent
    server_params = StdioServerParameters(
        command="python",  # Executable
        args=[
            str(Path(__file__).resolve().parent.parent.joinpath("mcp_wrapper.py")),
            f"python {str(dir.joinpath('simple_downstream_server.py'))}",
            str(config_path)
        ],  # Wrapper command + downstream server
        env=None,  # Optional environment variables
    )
    async with stdio_client(server_params) as (read, write):
        assert read is not None and write is not None
        async with ClientSession(
            read, write
        ) as session:
            assert session is not None
            await session.initialize()
            await callback(session)

@pytest.mark.asyncio
async def test_echo_tool_through_wrapper():
    """Test that the echo tool correctly works through the MCP wrapper."""
    async def callback(session):
        input = "Marco (Polo)"

        # List available tools
        tools = await session.list_tools()
        
        # Should have the echo tool, the add tool, and the approve_server_config tool
        assert len(tools.tools) == 2
        assert sorted([t.name for t in tools.tools]) == ["approve_server_config", "echo"]
        
        # First we need to approve the server config
        # Extract the server config
        server_config = None
        
        # Try to call echo tool - this should be blocked until config is approved
        result = await session.call_tool(name="echo", arguments={"message": input})
        assert len(result.content) == 1
        assert type(result.content[0]) is types.TextContent
        result_dict = json.loads(result.content[0].text)
        assert type(result_dict) is dict and result_dict["status"] == "blocked"
        server_config = result_dict["server_config"]
        # Approve the server config
        approval_result = await session.call_tool(
            name="approve_server_config", 
            arguments={"config": server_config}
        )
        assert type(approval_result) is types.CallToolResult
        approval_json = json.loads(approval_result.content[0].text)
        assert approval_json["status"] == "success"
        
        # Now call the echo tool again after config approval
        result = await session.call_tool(name="echo", arguments={"message": input})
        assert type(result) is types.CallToolResult
        assert len(result.content) == 1
        assert type(result.content[0]) is types.TextContent
        
        # Parse the response
        response_json = json.loads(result.content[0].text)
        assert response_json["status"] == "completed"
        
        # The actual echo response should be in the response field
        response_data = json.loads(response_json["response"])
        assert response_data["echo_message"] == input

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    await run_with_wrapper_session(callback, temp_file.name)
    os.unlink(temp_file.name)
