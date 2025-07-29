"""
Simple downstream MCP server with an echo tool.
Uses fastmcp from the official Python SDK for MCP.
"""

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
    app.run()
