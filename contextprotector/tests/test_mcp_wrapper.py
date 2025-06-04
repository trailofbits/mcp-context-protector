"""
Tests for the MCP wrapper server.
"""

import json
import os
import tempfile
import subprocess
import pytest
import asyncio
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from pathlib import Path
from ..mcp_config import MCPServerConfig


async def approve_server_config_using_review(command, config_path):
    """
    Run the --review-server process to approve a server configuration.

    Args:
        server_config: The server configuration to approve
        command: The command to run the downstream server
    """
    # Run the review process
    review_process = subprocess.Popen(
        [
            "python",
            "-m",
            "contextprotector",
            "--review-server",
            "--command",
            command,
            "--config-file",
            config_path
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=Path(__file__).parent.parent.parent.resolve(),
        text=True
    )

    # Wait for the review process to start
    await asyncio.sleep(0.5)

    # Send 'y' to approve the configuration
    review_process.stdin.write("y\n")
    review_process.stdin.flush()

    # Wait for the review process to complete
    stdout, stderr = review_process.communicate(timeout=5)

    # Verify the review process output
    assert review_process.returncode == 0, f"Review process failed with return code {review_process.returncode}: {stderr}"

    # Check for expected output in the review process
    assert "has been trusted and saved" in stdout, f"Missing expected approval message in output: {stdout}"


async def run_with_wrapper_session(callback, config_path=None):
    """
    Run a test with a wrapper session that connects to the simple downstream server.
    """
    config_path = config_path or MCPServerConfig.get_default_config_path()
    dir = Path(__file__).resolve().parent
    server_params = StdioServerParameters(
        command="python",  # Executable
        args=[
            "-m",
            "contextprotector",
            "--command",
            f"python {str(dir.joinpath('simple_downstream_server.py'))}",
            "--config-file",
            str(config_path),
        ],  # Wrapper command + downstream server
        cwd=Path(__file__).parent.parent.parent.resolve(),
        env=None,  # Optional environment variables
    )
    async with stdio_client(server_params) as (read, write):
        assert read is not None and write is not None
        async with ClientSession(read, write) as session:
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

        # Should only have the echo tool
        assert sorted([t.name for t in tools.tools]) == ["echo"]

        # First try calling the echo tool - expect to get blocked
        result = await session.call_tool(name="echo", arguments={"message": input})
        assert len(result.content) == 1
        assert isinstance(result.content[0], types.TextContent)
        result_dict = json.loads(result.content[0].text)

        # Check that the call was blocked due to unapproved config
        assert isinstance(result_dict, dict) and result_dict["status"] == "blocked"

    async def callback2(session):
        input = "Marco (Polo)"
        
        # Call the echo tool again - should work now
        result = await session.call_tool(name="echo", arguments={"message": input})
        assert isinstance(result, types.CallToolResult)
        assert len(result.content) == 1
        assert isinstance(result.content[0], types.TextContent)

        # Parse the response
        response_json = json.loads(result.content[0].text)
        assert response_json["status"] == "completed"

        # The actual echo response should be in the response field
        response_data = json.loads(response_json["response"])
        assert response_data["echo_message"] == input

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    await run_with_wrapper_session(callback, temp_file.name)

    # Now we need to run the review process to approve this config
    await approve_server_config_using_review(
        f"python {str(Path(__file__).resolve().parent.joinpath('simple_downstream_server.py'))}",
        temp_file.name
    )
    await run_with_wrapper_session(callback2, temp_file.name)
    os.unlink(temp_file.name)
