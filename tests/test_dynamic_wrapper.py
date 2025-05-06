"""
Tests for MCP wrapper with dynamic downstream server.

Tests the behavior of the MCP wrapper when the dynamic server updates its tools via SIGHUP signals.
"""

import asyncio
import json
import os
import signal
import tempfile
import time
from pathlib import Path
import pytest

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from ..mcp_config import MCPServerConfig

# Global variables for server process
SERVER_PID = None
TEMP_PIDFILE = None


async def run_with_dynamic_wrapper_session(callback, config_path=None):
    """
    Run a test with a wrapper session that connects to the dynamic downstream server.

    Args:
        callback: Async function to call with the client session.
        config_path: Path to the config file for the wrapper. If None, uses a temporary file.

    Returns:
        None
    """
    global SERVER_PID, TEMP_PIDFILE

    # Create a temporary pidfile for the dynamic server
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pid") as tmp:
        TEMP_PIDFILE = tmp.name

    config_path = config_path or MCPServerConfig.get_default_config_path()
    dir = Path(__file__).resolve().parent

    # Construct the command for the dynamic server
    dynamic_server_cmd = f"python {str(dir.joinpath('dynamic_downstream_server.py'))} --pidfile {TEMP_PIDFILE}"

    # Construct the wrapper server parameters
    server_params = StdioServerParameters(
        command="python",  # Executable
        args=[
            str(Path(__file__).resolve().parent.parent.joinpath("mcp_wrapper.py")),
            dynamic_server_cmd,
            str(config_path),
        ],  # Wrapper command + downstream server
        env=None,  # Optional environment variables
    )

    async with stdio_client(server_params) as (read, write):
        assert read is not None and write is not None
        async with ClientSession(read, write) as session:
            assert session is not None
            await session.initialize()

            # Get the server PID from the pidfile
            max_attempts = 10
            attempts = 0
            while attempts < max_attempts:
                try:
                    with open(TEMP_PIDFILE, "r") as f:
                        SERVER_PID = int(f.read().strip())
                    break
                except (FileNotFoundError, ValueError):
                    # Wait for the pidfile to be created
                    attempts += 1
                    time.sleep(0.1)

            assert SERVER_PID is not None, f"Failed to read PID from {TEMP_PIDFILE}"

            # Run the test callback with the session
            await callback(session)


def cleanup_pidfile():
    """Clean up the temporary pidfile if it exists."""
    global TEMP_PIDFILE
    if TEMP_PIDFILE and os.path.exists(TEMP_PIDFILE):
        try:
            os.unlink(TEMP_PIDFILE)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def cleanup_after_test():
    """Fixture to clean up resources after each test."""
    yield
    cleanup_pidfile()


async def send_sighup_and_wait():
    """
    Send SIGHUP to the dynamic server and wait a moment for processing.

    Args:
        None

    Returns:
        None
    """
    # Send SIGHUP to the dynamic server
    os.kill(SERVER_PID, signal.SIGHUP)

    # Wait to allow the server to process the signal and update tools
    await asyncio.sleep(0.5)


async def get_tool_names(session):
    """
    Get a sorted list of tool names from the session.

    Args:
        session: The client session

    Returns:
        List of tool names, sorted alphabetically
    """
    tools = await session.list_tools()
    return sorted([tool.name for tool in tools.tools])


