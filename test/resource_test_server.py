"""
A simple MCP server that provides tools, prompts, and resources for testing.
"""

import asyncio
import json
import sys
from pathlib import Path

import anyio

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contextlib import AsyncExitStack

from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.server.stdio import stdio_server


class ResourceTestServer:
    def __init__(self) -> None:
        self.server = Server("resource-test-server")
        self._session = None  # Will store the session object

        # Variable to track which set of resources to use (for testing changes)
        self.use_alternate_resources = False

        # Register handlers
        self.register_handlers()

    def register_handlers(self) -> None:
        """Register all handlers with the server."""

        @self.server.list_tools()
        async def list_tools() -> list[types.Tool]:
            """List the available tools."""
            return [
                types.Tool(
                    name="test_tool",
                    description="A simple test tool",
                    inputSchema={
                        "type": "object",
                        "required": ["message"],
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "Message to echo",
                            }
                        },
                    },
                ),
                types.Tool(
                    name="toggle_resources",
                    description="Toggle between different sets of resources (to test resource changes)",
                    inputSchema={"type": "object", "properties": {}},
                ),
            ]

        @self.server.list_resources()
        async def list_resources() -> list[types.Resource]:
            """List the available resources."""
            if not self.use_alternate_resources:
                # Default resources
                return [
                    types.Resource(
                        name="Sample data",
                        uri="contextprotector://sample_data",
                        description="Sample data resource",
                        mime_type="application/json",
                    ),
                    types.Resource(
                        name="Image resource",
                        uri="contextprotector://image_resource",
                        description="Sample image resource",
                        mime_type="image/png",
                    ),
                ]
            # Alternate resources (when toggled)
            return [
                types.Resource(
                    name="Sample data",
                    uri="contextprotector://sample_data",
                    description="Sample data resource (updated)",
                    mime_type="application/json",
                ),
                types.Resource(
                    name="Document resource",
                    uri="contextprotector://document_resource",
                    description="Sample document resource",
                    mime_type="text/plain",
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
            """Handle tool call requests."""
            if name == "test_tool":
                message = arguments.get("message", "")
                return [types.TextContent(type="text", text=f"Echo: {message}")]
            if name == "toggle_resources":
                # Toggle resources and notify clients
                self.use_alternate_resources = not self.use_alternate_resources
                resource_state = "alternate" if self.use_alternate_resources else "default"

                # Use the session to send a resource list changed notification
                if self._session:
                    # Schedule the notification to be sent after the current operation completes
                    asyncio.create_task(self._session.send_resource_list_changed())

                return [
                    types.TextContent(type="text", text=f"Toggled to {resource_state} resources")
                ]

            return [types.TextContent(type="text", text="Unknown tool")]

        @self.server.read_resource()
        async def read_resource(uri: str) -> types.ReadResourceResult:
            """Handle resource content requests."""
            if str(uri) == "contextprotector://sample_data":
                # Return JSON sample data
                content = json.dumps(
                    {
                        "name": "Sample Data",
                        "type": "test",
                        "items": [
                            {"id": 1, "value": "first"},
                            {"id": 2, "value": "second"},
                            {"id": 3, "value": "third"},
                        ],
                    }
                )
                return [ReadResourceContents(content=content, mime_type="application/json")]
            if str(uri) == "contextprotector://image_resource":
                # Just return placeholder text for testing
                content = b"[Binary image data]"
                return [ReadResourceContents(content=content, mime_type="image/png")]
            if str(uri) == "contextprotector://document_resource":
                # Return text document
                content = "This is a sample document resource.\nIt contains multiple lines.\nFor testing purposes."
                return [ReadResourceContents(content=content, mime_type="text/plain")]

            return [
                ReadResourceContents(content="Unknown resource requested", mime_type="text/plain")
            ]

    async def run(self) -> None:
        """Run the server with session tracking."""
        async with stdio_server() as streams:
            init_options = InitializationOptions(
                server_name="resource-test-server",
                server_version="0.1.0",
                capabilities=self.server.get_capabilities(
                    notification_options=NotificationOptions(
                        tools_changed=True, prompts_changed=True, resources_changed=True
                    ),
                    experimental_capabilities={},
                ),
            )

            async with AsyncExitStack() as stack:
                # Create and store the server session
                self._session = await stack.enter_async_context(
                    ServerSession(
                        streams[0],
                        streams[1],
                        init_options,
                    )
                )

                # Process incoming messages
                async with anyio.create_task_group() as tg:
                    async for message in self._session.incoming_messages:
                        tg.start_soon(
                            self.server._handle_message,
                            message,
                            self._session,
                            None,  # No lifespan context needed
                            False,  # Don't raise exceptions
                        )


async def main() -> None:
    """Main entry point for the server."""
    server = ResourceTestServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
