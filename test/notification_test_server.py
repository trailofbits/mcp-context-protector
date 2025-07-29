"""
Test MCP server that sends notifications for testing notification forwarding.
Uses the MCP Python SDK Server with ServerSession for sending notifications.
"""

import asyncio
import logging
from contextlib import AsyncExitStack

import anyio
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.server.stdio import stdio_server

logger = logging.getLogger("notification_test_server")


class NotificationTestServer:
    def __init__(self) -> None:
        self.server = Server("notification-test-server")
        self._session = None  # Will store the session object
        self.received_notifications = []  # Track received client notifications
        self.register_handlers()

    def register_handlers(self) -> None:
        """Register all handlers with the server."""

        @self.server.list_tools()
        async def list_tools() -> list[types.Tool]:
            """Return list of available tools."""
            return [
                types.Tool(
                    name="send_notifications",
                    description="Send test notifications including valid and invalid types",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "include_invalid": {
                                "type": "boolean",
                                "description": "Whether to send an invalid notification type",
                            }
                        },
                        "required": [],
                    },
                ),
                types.Tool(
                    name="get_received_notifications",
                    description="Get list of notifications received from client",
                    inputSchema={"type": "object", "properties": {}, "required": []},
                ),
                types.Tool(
                    name="clear_received_notifications",
                    description="Clear the list of received notifications",
                    inputSchema={"type": "object", "properties": {}, "required": []},
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
            """Handle tool calls."""
            if name == "send_notifications":
                include_invalid = arguments.get("include_invalid", True)
                logger.info("Sending notifications, include_invalid=%s", include_invalid)

                try:
                    # Send valid notifications
                    await self._send_valid_notifications()

                    logger.info("Successfully sent all notifications")
                    return [
                        types.TextContent(type="text", text="Sent test notifications (valid types)")
                    ]
                except Exception as e:
                    logger.exception("Error sending notifications: %s", e)
                    return [
                        types.TextContent(
                            type="text", text=f"Error sending notifications: {e!s}"
                        )
                    ]
            elif name == "get_received_notifications":
                import json

                notifications_data = [
                    {
                        "method": notif["method"],
                        "params": notif.get("params"),
                        "timestamp": notif["timestamp"],
                    }
                    for notif in self.received_notifications
                ]
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "received_notifications": notifications_data,
                                "count": len(notifications_data),
                            },
                            indent=2,
                        ),
                    )
                ]
            elif name == "clear_received_notifications":
                count = len(self.received_notifications)
                self.received_notifications.clear()
                return [
                    types.TextContent(type="text", text="Cleared %d received notifications" % count)
                ]
            else:
                raise ValueError(f"Unknown tool: {name}")

        # Add notification handlers to capture client→server notifications
        @self.server.progress_notification()
        async def handle_progress_notification(notification: types.ProgressNotification) -> None:
            """Handle progress notifications from client."""
            import time

            notification_data = {
                "method": notification.method,
                "params": notification.params.model_dump() if notification.params else None,
                "timestamp": time.time(),
            }
            self.received_notifications.append(notification_data)
            logger.info("Received progress notification from client: %s", notification.method)

        # Register other notification handlers manually
        async def handle_message_notification(notification: types.LoggingMessageNotification) -> None:
            """Handle message notifications from client."""
            import time

            notification_data = {
                "method": notification.method,
                "params": notification.params.model_dump() if notification.params else None,
                "timestamp": time.time(),
            }
            self.received_notifications.append(notification_data)
            logger.info("Received message notification from client: %s", notification.method)

        async def handle_cancelled_notification(notification: types.CancelledNotification) -> None:
            """Handle cancelled notifications from client."""
            import time

            notification_data = {
                "method": notification.method,
                "params": notification.params.model_dump() if notification.params else None,
                "timestamp": time.time(),
            }
            self.received_notifications.append(notification_data)
            logger.info("Received cancelled notification from client: %s", notification.method)

        async def handle_initialized_notification(notification: types.InitializedNotification) -> None:
            """Handle initialized notifications from client."""
            import time

            notification_data = {
                "method": notification.method,
                "params": notification.params.model_dump() if notification.params else None,
                "timestamp": time.time(),
            }
            self.received_notifications.append(notification_data)
            logger.info("Received initialized notification from client: %s", notification.method)

        # Register handlers in the notification_handlers dict
        self.server.notification_handlers[types.LoggingMessageNotification] = (
            handle_message_notification
        )
        self.server.notification_handlers[types.CancelledNotification] = (
            handle_cancelled_notification
        )
        self.server.notification_handlers[types.InitializedNotification] = (
            handle_initialized_notification
        )

        @self.server.list_prompts()
        async def list_prompts() -> list[types.Prompt]:
            """Return list of available prompts (empty for test server)."""
            return []

        @self.server.list_resources()
        async def list_resources() -> list[types.Resource]:
            """Return list of available resources (empty for test server)."""
            return []

    async def _send_valid_notifications(self) -> None:
        """Send all valid notification types according to MCP specification."""
        if not self._session:
            logger.exception("No session available to send notifications")
            return

        # 1. Send tools/list_changed notification
        await self._session.send_tool_list_changed()
        logger.info("Sent notifications/tools/list_changed")

        # 2. Send prompts/list_changed notification
        await self._session.send_prompt_list_changed()
        logger.info("Sent notifications/prompts/list_changed")

        # 3. Send resources/list_changed notification
        await self._session.send_resource_list_changed()
        logger.info("Sent notifications/resources/list_changed")

        # 4. Send progress notification using proper ProgressNotification type
        progress_notification = types.ProgressNotification(
            method="notifications/progress",
            params=types.ProgressNotificationParams(
                progressToken="test-progress-123", progress=50.0, total=100.0
            ),
        )
        await self._session.send_notification(progress_notification)
        logger.info("Sent notifications/progress")

        # 5. Send log message notification
        await self._session.send_log_message(
            level="info", data="Test log message from notification server"
        )
        logger.info("Sent notifications/message")

        # 6. Send resource updated notification
        resource_updated_notification = types.ResourceUpdatedNotification(
            method="notifications/resources/updated",
            params=types.ResourceUpdatedNotificationParams(uri="file://test-resource.txt"),
        )
        await self._session.send_notification(resource_updated_notification)
        logger.info("Sent notifications/resources/updated")

    async def _send_invalid_notification(self) -> None:
        """Send an invalid notification type that should be filtered out."""
        if not self._session:
            logger.exception("No session available to send notifications")
            return

        # Create a custom notification with invalid method for testing filtering
        invalid_notification = types.JSONRPCNotification(
            jsonrpc="2.0",
            method="notifications/invalid/custom_type",
            params={"custom_data": "This should be filtered out"},
        )
        await self._session.send_notification(invalid_notification)
        logger.info("Sent notifications/invalid/custom_type (should be filtered)")

    async def run(self) -> None:
        """Run the server with session tracking."""
        async with stdio_server() as streams:
            init_options = InitializationOptions(
                server_name="notification-test-server",
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
    server = NotificationTestServer()
    await server.run()


if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO)

    asyncio.run(main())
