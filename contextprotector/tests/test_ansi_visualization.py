#!/usr/bin/env python3
"""
Tests for ANSI escape code visualization in MCP wrapper.
"""

import json
import os
import tempfile
import pytest
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typing import Callable, Awaitable

# Configure path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Path to a test server script that returns ANSI-colored output
TEST_SERVER_PATH = Path(__file__).resolve().parent / "ansi_test_server.py"


async def run_with_ansi_visualization(
    callback: Callable[[ClientSession], Awaitable[None]],
    config_path: str,
    visualize_ansi: bool = False,
):
    """
    Run a test with a wrapper that has ANSI visualization set accordingly.

    Args:
        callback: Async function that will be called with the client session
        config_path: Path to the configuration file
        visualize_ansi: Whether to visualize ANSI escape codes
    """
    server_params = StdioServerParameters(
        command="python",
        args=[
            str(Path(__file__).resolve().parent.parent.parent.joinpath("main.py")),
            "--command",
            f"python {str(TEST_SERVER_PATH)}",
            "--config-file",
            str(config_path),
            *(["--visualize-ansi-codes"] if visualize_ansi else []),
        ],
    )
    print(server_params, file=sys.stderr)
    async with stdio_client(server_params) as (read, write):
        assert read is not None and write is not None
        async with ClientSession(read, write) as session:
            await session.initialize()
            await callback(session)


class TestAnsiVisualization:
    """Tests for ANSI escape code visualization."""

    def setup_method(self):
        """Set up test by creating temp config file."""
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.config_path = self.temp_file.name

    def teardown_method(self):
        """Clean up after test."""
        os.unlink(self.config_path)

    @pytest.mark.asyncio
    async def test_ansi_passthrough_default(self):
        """Test that ANSI escape codes are let through by default."""

        async def callback(session):
            # List available tools
            tools = await session.list_tools()

            # There should be an ansi_echo tool
            tool_names = [t.name for t in tools.tools]
            assert "ansi_echo" in tool_names

            # Find the ansi_echo tool
            ansi_tool = next(t for t in tools.tools if t.name == "ansi_echo")

            # Verify that the description contains ANSI escape sequences
            assert "\x1b[" in ansi_tool.description

            # First attempt to call ansi_echo should be blocked
            blocked_result = await session.call_tool("ansi_echo", {"message": "test"})
            blocked_response = json.loads(blocked_result.content[0].text)
            assert blocked_response["status"] == "blocked"

            # Approve the server config
            approval_result = await session.call_tool(
                "approve_server_config", {"config": blocked_response["server_config"]}
            )
            approval_json = json.loads(approval_result.content[0].text)
            assert approval_json["status"] == "success"

            # Now try calling the ansi_echo tool
            result = await session.call_tool("ansi_echo", {"message": "test"})

            # Get the response
            response_text = result.content[0].text
            response_json = json.loads(response_text)

            # Verify the response contains ANSI escape codes (not replaced with ESC)
            assert "ESC" not in response_json["response"]
            assert "\x1b[" in response_json["response"]

        await run_with_ansi_visualization(
            callback, self.config_path, visualize_ansi=False
        )

    @pytest.mark.asyncio
    async def test_ansi_visualization_enabled(self):
        """Test that ANSI escape codes are visualized when enabled."""

        async def callback(session):
            # List available tools
            tools = await session.list_tools()

            # There should be an ansi_echo tool
            tool_names = [t.name for t in tools.tools]
            assert "ansi_echo" in tool_names

            # First attempt to call ansi_echo should be blocked
            blocked_result = await session.call_tool("ansi_echo", {"message": "test"})
            blocked_response = json.loads(blocked_result.content[0].text)
            assert blocked_response["status"] == "blocked"

            # Approve the server config
            approval_result = await session.call_tool(
                "approve_server_config", {"config": blocked_response["server_config"]}
            )
            approval_json = json.loads(approval_result.content[0].text)
            assert approval_json["status"] == "success"

            # Now call the ansi_echo tool
            result = await session.call_tool("ansi_echo", {"message": "test"})

            # Get the response
            response_text = result.content[0].text
            response_json = json.loads(response_text)

            # Verify the response contains "ESC" instead of actual escape codes
            assert "ESC[" in response_json["response"]
            assert "\x1b[" not in response_json["response"]

        await run_with_ansi_visualization(
            callback, self.config_path, visualize_ansi=True
        )
