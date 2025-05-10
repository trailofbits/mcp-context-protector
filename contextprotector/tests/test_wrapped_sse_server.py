"""
Tests for MCP wrapper with SSE downstream server.

Tests the integration between the MCP wrapper and the SSE server using HTTP transport.
"""

import json
import asyncio
import logging
import os
import pytest
import pytest_asyncio
import sys
import tempfile
import psutil
import subprocess
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from ..mcp_config import MCPServerConfig


async def approve_server_config_using_review(url, config_path):
    """
    Run the --review process to approve a server configuration.

    Args:
        server_config: The server configuration to approve
        url: The URL of the downstream server
    """
    root_dir = Path(__file__).resolve().parent.parent.parent
    main_py = str(root_dir.joinpath("main.py"))

    # Run the review process
    review_process = subprocess.Popen(
        [
            "python",
            main_py,
            "--review",
            "--url",
            url,
            "--config-file",
            config_path
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Wait for the review process to start
    await asyncio.sleep(1.5)

    # Send 'y' to approve the configuration
    review_process.stdin.write("y\n")
    review_process.stdin.flush()

    # Wait for the review process to complete
    stdout, stderr = review_process.communicate(timeout=5)

    # Verify the review process output
    assert review_process.returncode == 0, f"Review process failed with return code {review_process.returncode}: {stderr}"

    # Check for expected output in the review process
    assert "has been trusted and saved" in stdout, f"Missing expected approval message in output: {stdout}"

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
        logging.warning(f"Process with PID {pid} not found.")
        return []
    except psutil.AccessDenied:
        logging.warning(f"Access denied to process with PID {pid}.")
        return []


async def start_sse_server():
    """Start the SSE downstream server in a separate process."""
    import subprocess

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

            assert SERVER_PORT is not None, "Could not determine port for SSE server"
    except (IOError, ValueError) as e:
        assert False, f"Failed to read PID file: {e}"

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


async def run_with_wrapper_session(callback, config_path=None):
    """
    Run a test with a wrapper session that connects to the SSE downstream server via URL.

    Args:
        callback: Async function to call with the client session
        config_path: Path to the wrapper config file
    """
    global SERVER_PORT

    # Make sure we have a valid port
    assert SERVER_PORT is not None, "Server port must be detected before connecting"

    config_path = config_path or MCPServerConfig.get_default_config_path()

    # Build the URL for the SSE server
    sse_url = f"http://localhost:{SERVER_PORT}/sse"
    logging.warning(f"Connecting wrapper to SSE server at: {sse_url}")

    # Construct the wrapper server parameters
    server_params = StdioServerParameters(
        command="python",  # Executable
        args=[
            str(Path(__file__).resolve().parent.parent.parent.joinpath("main.py")),
            "--url",
            sse_url,
            "--config-file",
            str(config_path),
        ],  # Wrapper command + downstream server URL
        env=None,  # Optional environment variables
    )
    logging.warning(f"args: {server_params}")
    async with stdio_client(server_params) as (read, write):
        assert read is not None and write is not None
        async with ClientSession(read, write) as session:
            assert session is not None
            await session.initialize()
            await callback(session)


@pytest_asyncio.fixture
async def sse_server_fixture():
    """Fixture to manage the SSE server lifecycle."""
    process = await start_sse_server()
    yield process
    await stop_sse_server()


@pytest.mark.asyncio
async def test_echo_tool_through_wrapper(sse_server_fixture):
    """Test that the echo tool correctly works through the MCP wrapper using SSE transport."""
    sc = None
    async def callback(session):
        nonlocal sc

        input_message = "Hello from Wrapped SSE Server!"

        # List available tools
        tools = await session.list_tools()

        # Should only have the echo tool
        assert sorted([t.name for t in tools.tools]) == ["echo"]

        # First try calling the echo tool - expect to get blocked
        result = await session.call_tool(
            name="echo", arguments={"message": input_message}
        )
        assert len(result.content) == 1
        assert isinstance(result.content[0], types.TextContent)
        result_dict = json.loads(result.content[0].text)

        # Check that the call was blocked due to unapproved config
        assert isinstance(result_dict, dict) and result_dict["status"] == "blocked"
        sc = result_dict['server_config']


    async def callback2(session):
        input_message = "Hello from Wrapped SSE Server!"
        # After approval, reconnect and try again

        # Call the echo tool again - should work now
        result = await session.call_tool(
            name="echo", arguments={"message": input_message}
        )
        assert isinstance(result, types.CallToolResult)
        assert len(result.content) == 1
        assert isinstance(result.content[0], types.TextContent)

        # Parse the response
        response_json = json.loads(result.content[0].text)
        if response_json["status"] == "blocked":
            assert sc == response_json["server_config"]
        assert response_json["status"] == "completed"

        # The actual echo response should be in the response field
        response_data = json.loads(response_json["response"])
        assert response_data["echo_message"] == input_message

        # Try with a different message to ensure consistent behavior
        second_message = "Testing with a second message"
        result2 = await session.call_tool(
            name="echo", arguments={"message": second_message}
        )
        response_json2 = json.loads(result2.content[0].text)
        response_data2 = json.loads(response_json2["response"])
        assert response_data2["echo_message"] == second_message

    # Run the test with a temporary config file
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    await run_with_wrapper_session(callback, temp_file.name)
    # Build the URL for the SSE server to be used in the review process
    sse_url = f"http://localhost:{SERVER_PORT}/sse"

    # Now we need to run the review process to approve this config
    await approve_server_config_using_review(sse_url, temp_file.name)

    with open(temp_file.name, "r") as f:
        logging.error(f.read())
    from ..mcp_config import MCPConfigDatabase
    cdb = MCPConfigDatabase(temp_file.name)
    # assert cdb.servers == [], "wrong"
    conf = cdb.get_server_config("http", sse_url)
    assert conf is not None, "couldn't find"
    sc_obj = json.loads(sc)
    conf_mine = MCPServerConfig.from_dict(sc_obj)
    assert conf_mine == conf
    

    await run_with_wrapper_session(callback2, temp_file.name)

    os.unlink(temp_file.name)


@pytest.mark.asyncio
async def test_invalid_tool_through_wrapper(sse_server_fixture):
    """Test error handling for invalid tools through the MCP wrapper using SSE transport."""

    async def callback(session):
        # First try calling any tool to get blocked and receive the config
        result = await session.call_tool(name="echo", arguments={"message": "Test"})
        assert len(result.content) == 1
        result_dict = json.loads(result.content[0].text)
        assert result_dict["status"] == "blocked"

    async def callback2(session):
        # Now try to call a tool that doesn't exist
        result = await session.call_tool(
            name="nonexistent_tool", arguments={"foo": "bar"}
        )
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
    await run_with_wrapper_session(callback, temp_file.name)
    # Build the URL for the SSE server to be used in the review process
    sse_url = f"http://localhost:{SERVER_PORT}/sse"

    # Run the review process to approve this config
    await approve_server_config_using_review(sse_url, temp_file.name)
    await run_with_wrapper_session(callback2, temp_file.name)
    os.unlink(temp_file.name)


# This test is no longer needed since the server config approval process has changed
# and is now handled internally by the wrapper
@pytest.mark.skip(reason="Server config approval is now handled internally")
@pytest.mark.asyncio
async def test_server_config_difference(sse_server_fixture):
    """This test was for the old approval mechanism and is now skipped."""

    async def callback(session):
        # The echo tool should work directly now
        message = "Test message"
        result = await session.call_tool(name="echo", arguments={"message": message})
        response_json = json.loads(result.content[0].text)
        assert response_json["status"] == "completed"

    # Run the test with a temporary config file
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    await run_with_wrapper_session(callback, temp_file.name)
    os.unlink(temp_file.name)
