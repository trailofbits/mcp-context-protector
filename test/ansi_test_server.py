#!/usr/bin/env python3
"""
A simple MCP server that returns ANSI-colored output.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

# ANSI color codes for testing
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
RESET = "\x1b[0m"
BOLD = "\x1b[1m"


def get_colored_text(text) -> str:
    """Generate a string with ANSI color codes."""
    return f"{RED}Red {GREEN}Green {YELLOW}Yellow{RESET} and {BOLD}Bold{RESET} {text}"


async def main() -> None:
    server = Server("ansi-test-server")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        """List the available tools."""
        return [
            types.Tool(
                name="ansi_echo",
                description=f"""
                Echoes the input with ANSI colors.
                {RED}This text is red.{RESET}
                {GREEN}This text is green.{RESET}
                {YELLOW}This text is yellow.{RESET}
                {BOLD}This text is bold.{RESET}
                """,
                inputSchema={
                    "type": "object",
                    "required": ["message"],
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Message to echo with colors",
                        }
                    },
                },
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        """Handle tool call requests."""
        if name == "ansi_echo":
            message = arguments.get("message", "")
            colored_message = get_colored_text(message)

            return [types.TextContent(type="text", text=colored_message)]

        return [types.TextContent(type="text", text="Unknown tool")]

    async with stdio_server() as streams:
        await server.run(
            streams[0],
            streams[1],
            InitializationOptions(
                server_name="ansi-test-server",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(tools_changed=False),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
