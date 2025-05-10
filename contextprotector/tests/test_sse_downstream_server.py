"""
Tests for the SSE downstream MCP server.
"""

import json
import asyncio
import logging
import pytest
import pytest_asyncio
import os
import sys
import psutil
from pathlib import Path

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.types import CallToolResult, TextContent

# Global variables to track server process and dynamic port
SERVER_PROCESS = None
SERVER_PORT = None
SERVER_PID = None


def get_ports_by_pid(pid):
    """
    Finds and returns a list of ports opened by a process ID.

    Args:
        pid (int): The process ID.

    Returns:
        list: A list of port numbers or an empty list if no ports are found.
    """
    try:
        process = psutil.Process(pid)
        connections = process.net_connections()
        ports = []
        for conn in connections:
            if conn.status == "LISTEN":
                ports.append(conn.laddr.port)
        return ports
    except psutil.NoSuchProcess:
        print(f"Process with PID {pid} not found.")
        return []
    except psutil.AccessDenied:
        print(f"Access denied to process with PID {pid}.")
        return []


async def start_sse_server():
    """Start the SSE downstream server in a separate process."""
    import subprocess
    import tempfile

    global SERVER_PROCESS, SERVER_PORT, SERVER_PID

    # Create a temporary file for the PID
    pid_file = tempfile.NamedTemporaryFile(delete=False)
    pid_file.close()

    # Get the path to the server script
    server_script = str(
        Path(__file__).resolve().parent.joinpath("simple_sse_server.py")
    )

    # Start the server process
    SERVER_PROCESS = subprocess.Popen(
        [sys.executable, server_script, "--pidfile", pid_file.name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Give the server time to start
    await asyncio.sleep(1.0)

    # Read the PID from the file to ensure the server started
    try:
        with open(pid_file.name, "r") as f:
            pid = int(f.read().strip())
            SERVER_PID = pid
            assert pid is not None
            logging.warning(f"SSE Server started with PID: {pid}")

            # Find which port the server is listening on
            max_attempts = 5
            for attempt in range(max_attempts):
                ports = get_ports_by_pid(pid)
                if ports:
                    SERVER_PORT = ports[0]  # Use the first port found
                    logging.warning(f"SSE Server is listening on port: {SERVER_PORT}")
                    break

                logging.warning(
                    f"Attempt {attempt + 1}/{max_attempts}: No ports found for PID {pid}, waiting..."
                )
                await asyncio.sleep(1.0)

            if not SERVER_PORT:
                print(f"Warning: Could not determine port for SSE server (PID {pid})")
    except (IOError, ValueError) as e:
        assert e is None
        logging.warning(f"Failed to read PID file: {e}")

    # Clean up the PID file
    try:
        os.unlink(pid_file.name)
    except OSError:
        pass

    return SERVER_PROCESS


async def stop_sse_server():
    """Stop the SSE downstream server process."""
    global SERVER_PROCESS, SERVER_PORT, SERVER_PID

    if SERVER_PROCESS:
        SERVER_PROCESS.terminate()
        await asyncio.sleep(0.5)

        # Make sure it's really gone
        if SERVER_PROCESS.poll() is None:
            SERVER_PROCESS.kill()

        SERVER_PROCESS = None
        SERVER_PORT = None
        SERVER_PID = None


@pytest_asyncio.fixture
async def sse_server():
    """Fixture to manage the SSE server lifecycle."""
    process = await start_sse_server()
    yield process
    await stop_sse_server()


async def run_with_sse_client(callback):
    """
    Run a test with a client that connects to the SSE downstream server.
    """
    global SERVER_PORT

    # Make sure we have a valid port
    assert SERVER_PORT is not None, "Server port must be detected before connecting"

    # Use the dynamically determined port
    server_url = f"http://localhost:{SERVER_PORT}/sse"
    print(f"Connecting to SSE server at: {server_url}")

    async with sse_client(server_url) as (read, write):
        assert read is not None and write is not None

        async with ClientSession(read, write) as session:
            assert session is not None
            await session.initialize()
            await callback(session)


@pytest.mark.asyncio
async def test_list_tools_via_sse(sse_server):
    """Test that the tool listing works correctly via SSE transport."""

    async def callback(session):
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


@pytest.mark.asyncio
async def test_echo_tool_via_sse(sse_server):
    """Test that the echo tool works correctly via SSE transport."""

    async def callback(session):
        # Test message to echo
        input_message = "Hello SSE MCP Server!"

        # Call the echo tool
        result = await session.call_tool(
            name="echo", arguments={"message": input_message}
        )

        # Verify the result
        assert isinstance(result, CallToolResult)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextContent)

        # Parse the response JSON
        response = json.loads(result.content[0].text)
        assert response["echo_message"] == input_message

        # Try another message
        second_message = "Testing SSE with a different message!"
        result2 = await session.call_tool(
            name="echo", arguments={"message": second_message}
        )
        response2 = json.loads(result2.content[0].text)
        assert response2["echo_message"] == second_message

    await run_with_sse_client(callback)


@pytest.mark.asyncio
async def test_invalid_tool_call_via_sse(sse_server):
    """Test error handling when an invalid tool is called via SSE transport."""

    async def callback(session):
        # Try to call a tool that doesn't exist
        result = await session.call_tool(
            name="nonexistent_tool", arguments={"foo": "bar"}
        )
        assert result.content and len(result.content) == 1
        assert result.content[0].text.startswith("Unknown tool")

        # Make sure a missing required parameter causes an error
        result = await session.call_tool(name="echo", arguments={})
        assert result.content and len(result.content) == 1
        text = result.content[0].text.lower()
        assert "error" in text and ("missing" in text or "required" in text)

    await run_with_sse_client(callback)
