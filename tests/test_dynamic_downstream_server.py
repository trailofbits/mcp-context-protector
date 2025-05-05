"""
Tests for the dynamic downstream MCP server with signal-based tool updates.
"""

import asyncio
import json
import os
import pytest
import signal
import tempfile
import time
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from pathlib import Path

# Global variable to store PID for sending signals
SERVER_PID = None
# Global variable for temporary pidfile
TEMP_PIDFILE = None

async def verify_tools(session, expected_tool_names):
    """
    Verify that the session has the expected tools.

    Args:
        session: The client session to check
        expected_tool_names: List of tool names that should be present

    Returns:
        tools_list: The list of tools from the server
    """
    tools = await session.list_tools()
    assert len(tools.tools) == len(
        expected_tool_names
    ), f"Expected {len(expected_tool_names)} tools, got {len(tools.tools)}"

    # Check that all expected tools are present
    actual_names = [tool.name for tool in tools.tools]
    for name in expected_tool_names:
        assert name in actual_names, f"Expected tool '{name}' not found in tools list"

    return tools


async def send_sighup_and_wait(session, expected_tools):
    """
    Send SIGHUP to the server, wait for 2 seconds, then verify tools were updated.

    Args:
        session: The client session to check
        expected_tools: List of tool names that should be present after the update

    Returns:
        tools_list: The list of tools from the server after the update
    """
    # Send SIGHUP to the server
    os.kill(SERVER_PID, signal.SIGHUP)

    # Wait to allow the server to process the signal and update tools
    await asyncio.sleep(.5)

    # Verify that the tools list now contains the expected tools
    await verify_tools(session, expected_tools)


async def start_dynamic_server(callback: callable):
    """
    Start the dynamic server and run the provided callback with a client session.

    Args:
        callback: Function to call with the client session
    """
    global SERVER_PID, TEMP_PIDFILE

    # Create a temporary pidfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pid") as tmp:
        TEMP_PIDFILE = tmp.name

    dir = Path(__file__).resolve().parent
    server_params = StdioServerParameters(
        command="python",
        args=[
            str(dir.joinpath("dynamic_downstream_server.py")),
            "--pidfile",
            TEMP_PIDFILE,
        ],
        env=None,
    )

    async with stdio_client(server_params) as (read, write):
        assert read is not None and write is not None
        async with ClientSession(read, write) as session:
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


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_initial_tools():
    """Test that the dynamic server starts with the initial echo tool."""

    async def callback(session):
        await verify_tools(session, ["echo"])

        # Test the echo tool
        input_message = "Hello, dynamic server!"
        result = await session.call_tool(
            name="echo", arguments={"message": input_message}
        )

        assert type(result) is types.CallToolResult
        assert len(result.content) == 1
        assert type(result.content[0]) is types.TextContent

        response = json.loads(result.content[0].text)
        assert response == {"echo_message": input_message}

    await start_dynamic_server(callback)


@pytest.mark.asyncio
async def test_sighup_adds_tool():
    """Test that sending SIGHUP adds a new tool."""

    async def callback(session):
        # Check initial state - only echo tool should be present
        await verify_tools(session, ["echo"])
        
        # Send SIGHUP to add calculator tool and wait for it to be added
        await send_sighup_and_wait(session, ["echo", "calculator"])

        # Test the calculator tool
        result = await session.call_tool(
            name="calculator", arguments={"a": 10, "b": 5, "operation": "add"}
        )

        assert type(result) is types.CallToolResult
        assert len(result.content) == 1
        response = json.loads(result.content[0].text)
        assert response == {"result": 15}

        # Test another calculator operation
        result = await session.call_tool(
            name="calculator", arguments={"a": 10, "b": 5, "operation": "multiply"}
        )

        response = json.loads(result.content[0].text)
        assert response == {"result": 50}

    await start_dynamic_server(callback)


@pytest.mark.asyncio
async def test_multiple_sighups():
    """Test that multiple SIGHUPs add multiple tools."""

    async def callback(session):
        # Check initial state - only echo tool should be present
        await verify_tools(session, ["echo"])

        # Send first SIGHUP to add calculator tool
        await send_sighup_and_wait(session, ["echo", "calculator"])

        # Send second SIGHUP to add counter tool
        await send_sighup_and_wait(session, ["echo", "calculator", "counter"])

        # Test the counter tool
        result = await session.call_tool(name="counter", arguments={})

        assert type(result) is types.CallToolResult
        assert len(result.content) == 1
        response = json.loads(result.content[0].text)
        assert response == {"count": 3}  # Should reflect num_tools=3

        # Send third SIGHUP to add echo4 tool
        await send_sighup_and_wait(session, ["echo", "calculator", "counter", "echo4"])

    await start_dynamic_server(callback)