@pytest.mark.asyncio
async def test_sighup_causes_tool_blocking():
    """Test that when SIGHUP is received, tool calls are blocked until config is approved."""

    async def callback(session):
        # Initial state should have approve_server_config and echo tools
        tool_names = await get_tool_names(session)
        assert tool_names == ["approve_server_config", "echo"]

        # First we need to approve the initial config
        # Try to call echo tool - this should be blocked until config is approved
        input_message = "Hello from dynamic wrapper test"
        result = await session.call_tool(
            name="echo", arguments={"message": input_message}
        )

        # Verify it's blocked
        assert len(result.content) == 1
        assert isinstance(result.content[0], types.TextContent)
        result_dict = json.loads(result.content[0].text)
        assert isinstance(result_dict, dict) and result_dict["status"] == "blocked"

        # Get the server config and approve it
        server_config = result_dict["server_config"]
        approval_result = await session.call_tool(
            name="approve_server_config", arguments={"config": server_config}
        )
        assert type(approval_result) is types.CallToolResult
        approval_json = json.loads(approval_result.content[0].text)
        assert approval_json["status"] == "success"

        # Now echo tool should work
        result = await session.call_tool(
            name="echo", arguments={"message": input_message}
        )
        assert type(result) is types.CallToolResult
        response_json = json.loads(result.content[0].text)
        assert response_json["status"] == "completed"
        response_data = json.loads(response_json["response"])
        assert response_data["echo_message"] == input_message

        # Now send SIGHUP to add a new tool
        await send_sighup_and_wait()

        # Tool list should still include the existing and new tools
        tool_names = await get_tool_names(session)
        assert "calculator" in tool_names
        assert tool_names == ["approve_server_config", "calculator", "echo"]

        # Try to call the echo tool again - it should now be blocked due to config change
        result = await session.call_tool(
            name="echo", arguments={"message": input_message}
        )
        assert len(result.content) == 1
        result_dict = json.loads(result.content[0].text)
        assert result_dict["status"] == "blocked"

        # Try to call the new calculator tool - should also be blocked
        result = await session.call_tool(
            name="calculator", arguments={"a": 5, "b": 7, "operation": "add"}
        )
        assert len(result.content) == 1
        result_dict = json.loads(result.content[0].text)
        assert result_dict["status"] == "blocked"

        # Get the updated server config for the next test
        updated_server_config = result_dict["server_config"]
        return updated_server_config

    # Run the test with a temporary config file
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    updated_config = await run_with_dynamic_wrapper_session(callback, temp_file.name)
    os.unlink(temp_file.name)

    # Return the updated config for the next test to use
    return updated_config


@pytest.mark.asyncio
async def test_approve_server_config_after_sighup():
    """Test that after SIGHUP, tool calls can be unblocked by approving the updated config."""

    async def callback(session):
        # Initial state should have approve_server_config and echo tools
        tool_names = await get_tool_names(session)
        assert tool_names == ["approve_server_config", "echo"]

        # First approve the initial config
        input_message = "Hello from the dynamic server"
        result = await session.call_tool(
            name="echo", arguments={"message": input_message}
        )
        server_config = json.loads(result.content[0].text)["server_config"]

        await session.call_tool(
            name="approve_server_config", arguments={"config": server_config}
        )

        # Send SIGHUP to add the calculator tool
        await send_sighup_and_wait()

        # Verify the calculator tool is now in the tools list
        tool_names = await get_tool_names(session)
        assert "calculator" in tool_names
        assert tool_names == ["approve_server_config", "calculator", "echo"]

        # Try to call the calculator tool - it should be blocked
        result = await session.call_tool(
            name="calculator", arguments={"a": 10, "b": 5, "operation": "subtract"}
        )
        assert len(result.content) == 1
        result_dict = json.loads(result.content[0].text)
        assert result_dict["status"] == "blocked"

        # Get the updated server config and approve it
        updated_server_config = result_dict["server_config"]
        approval_result = await session.call_tool(
            name="approve_server_config", arguments={"config": updated_server_config}
        )
        approval_json = json.loads(approval_result.content[0].text)
        assert approval_json["status"] == "success"

        # Now calculator tool should work
        result = await session.call_tool(
            name="calculator", arguments={"a": 10, "b": 5, "operation": "subtract"}
        )
        assert type(result) is types.CallToolResult
        response_json = json.loads(result.content[0].text)
        assert response_json["status"] == "completed"

        # Parse the calculator response
        response_data = json.loads(response_json["response"])
        assert response_data["result"] == 5

        # Echo tool should also work
        result = await session.call_tool(
            name="echo", arguments={"message": input_message}
        )
        assert type(result) is types.CallToolResult
        response_json = json.loads(result.content[0].text)
        assert response_json["status"] == "completed"
        response_data = json.loads(response_json["response"])
        assert response_data["echo_message"] == input_message

        # Send SIGHUP again to add the counter tool
        await send_sighup_and_wait()

        # Save the config with 3 tools for the next test
        result = await session.call_tool(
            name="echo", arguments={"message": input_message}
        )
        config_with_counter = json.loads(result.content[0].text)["server_config"]
        return config_with_counter

    # Run the test with a temporary config file
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    config_with_counter = await run_with_dynamic_wrapper_session(
        callback, temp_file.name
    )
    os.unlink(temp_file.name)

    # Return the config with 3 tools (echo, calculator, counter) for the next test
    return config_with_counter


