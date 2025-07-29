#!/usr/bin/env python3
"""
Dynamic downstream MCP server with signal handler to update tools.
Uses fastmcp from the official Python SDK for MCP.

This server:
1. Starts with a configurable number of tools (default: 1)
2. Registers a SIGHUP signal handler
3. When SIGHUP is received, adds a new tool and notifies clients
4. Writes its PID to a pidfile specified via command-line argument
5. Can read initial tool count from a specified file

Usage:
  python dynamic_downstream_server.py [--pidfile PIDFILE] [--toolcount-file TOOLCOUNT_FILE]

Args:
  --pidfile PIDFILE  Path to write PID file (default: dynamic_server.pid)
  --toolcount-file TOOLCOUNT_FILE  Path to file containing initial tool count (optional)

To test:
1. Run this server
2. Connect with the MCP wrapper
3. Send SIGHUP to the server process:
   kill -HUP $(cat dynamic_server.pid)
"""

import argparse
import asyncio
import atexit
import os
import signal
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel import NotificationOptions
from mcp.server.session import ServerSession
from mcp.server.stdio import stdio_server

# Global counter for the number of tools
num_tools = 1

# Create the server
app = FastMCP()


# Echo handler function
async def echo_handler(message: str) -> dict[str, Any]:
    """
    Echo handler function that returns the input message.

    Args:
        message: The string message to echo back

    Returns:
        A dictionary with the 'echo_message' key containing the input message.
    """
    return {"echo_message": message}


# Calculator handler for the dynamic tool
async def calculator_handler(a: int, b: int, operation: str) -> dict[str, Any]:
    """
    Calculator handler function that performs the requested operation on two numbers.

    Args:
        a: First number
        b: Second number
        operation: The operation to perform (add, subtract, multiply, divide)

    Returns:
        A dictionary with the 'result' key containing the calculation result.
    """
    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    elif operation == "divide":
        if b == 0:
            return {"error": "Cannot divide by zero"}
        result = a / b
    else:
        return {"error": f"Unknown operation: {operation}"}

    return {"result": result}


# Counter tool handler - available based on num_tools
async def counter_handler() -> dict[str, Any]:
    """
    Counter handler function that returns the current number of tools.

    Returns:
        A dictionary with the 'count' key containing the current number of tools.
    """
    return {"count": num_tools}


def add_dynamic_tool() -> None:
    """Add a new tool based on the current tool count."""
    global num_tools

    # Add calculator tool if num_tools >= 2
    if num_tools == 2:
        app.add_tool(
            calculator_handler,
            name="calculator",
            description="Performs basic arithmetic operations",
        )
        print(f"Added calculator tool (tool #{num_tools})", file=sys.stderr)

    # Add counter tool if num_tools >= 3
    elif num_tools == 3:
        app.add_tool(
            counter_handler,
            name="counter",
            description="Returns the current number of tools",
        )
        print(f"Added counter tool (tool #{num_tools})", file=sys.stderr)

    # For num_tools > 3, add numbered echo tools
    else:
        # Create a wrapper function that calls the original echo handler
        # We need a new function for each dynamically added tool
        async def numbered_echo_handler(message: str) -> dict[str, Any]:
            result = await echo_handler(message)
            result["tool_number"] = num_tools
            return result

        app.add_tool(
            numbered_echo_handler,
            name=f"echo{num_tools}",
            description=f"Echo tool #{num_tools} - echoes back the input message with a tool number",
        )
        print(f"Added echo{num_tools} tool", file=sys.stderr)


def initialize_tools(count) -> None:
    """
    Initialize the server with the specified number of tools.

    Args:
        count: The number of tools to initialize
    """
    global num_tools

    # Always register the first echo tool
    app.add_tool(
        echo_handler,
        name="echo",
        description="Echoes back the input message",
    )
    print("Added initial echo tool (tool #1)", file=sys.stderr)

    # Add additional tools if requested
    while num_tools < count:
        num_tools += 1
        add_dynamic_tool()


