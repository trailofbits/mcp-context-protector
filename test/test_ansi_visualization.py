"""
Tests for ANSI escape code visualization in MCP wrapper.
"""

import json
import os
import sys
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from mcp import ClientSession

from .test_utils import approve_server_config_using_review, run_with_wrapper_session

# Configure path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# Path to a test server script that returns ANSI-colored output
TEST_SERVER_PATH = Path(__file__).resolve().parent / "ansi_test_server.py"


async def run_without_ansi_visualization(
    callback: Callable[[ClientSession], Awaitable[None]],
    config_path: str
) -> None:
    """
    Run a test with a wrapper that has ANSI visualization set accordingly.

    Args:
        callback: Async function that will be called with the client session
        config_path: Path to the configuration file
        visualize_ansi: Whether to visualize ANSI escape codes
    """
    command = f"python {TEST_SERVER_PATH!s}"
    await run_with_wrapper_session(callback, "stdio", command, config_path, False)


async def run_with_ansi_visualization(
    callback: Callable[[ClientSession], Awaitable[None]],
    config_path: str
) -> None:
    """
    Run a test with a wrapper that has ANSI visualization set accordingly.

    Args:
        callback: Async function that will be called with the client session
        config_path: Path to the configuration file
        visualize_ansi: Whether to visualize ANSI escape codes
    """
    command = f"python {TEST_SERVER_PATH!s}"
    await run_with_wrapper_session(callback, "stdio", command, config_path, True)


class TestAnsiVisualization:
    """Tests for ANSI escape code visualization."""

    def setup_method(self) -> None:
        """Set up test by creating temp config file."""
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.config_path = self.temp_file.name

    def teardown_method(self) -> None:
        """Clean up after test."""
        os.unlink(self.config_path)

    @pytest.mark.asyncio()
    async def test_ansi_passthrough_default(self) -> None:
        """Test that ANSI escape codes are let through by default."""

        # Create the test command
        command = f"python {TEST_SERVER_PATH!s}"

        # First test stage - get blocked
        async def callback1(session: ClientSession) -> None:
            # List available tools - should only see context-protector-block when unapproved
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            assert tool_names == ["context-protector-block"]

            # First attempt to call ansi_echo should be blocked
            blocked_result = await session.call_tool("ansi_echo", {"message": "test"})
            blocked_response = json.loads(blocked_result.content[0].text)
            assert blocked_response["status"] == "blocked"

        # Second test stage - after approval
        async def callback2(session: ClientSession) -> None:
            # After approval, list tools to verify ANSI codes in descriptions
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            assert "ansi_echo" in tool_names

            # Find the ansi_echo tool and verify ANSI escape sequences in description
            ansi_tool = next(t for t in tools.tools if t.name == "ansi_echo")
            assert "\x1b[" in ansi_tool.description

            # Now try calling the ansi_echo tool
            result = await session.call_tool("ansi_echo", {"message": "test"})

            # Get the response
            response_text = result.content[0].text
            response_json = json.loads(response_text)

            # Verify the response contains ANSI escape codes (not replaced with ESC)
            assert "ESC" not in response_json["response"]
            assert "\x1b[" in response_json["response"]

        # Run first part of the test
        await run_without_ansi_visualization(callback1, self.config_path)

        # Use review to approve the config
        await approve_server_config_using_review("stdio", command, self.config_path)

        # Run second part of the test with the approved config
        await run_without_ansi_visualization(callback2, self.config_path)

    @pytest.mark.asyncio()
    async def test_ansi_visualization_enabled(self) -> None:
        """Test that ANSI escape codes are visualized when enabled."""

        # Create the test command
        command = f"python {TEST_SERVER_PATH!s}"

        # First test stage - get blocked
        async def callback1(session: ClientSession) -> None:
            # List available tools - should only see context-protector-block when unapproved
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            assert tool_names == ["context-protector-block"]

            # First attempt to call ansi_echo should be blocked
            blocked_result = await session.call_tool("ansi_echo", {"message": "test"})
            blocked_response = json.loads(blocked_result.content[0].text)
            assert blocked_response["status"] == "blocked"

        # Second test stage - after approval
        async def callback2(session: ClientSession) -> None:
            # Now call the ansi_echo tool
            result = await session.call_tool("ansi_echo", {"message": "test"})

            # Get the response
            response_text = result.content[0].text
            response_json = json.loads(response_text)

            # Verify the response contains "ESC" instead of actual escape codes
            assert "ESC[" in response_json["response"]
            assert "\x1b[" not in response_json["response"]

        # Run first part of the test
        await run_with_ansi_visualization(callback1, self.config_path)

        # Use review to approve the config
        await approve_server_config_using_review("stdio", command, self.config_path)

        # Run second part of the test with the approved config
        await run_with_ansi_visualization(callback2, self.config_path)