@pytest.mark.asyncio
async def test_outdated_config_approval_fails():
    """
    Test that trying to approve an outdated server config after multiple SIGHUPs fails.

    This tests the scenario where:
    1. We start with 1 tool (echo)
    2. SIGHUP adds a second tool (calculator) - we capture config but don't approve yet
    3. SIGHUP adds a third tool (counter)
    4. Try to approve the cached config with 2 tools - this should fail
    5. Get the current config with 3 tools and approve it - this should succeed
    """
    # Run the previous test to ensure the server is in a known state
    await test_approve_server_config_after_sighup()

    async def callback(session):
        # Initial state should have approve_server_config and echo tools
        tool_names = await get_tool_names(session)
        assert tool_names == ["approve_server_config", "echo"]

        # First approve the initial config
        input_message = "Hello from multiple SIGHUPs test"
        result = await session.call_tool(
            name="echo", arguments={"message": input_message}
        )
        server_config = json.loads(result.content[0].text)["server_config"]

        await session.call_tool(
            name="approve_server_config", arguments={"config": server_config}
        )

        # Send SIGHUP to add calculator tool
        await send_sighup_and_wait()

        # Try to call calculator to get the updated config (with 2 tools)
        result = await session.call_tool(
            name="calculator", arguments={"a": 10, "b": 5, "operation": "multiply"}
        )
        # Extract the config with echo + calculator (2 tools)
        config_with_calculator = json.loads(result.content[0].text)["server_config"]

        # Send another SIGHUP to add counter tool
        await send_sighup_and_wait()

        # Verify we now have 3 tools
        tool_names = await get_tool_names(session)
        assert len(tool_names) == 4  # 3 tools + approve_server_config
        assert "counter" in tool_names

        # Try to approve the outdated config (with just calculator, not counter)
        approval_result = await session.call_tool(
            name="approve_server_config", arguments={"config": config_with_calculator}
        )
        approval_json = json.loads(approval_result.content[0].text)
        # This should fail because the config is outdated
        assert approval_json["status"] == "failed"

        # Get the current config with all 3 tools
        result = await session.call_tool(
            name="echo", arguments={"message": input_message}
        )
        current_config = json.loads(result.content[0].text)["server_config"]

        # Approve the current config
        approval_result = await session.call_tool(
            name="approve_server_config", arguments={"config": current_config}
        )
        approval_json = json.loads(approval_result.content[0].text)
        assert approval_json["status"] == "success"

        # Verify we can use the counter tool now
        result = await session.call_tool(name="counter", arguments={})
        assert type(result) is types.CallToolResult
        response_json = json.loads(result.content[0].text)
        assert response_json["status"] == "completed"

        # Verify the counter reports 3 tools
        response_data = json.loads(response_json["response"])
        assert response_data["count"] == 3

    # Run the test with a temporary config file
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    await run_with_dynamic_wrapper_session(callback, temp_file.name)
    os.unlink(temp_file.name)
