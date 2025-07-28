"""
Simple downstream MCP server with an echo tool.
Uses fastmcp with SSE transport from the official Python SDK for MCP.
"""

import argparse
import os
import sys
from typing import Dict, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool

# Define the echo tool
echo_tool = Tool(
    name="echo",
    description="Echoes back the input message",
    inputSchema={
        "type": "object",
        "properties": {"message": {"type": "string", "description": "The message to echo back"}},
        "required": ["message"],
    },
)


# Echo handler function
async def echo_handler(message: str) -> dict[str, Any]:
    """
    Echo handler function that returns the input message.

    Args:
        params: A dictionary containing the parameters from the request.
            Expected to have a 'message' key with a string value.

    Returns:
        A dictionary with the 'echo_message' key containing the input message.
    """
    return {"echo_message": message}


# Create the server
app = FastMCP()

# Register the tool
app.add_tool(echo_handler, "echo")


# Function to write PID to file
def write_pidfile(pidfile_path):
    """Write the current process ID to the specified file."""
    if pidfile_path:
        with open(pidfile_path, "w") as f:
            f.write(str(os.getpid()))
        print(f"PID {os.getpid()} written to {pidfile_path}")


# Run the server if executed directly
if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Simple SSE MCP Server")
    parser.add_argument("--pidfile", help="File to write the server's PID to")

    args = parser.parse_args()

    # Write PID to file if specified
    write_pidfile(args.pidfile)

    app.settings.host = "127.0.0.1"

    # The default port for FastMCP's SSE transport is 8000, but just in case that port number is in
    # use, we will attempt fifty ports to try to find one that is available. uvicorn raises
    # SystemExit when it fails due to a port conflict, so that's how we detect this failure case.
    class PortException(Exception):
        pass

    for port in range(8000, 8050):
        try:
            app.settings.port = port
            app.run(transport="sse")
            break
        except SystemExit:
            print(f"Warning: port {port} in use", file=sys.stderr)
            pass
        except KeyboardInterrupt:
            sys.exit(0)
