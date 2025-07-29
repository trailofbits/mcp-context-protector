"""
A simple MCP server that provides both tools and prompts for testing.
"""

import asyncio
import sys
from pathlib import Path

import anyio

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contextlib import AsyncExitStack

from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.server.stdio import stdio_server


class PromptTestServer:
    def __init__(self) -> None:
        self.server = Server("prompt-test-server")
        self._session = None  # Will store the session object

        # Variable to track which set of prompts to use (for testing changes)
        self.use_alternate_prompts = False

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
                    name="toggle_prompts",
                    description="Toggle between different sets of prompts (to test prompt changes)",
                    inputSchema={"type": "object", "properties": {}},
                ),
            ]

        @self.server.list_prompts()
        async def list_prompts() -> list[types.Prompt]:
            """List the available prompts."""
            if not self.use_alternate_prompts:
                # Default prompts
                return [
                    types.Prompt(
                        name="greeting",
                        description="A friendly greeting prompt",
                        arguments=[
                            types.PromptArgument(
                                name="name", description="Name to greet", required=True
                            )
                        ],
                    ),
                    types.Prompt(
                        name="help",
                        description="Get help information",
                        arguments=[
                            types.PromptArgument(
                                name="topic",
                                description="Optional topic to get help on",
                                required=True,
                            )
                        ],
                    ),
                ]
            # Alternate prompts (when toggled)
            return [
                types.Prompt(
                    name="greeting",
                    description="A friendly greeting prompt (updated)",
                    arguments=[
                        types.PromptArgument(
                            name="name", description="Name to greet", required=True
                        )
                    ],
                ),
                types.Prompt(
                    name="farewell",
                    description="A farewell message",
                    arguments=[
                        types.PromptArgument(
                            name="name",
                            description="Name to bid farewell to",
                            required=True,
                        )
                    ],
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
            """Handle tool call requests."""
            if name == "test_tool":
                message = arguments.get("message", "")
                return [types.TextContent(type="text", text=f"Echo: {message}")]
            elif name == "toggle_prompts":
                # Toggle prompts and notify clients
                self.use_alternate_prompts = not self.use_alternate_prompts
                prompt_state = "alternate" if self.use_alternate_prompts else "default"

                # Use the session to send a prompt list changed notification
                if self._session:
                    loop = asyncio.get_running_loop()
                    asyncio.run_coroutine_threadsafe(self._session.send_prompt_list_changed(), loop)
                    print("Sent prompt_list_changed notification", file=sys.stderr)

                return [types.TextContent(type="text", text=f"Toggled to {prompt_state} prompts")]

            return [types.TextContent(type="text", text="Unknown tool")]

        @self.server.get_prompt()
        async def get_prompt(name: str, arguments: dict) -> list[types.TextContent]:
            """Handle prompt dispatch requests."""
            text = None
            description = None
            if name == "greeting":
                user_name = arguments.get("name", "User")
                # Check if we have formal parameter (only in alternate prompt set)
                if "formal" in arguments and arguments["formal"] == "true":
                    description = "A friendly greeting prompt"
                    text = f"Good day, {user_name}."
                else:
                    description = "A friendly greeting prompt"
                    text = f"Hello, {user_name}!"
            elif name == "help":
                topic = arguments.get("topic", "general")
                text = f"Help for topic: {topic}"
                description = "Get help information"
            elif name == "farewell":
                user_name = arguments.get("name", "User")
                description = "A farewell message"
                text = f"Goodbye, {user_name}!"

            return types.GetPromptResult(
                description=description,
                messages=[
                    types.PromptMessage(
                        role="user",
                        content=types.TextContent(type="text", text=text),
                    )
                ],
            )

    async def run(self) -> None:
        """Run the server with session tracking."""
        async with stdio_server() as streams:
            init_options = InitializationOptions(
                server_name="prompt-test-server",
                server_version="0.1.0",
                capabilities=self.server.get_capabilities(
                    notification_options=NotificationOptions(
                        tools_changed=True, prompts_changed=True
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
    server = PromptTestServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
