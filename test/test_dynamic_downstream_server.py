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
# Global variable for temporary tool count file
TEMP_TOOLCOUNT_FILE = None


class ToolUpdateTracker:
    """Helper class to track tool update notifications from the server."""

    def __init__(self):
        self.updates_received = 0
        self.latest_tools = []
        self.notification_event = asyncio.Event()

    async def handle_message(self, message):
        """
        Message handler function that processes notifications from the server.

        Args:
            message: The message from the server
        """
        from mcp.types import ServerNotification

        # Check if it's a notification
        if isinstance(message, ServerNotification):
            print(f"Received notification: {message.root.method}")

            if message.root.method == "notifications/tools/list_changed":
                self.updates_received += 1
                # We need to fetch the latest tools list since the notification doesn't include it
                print("Received notifications/tools/list_changed notification")
                self.notification_event.set()  # Signal that a notification was received
        else:
            print(f"Received non-notification message: {type(message)}")

    async def wait_for_notification(self, timeout=2.0):
        """Wait for a tool update notification to be received."""
        try:
            await asyncio.wait_for(self.notification_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


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


async def send_sighup_and_wait(session, expected_tools, tracker):
    """
    Send SIGHUP to the server, verify a notification is received, then check tools were updated.

    Args:
        session: The client session to check
        expected_tools: List of tool names that should be present after the update
        tracker: The ToolUpdateTracker instance to check for notifications

    Returns:
        None
    """
    # Reset the notification event
    tracker.notification_event.clear()

    # Send SIGHUP to the server
    os.kill(SERVER_PID, signal.SIGHUP)

    # Wait for the notification to be received
    notification_received = await tracker.wait_for_notification(timeout=2.0)
    assert notification_received, "No tool update notification was received after sending SIGHUP"

    # Additional verification: check that updates_received counter was incremented
    assert tracker.updates_received > 0, "Tool update tracker did not receive any notifications"

    # Verify that the tools list now contains the expected tools
    await verify_tools(session, expected_tools)

    # Get the updated tools list and store it in the tracker
    tools = await session.list_tools()
    tracker.latest_tools = tools.tools


def write_tool_count(count):
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


async def start_dynamic_server(callback: callable, initial_tool_count=None):
    """
    Start the dynamic server and run the provided callback with a client session.

    Args:
        callback: Function to call with the client session
        initial_tool_count: Initial number of tools (None uses default)
    """
    global SERVER_PID, TEMP_PIDFILE, TEMP_TOOLCOUNT_FILE

    # Create a temporary pidfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pid") as tmp:
        TEMP_PIDFILE = tmp.name

    # Create a command args list
    args = [
        str(Path(__file__).resolve().parent.joinpath("dynamic_downstream_server.py")),
        "--pidfile",
        TEMP_PIDFILE,
    ]

    # Add tool count file if specified
    if initial_tool_count is not None:
        toolcount_file = write_tool_count(initial_tool_count)
        args.extend(["--toolcount-file", toolcount_file])

    server_params = StdioServerParameters(
        command="python",
        args=args,
        env=None,
    )

    # Create a notification tracker
    tracker = ToolUpdateTracker()

    async with stdio_client(server_params) as (read, write):
        assert read is not None and write is not None
        # Create the session with the tracker's message handler
        async with ClientSession(read, write, message_handler=tracker.handle_message) as session:
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

            # Run the test callback with the session and tracker
            await callback(session, tracker)


def cleanup_files():
    """Clean up the temporary files if they exist."""
    global TEMP_PIDFILE, TEMP_TOOLCOUNT_FILE

    if TEMP_PIDFILE and os.path.exists(TEMP_PIDFILE):
        try:
            os.unlink(TEMP_PIDFILE)
        except OSError:
            pass

    if TEMP_TOOLCOUNT_FILE and os.path.exists(TEMP_TOOLCOUNT_FILE):
        try:
            os.unlink(TEMP_TOOLCOUNT_FILE)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def cleanup_after_test():
    """
    Fixture to clean up resources after each test.

    This fixture runs automatically after each test function completes
    and ensures that temporary files are properly removed.
    """
    yield
    cleanup_files()


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_initial_tools():
    """
    Test that the dynamic server starts with the initial echo tool.

    This test verifies:
    1. The server initializes with the echo tool
    2. The echo tool functions correctly by returning the input message

    The timeout ensures the test won't hang indefinitely if there's an issue.
    """

    async def callback(session, tracker):
        """
        Test callback that verifies the initial tool state and tests the echo tool.

        Args:
            session: The MCP client session connected to the server
            tracker: The notification tracker for monitoring tool updates
        """
        await verify_tools(session, ["echo"])

        # Test the echo tool
        input_message = "Hello, dynamic server!"
        result = await session.call_tool(name="echo", arguments={"message": input_message})

        assert isinstance(result, types.CallToolResult)
        assert len(result.content) == 1
        assert isinstance(result.content[0], types.TextContent)

        response = json.loads(result.content[0].text)
        assert response == {"echo_message": input_message}

    await start_dynamic_server(callback)


@pytest.mark.asyncio
@pytest.mark.timeout(5)
async def test_preconfigured_tools():
    """
    Test that the server can start with a preconfigured number of tools.

    This test verifies:
    1. The server initializes with multiple tools when specified in the tool count file
    2. The tools are properly initialized and functional
    """

    async def callback(session, tracker):
        """
        Test callback that verifies multiple tools are available at startup.

        Args:
            session: The MCP client session connected to the server
            tracker: The notification tracker for monitoring tool updates
        """
        # Check that all expected tools are available
        await verify_tools(session, ["echo", "calculator", "counter"])

        # Test the echo tool
        input_message = "Hello, preconfigured server!"
        result = await session.call_tool(name="echo", arguments={"message": input_message})
        response = json.loads(result.content[0].text)
        assert response == {"echo_message": input_message}

        # Test the calculator tool
        result = await session.call_tool(
            name="calculator", arguments={"a": 5, "b": 7, "operation": "add"}
        )
        response = json.loads(result.content[0].text)
        assert response == {"result": 12}

        # Test the counter tool
        result = await session.call_tool(name="counter", arguments={})
        response = json.loads(result.content[0].text)
        assert response == {"count": 3}

    # Start server with 3 tools
    await start_dynamic_server(callback, initial_tool_count=3)


@pytest.mark.asyncio
async def test_sighup_adds_tool():
    """
    Test that sending SIGHUP adds a new tool and triggers a tool update notification.

    This test verifies:
    1. The server starts with the echo tool
    2. When a SIGHUP signal is sent, a notification is received
    3. The calculator tool is added to the available tools
    4. The calculator tool functions correctly with different operations
    5. The notification contains the updated tool list
    """

    async def callback(session, tracker):
        """
        Test callback that verifies tool updates after SIGHUP signal.

        Args:
            session: The MCP client session connected to the server
            tracker: The notification tracker for monitoring tool updates
        """
        # Check initial state - only echo tool should be present
        await verify_tools(session, ["echo"])

        # Send SIGHUP to add calculator tool and verify notification is received
        await send_sighup_and_wait(session, ["echo", "calculator"], tracker)

        # Log notification details for debugging
        print(f"Tool update notification received after {tracker.updates_received} updates")

        # The latest_tools in the notification should include the calculator tool
        tool_names = [tool.name for tool in tracker.latest_tools]
        assert "calculator" in tool_names, "Calculator tool not found in the update notification"

        # Test the calculator tool
        result = await session.call_tool(
            name="calculator", arguments={"a": 10, "b": 5, "operation": "add"}
        )

        assert isinstance(result, types.CallToolResult)
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
async def test_notification_on_sighup():
    """
    Explicit test focusing on notifications being sent when SIGHUP is received.

    This test verifies:
    1. No notifications are received initially
    2. When SIGHUP is sent, a tool update notification is received
    3. The notification counter is incremented correctly
    4. Multiple SIGHUPs result in multiple notifications
    5. After each SIGHUP, the tool list is updated with the expected new tools
    """

    async def callback(session, tracker):
        """
        Test callback that explicitly checks notification receipt after SIGHUP signals.

        Args:
            session: The MCP client session connected to the server
            tracker: The notification tracker for monitoring tool updates
        """
        # Verify no notifications yet
        assert tracker.updates_received == 0, "Should have no notifications before SIGHUP"

        # Send SIGHUP
        os.kill(SERVER_PID, signal.SIGHUP)

        # Wait for the notification
        notification_received = await tracker.wait_for_notification(timeout=2.0)
        assert notification_received, "No notification received within timeout period"

        # Verify a notification was received
        assert tracker.updates_received == 1, "Expected exactly one notification"

        # Fetch the tools list
        tools = await session.list_tools()
        tool_names = [tool.name for tool in tools.tools]
        assert "calculator" in tool_names, "Calculator tool missing after notification"
        print(f"Notification verified with tools: {tool_names}")

        # Send another SIGHUP and verify we get a second notification
        tracker.notification_event.clear()  # Reset the event
        os.kill(SERVER_PID, signal.SIGHUP)

        notification_received = await tracker.wait_for_notification(timeout=2.0)
        assert notification_received, "No second notification received within timeout period"
        assert tracker.updates_received == 2, "Expected two notifications total"

        # Get updated tools list
        tools = await session.list_tools()
        tool_names = [tool.name for tool in tools.tools]
        assert "counter" in tool_names, "Counter tool missing after second notification"
        print(f"Second notification verified with tools: {tool_names}")

    await start_dynamic_server(callback)


@pytest.mark.asyncio
async def test_preconfigured_with_sighup():
    """
    Test that a server with preconfigured tools correctly responds to SIGHUP.

    This test verifies:
    1. The server starts with multiple tools from the configuration file
    2. When SIGHUP is sent, additional tools are added correctly
    3. Tool notifications work properly for servers with preconfigured tools
    """

    async def callback(session, tracker):
        """
        Test callback that verifies SIGHUP behavior with preconfigured tools.

        Args:
            session: The MCP client session connected to the server
            tracker: The notification tracker for monitoring tool updates
        """
        # Check initial state - two tools should be present
        await verify_tools(session, ["echo", "calculator"])

        # Send SIGHUP to add counter tool and verify notification
        await send_sighup_and_wait(session, ["echo", "calculator", "counter"], tracker)

        # Test the counter tool that was just added
        result = await session.call_tool(name="counter", arguments={})
        response = json.loads(result.content[0].text)
        assert response == {"count": 3}

        # Send another SIGHUP to add echo4 tool
        await send_sighup_and_wait(session, ["echo", "calculator", "counter", "echo4"], tracker)

        # Test the echo4 tool
        result = await session.call_tool(name="echo4", arguments={"message": "Testing echo4"})
        response = json.loads(result.content[0].text)
        assert response["echo_message"] == "Testing echo4"
        assert response["tool_number"] == 4

    # Start server with 2 tools
    await start_dynamic_server(callback, initial_tool_count=2)


@pytest.mark.asyncio
async def test_multiple_sighups():
    """
    Test that multiple SIGHUPs add multiple tools and trigger notifications for each.

    This test verifies:
    1. Each SIGHUP signal adds a new tool in sequence (calculator, counter, echo4)
    2. Each SIGHUP triggers a separate notification
    3. The notification counter increments correctly after each signal
    4. The tools are functional after being added
    5. The tools are added in the expected order based on the server implementation
    """

    async def callback(session, tracker):
        """
        Test callback that verifies multiple SIGHUP signals add tools in sequence.

        Args:
            session: The MCP client session connected to the server
            tracker: The notification tracker for monitoring tool updates
        """
        # Check initial state - only echo tool should be present
        await verify_tools(session, ["echo"])

        # Send first SIGHUP to add calculator tool
        await send_sighup_and_wait(session, ["echo", "calculator"], tracker)

        # Verify notification for first SIGHUP
        assert tracker.updates_received == 1, "Expected 1 notification after first SIGHUP"
        tools = await session.list_tools()
        tool_names1 = [tool.name for tool in tools.tools]
        assert "calculator" in tool_names1, "Calculator tool missing after first SIGHUP"
        print(f"First SIGHUP notification verified with tools: {tool_names1}")

        # Reset notification event counter before second SIGHUP
        tracker.notification_event.clear()

        # Send second SIGHUP to add counter tool
        await send_sighup_and_wait(session, ["echo", "calculator", "counter"], tracker)

        # Verify notification for second SIGHUP
        assert tracker.updates_received == 2, "Expected 2 notifications total after second SIGHUP"
        tools = await session.list_tools()
        tool_names2 = [tool.name for tool in tools.tools]
        assert "counter" in tool_names2, "Counter tool missing after second SIGHUP"
        print(f"Second SIGHUP notification verified with tools: {tool_names2}")

        # Test the counter tool
        result = await session.call_tool(name="counter", arguments={})

        assert isinstance(result, types.CallToolResult)
        assert len(result.content) == 1
        response = json.loads(result.content[0].text)
        assert response == {"count": 3}  # Should reflect num_tools=3

        # Reset notification event counter before third SIGHUP
        tracker.notification_event.clear()

        # Send third SIGHUP to add echo4 tool
        await send_sighup_and_wait(session, ["echo", "calculator", "counter", "echo4"], tracker)

        # Verify notification for third SIGHUP
        assert tracker.updates_received == 3, "Expected 3 notifications total after third SIGHUP"
        tools = await session.list_tools()
        tool_names3 = [tool.name for tool in tools.tools]
        assert "echo4" in tool_names3, "Echo4 tool missing after third SIGHUP"
        print(f"Third SIGHUP notification verified with tools: {tool_names3}")

    await start_dynamic_server(callback)
