"""
Tests for MCP wrapper with dynamic downstream server.

Tests the behavior of the dynamic server with tool count configuration.
"""

import aiofiles
import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Awaitable, Callable, Generator
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

# Global variables for server process
SERVER_PID = None
TEMP_PIDFILE = None
TEMP_TOOLCOUNT_FILE = None
TEMP_CONFIG_FILE = None


def write_tool_count(count: int) -> str:
    """
    Write the specified tool count to a temporary file.

    Args:
        count: The number of tools to write to the file

    Returns:
        str: Path to the temporary file
    """
    global TEMP_TOOLCOUNT_FILE

    # Create a temporary file for the tool count
    with tempfile.NamedTemporaryFile(delete=False, suffix=".count") as tmp:
        TEMP_TOOLCOUNT_FILE = tmp.name
        tmp.write(str(count).encode("utf-8"))

    return TEMP_TOOLCOUNT_FILE


def create_approved_config(server_cmd: str) -> str:
    """
    Create a pre-approved configuration for the server to avoid blocking.

    Args:
        server_cmd: The server command to create a config for

    Returns:
        str: Path to the temporary config file
    """
    global TEMP_CONFIG_FILE

    # Create a temporary config file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
        TEMP_CONFIG_FILE = tmp.name

    # Use the review command to pre-approve the server config
    subprocess.run(
        [
            sys.executable,
            "-m",
            "contextprotector",
            "--command",
            server_cmd,
            "--server-config-file",
            TEMP_CONFIG_FILE,
            "--review-server",
            "yes",
        ],
        cwd=Path(__file__).parent.parent.parent.resolve(),
        check=True,
    )

    return TEMP_CONFIG_FILE


async def run_with_dynamic_server_session(callback: Callable[[ClientSession], Awaitable[None]], initial_tool_count: int | None = None) -> None:
    """
    Run a test with a direct connection to the dynamic downstream server.

    Args:
        callback: Async function to call with the client session.
        initial_tool_count: Number of tools to pre-configure in the dynamic server.

    Returns:
        None
    """
    global SERVER_PID, TEMP_PIDFILE, TEMP_TOOLCOUNT_FILE, TEMP_CONFIG_FILE

    # Create a temporary pidfile for the dynamic server
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pid") as tmp:
        TEMP_PIDFILE = tmp.name

    parent_dir = Path(__file__).resolve().parent

    # Construct the base command for the dynamic server
    args = [
        str(parent_dir.joinpath("dynamic_downstream_server.py")),
        "--pidfile",
        TEMP_PIDFILE,
    ]

    # Add toolcount-file if specified
    if initial_tool_count is not None:
        toolcount_file = write_tool_count(initial_tool_count)
        args.extend(["--toolcount-file", toolcount_file])

    # Construct the server parameters
    server_params = StdioServerParameters(
        command="python",  # Executable
        args=args,
        env=None,  # Optional environment variables
    )

    async with stdio_client(server_params) as (read, write):
        assert read is not None
        assert write is not None
        async with ClientSession(read, write) as session:
            assert session is not None
            await session.initialize()

            # Get the server PID from the pidfile
            max_attempts = 10
            attempts = 0
            while attempts < max_attempts:
                try:
                    async with aiofiles.open(TEMP_PIDFILE, "r") as f:
                        SERVER_PID = int((await f.read()).strip())
                    break
                except (FileNotFoundError, ValueError):
                    # Wait for the pidfile to be created
                    attempts += 1
                    await asyncio.sleep(0.1)

            assert SERVER_PID is not None, f"Failed to read PID from {TEMP_PIDFILE}"

            # Run the test callback with the session
            await callback(session)


def cleanup_files() -> None:
    """Clean up the temporary files if they exist."""
    global TEMP_PIDFILE, TEMP_TOOLCOUNT_FILE, TEMP_CONFIG_FILE

    for file_path in [TEMP_PIDFILE, TEMP_TOOLCOUNT_FILE, TEMP_CONFIG_FILE]:
        if file_path and Path(file_path).exists():
            try:
                Path(file_path).unlink()
            except OSError:
                pass


@pytest.fixture(autouse=True)
def _cleanup_after_test() -> Generator[None, None, None]:
    """Fixture to clean up resources after each test."""
    yield
    cleanup_files()


async def send_sighup_and_wait() -> None:
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


async def get_tool_names(session: ClientSession) -> list[str]:
    """
    Get a sorted list of tool names from the session.

    Args:
        session: The client session

    Returns:
        List of tool names, sorted alphabetically
    """
    tools = await session.list_tools()
    tool_names = [tool.name for tool in tools.tools]
    return sorted(tool_names)


