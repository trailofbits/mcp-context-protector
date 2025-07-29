"""
Multi-tool downstream MCP server for testing granular approval.
Has multiple tools that can be selectively approved/blocked.
"""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool

# Define multiple tools
echo_tool = Tool(
    name="echo",
    description="Echoes back the input message",
    inputSchema={
        "type": "object",
        "properties": {"message": {"type": "string", "description": "The message to echo back"}},
        "required": ["message"],
    },
)

greet_tool = Tool(
    name="greet",
    description="Greets a person by name",
    inputSchema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The name of the person to greet"}
        },
        "required": ["name"],
    },
)


# Handler functions
async def echo_handler(message: str) -> dict[str, Any]:
    """Echo handler function that returns the input message."""
    return {"echo_message": message}


async def greet_handler(name: str) -> dict[str, Any]:
    """Greet handler function that greets a person by name."""
    return {"greeting": f"Hello, {name}!"}


# Create the server
app = FastMCP()

# Register the tools
app.add_tool(echo_handler, "echo")
app.add_tool(greet_handler, "greet")

# Run the server if executed directly
if __name__ == "__main__":
    app.run()