def read_tool_count_from_file(toolcount_file) -> int:
    """
    Read the tool count from the specified file.

    Args:
        toolcount_file: Path to the file containing the tool count

    Returns:
        int: The number of tools to initialize, or 1 if the file doesn't exist or is invalid
    """
    try:
        if toolcount_file and Path(toolcount_file).exists():
            with Path(toolcount_file).open("r") as f:
                count = int(f.read().strip())
                return max(1, count)  # Ensure at least 1 tool
    except (OSError, ValueError, FileNotFoundError) as e:
        print(f"Error reading tool count from {toolcount_file}: {e}", file=sys.stderr)

    # Default to 1 tool if file doesn't exist or has invalid content
    return 1


def signal_handler(_signum: any, _frame: any) -> None:
    """Signal handler for SIGHUP that adds a new tool."""
    global num_tools

    print(f"Received SIGHUP signal, current num_tools: {num_tools}", file=sys.stderr)

    num_tools += 1

    # Add a new tool
    add_dynamic_tool()

    # Notify clients of the updated tools list
    # This triggers the _handle_tool_updates callback in the wrapper
    # app.notify_tools_updated()
    loop = asyncio.get_running_loop()
    asyncio.run_coroutine_threadsafe(app._session.send_tool_list_changed(), loop)

    print(
        f"Increased num_tools to {num_tools} and sent tool update notification",
        file=sys.stderr,
    )


def write_pidfile(pidfile_path) -> None:
    """
    Write the current process ID to the specified pidfile.

    Args:
        pidfile_path: Path to the pidfile
    """
    pid = os.getpid()

    try:
        with Path(pidfile_path).open("w") as f:
            f.write(str(pid))

        # Register cleanup function to remove pidfile on exit
        atexit.register(lambda: Path(pidfile_path).unlink() if Path(pidfile_path).exists() else None)

        print(f"PID {pid} written to {pidfile_path}", file=sys.stderr)
    except Exception as e:
        print(f"Error writing pidfile {pidfile_path}: {e}", file=sys.stderr)


async def my_run(
    self,
    # When False, exceptions are returned as messages to the client.
    # When True, exceptions are raised, which will cause the server to shut down
    # but also make tracing exceptions much easier during testing and when using
    # in-process servers.
    raise_exceptions: bool = False,
    # When True, the server is stateless and
    # clients can perform initialization with any node. The client must still follow
    # the initialization lifecycle, but can do so with any available node
    # rather than requiring initialization for each connection.
    _stateless: bool = False,
) -> None:
    """
    Server startup function that allows us to send notifications.

    We need this song and dance because the current version of the Python SDK doesn't give us
    direct access to the ServerSession object or the server's MemoryObjectSendStream, meaning that
    there's no way to send the tools updated notification without restructuring the server object
    a bit. This functino is replicated directly from mcp/server/fastmcp/server.py and
    mcp/server/low-level/server.py.
    """
    opts = self._mcp_server.create_initialization_options(
        notification_options=NotificationOptions(tools_changed=True)
    )
    async with stdio_server() as (read_stream, write_stream):
        async with AsyncExitStack() as stack:
            lifespan_context = await stack.enter_async_context(self._mcp_server.lifespan(self))
            session = await stack.enter_async_context(
                ServerSession(
                    read_stream,
                    write_stream,
                    opts,
                )
            )
            self._session = session

            async with anyio.create_task_group() as tg:
                async for message in session.incoming_messages:
                    tg.start_soon(
                        self._mcp_server._handle_message,
                        message,
                        self._session,
                        lifespan_context,
                        raise_exceptions,
                    )


def main() -> None:
    """Main function to run the server with signal handling and pidfile."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Dynamic MCP server with signal handling")
    parser.add_argument(
        "--pidfile",
        default="dynamic_server.pid",
        help="Path to write PID file (default: dynamic_server.pid)",
    )
    parser.add_argument(
        "--toolcount-file",
        help="Path to file containing initial tool count",
    )
    args = parser.parse_args()

    # Write PID to pidfile
    write_pidfile(args.pidfile)

    # Read tool count from file if specified
    initial_tool_count = read_tool_count_from_file(args.toolcount_file)

    # Initialize tools with the specified count
    initialize_tools(initial_tool_count)

    # Register the signal handler
    signal.signal(signal.SIGHUP, signal_handler)

    print(
        f"Dynamic server started with PID {os.getpid()} and {num_tools} tools",
        file=sys.stderr,
    )
    print(f"Send SIGHUP to add tools: kill -HUP $(cat {args.pidfile})", file=sys.stderr)

    # Run the server
    asyncio.run(my_run(app))


if __name__ == "__main__":
    main()
