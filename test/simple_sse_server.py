"""
Simple downstream MCP server with an echo tool.
Uses fastmcp with SSE transport from the official Python SDK for MCP.
"""

import sys
from typing import Any

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


# Run the server if executed directly
if __name__ == "__main__":

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
        except KeyboardInterrupt:
            sys.exit(0)