@pytest.mark.asyncio()
async def test_initial_tools() -> None:
    """Test that the dynamic server starts with the expected initial tools."""

    async def callback(session: ClientSession) -> None:
        # Initial state should have echo tool
        tool_names = await get_tool_names(session)
        assert tool_names == ["echo"]

        # Test that the echo tool functions correctly
        input_message = "Hello from dynamic server test"
        result = await session.call_tool(name="echo", arguments={"message": input_message})

        # Parse the response
        assert isinstance(result, types.CallToolResult)
        assert len(result.content) == 1
        assert isinstance(result.content[0], types.TextContent)

        # Parse the text content
        response = json.loads(result.content[0].text)
        assert response["echo_message"] == input_message

    # Run the test with default configuration (1 tool)
    await run_with_dynamic_server_session(callback)


@pytest.mark.asyncio()
async def test_preconfigured_tools() -> None:
    """Test that the dynamic server can start with multiple tools via configuration file."""

    async def callback(session: ClientSession) -> None:
        # Initial state should have multiple tools
        tool_names = await get_tool_names(session)
        assert sorted(tool_names) == ["calculator", "counter", "echo"]

        # Test the echo tool
        input_message = "Hello from preconfigured server"
        result = await session.call_tool(name="echo", arguments={"message": input_message})
        response = json.loads(result.content[0].text)
        assert response["echo_message"] == input_message

        # Test the calculator tool
        result = await session.call_tool(
            name="calculator", arguments={"a": 10, "b": 5, "operation": "add"}
        )
        response = json.loads(result.content[0].text)
        assert response["result"] == 15

        # Test the counter tool
        result = await session.call_tool(name="counter", arguments={})
        response = json.loads(result.content[0].text)
        assert response["count"] == 3  # Should be 3 tools

    # Run the test with a preconfigured server (3 tools)
    await run_with_dynamic_server_session(callback, initial_tool_count=3)


@pytest.mark.asyncio()
async def test_sighup_adds_tool() -> None:
    """Test that sending SIGHUP adds a new tool."""

    async def callback(session: ClientSession) -> None:
        # Check initial state - only echo tool should be present
        tool_names = await get_tool_names(session)
        assert tool_names == ["echo"]

        # Try echo tool first - should work
        input_message = "Hello from dynamic server!"
        result = await session.call_tool(name="echo", arguments={"message": input_message})
        response = json.loads(result.content[0].text)
        assert response["echo_message"] == input_message

        # Send SIGHUP to add calculator tool
        await send_sighup_and_wait()

        # Verify the calculator tool is now in the tools list
        tool_names = await get_tool_names(session)
        assert "calculator" in tool_names
        assert sorted(tool_names) == ["calculator", "echo"]

        # Test the calculator tool
        result = await session.call_tool(
            name="calculator", arguments={"a": 10, "b": 5, "operation": "subtract"}
        )
        response = json.loads(result.content[0].text)
        assert response["result"] == 5

    # Run the test with direct connection to the dynamic server
    await run_with_dynamic_server_session(callback)


@pytest.mark.asyncio()
async def test_multiple_sighups() -> None:
    """Test that multiple SIGHUPs add multiple tools."""

    async def callback(session: ClientSession) -> None:
        # Check initial state with two tools
        tool_names = await get_tool_names(session)
        assert sorted(tool_names) == ["calculator", "echo"]

        # Test calculator - should work
        result = await session.call_tool(
            name="calculator", arguments={"a": 5, "b": 7, "operation": "multiply"}
        )
        response = json.loads(result.content[0].text)
        assert response["result"] == 35

        # Send SIGHUP to add counter tool
        await send_sighup_and_wait()

        # Verify we now have 3 tools
        tool_names = await get_tool_names(session)
        assert sorted(tool_names) == ["calculator", "counter", "echo"]

        # Test counter
        result = await session.call_tool(name="counter", arguments={})
        response = json.loads(result.content[0].text)
        assert response["count"] == 3  # Should show 3 tools

        # Send another SIGHUP to add echo4
        await send_sighup_and_wait()

        # Verify we now have 4 tools
        tool_names = await get_tool_names(session)
        assert sorted(tool_names) == ["calculator", "counter", "echo", "echo4"]

        # Test echo4
        result = await session.call_tool(name="echo4", arguments={"message": "Testing echo4"})
        response = json.loads(result.content[0].text)
        assert response["echo_message"] == "Testing echo4"
        assert response["tool_number"] == 4

    # Run the test with a preconfigured server (2 tools)
    await run_with_dynamic_server_session(callback, initial_tool_count=2)
