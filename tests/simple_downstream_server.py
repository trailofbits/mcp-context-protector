"""
Simple downstream MCP server with an echo tool.
Uses fastmcp from the official Python SDK for MCP.
"""
from typing import Dict, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool

# Define the echo tool
echo_tool = Tool(
    name="echo",
    description="Echoes back the input message",
    inputSchema={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The message to echo back"
            }
        },
        "required": ["message"]
    }
)

# Echo handler function
# async def echo_handler(params: Dict[str, Any]) -> Dict[str, Any]:
async def echo_handler(message: str) -> Dict[str, Any]:
    """
    Echo handler function that returns the input message.
    
    Args:
        params: A dictionary containing the parameters from the request.
            Expected to have a 'message' key with a string value.
            
    Returns:
        A dictionary with the 'echo_message' key containing the input message.
    """
    # message = params.get("message", "")
    return {"echo_message": message}

# Create the server
app = FastMCP()

# Register the tool
#app.add_tool(echo_tool, echo_handler)
app.add_tool(echo_handler, "echo")

# Run the server if executed directly
if __name__ == "__main__":
    app.run()
    #asyncio.run(app.run_server("localhost", 8000))
