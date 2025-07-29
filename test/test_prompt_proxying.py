#!/usr/bin/env python3
"""
Tests for the prompt proxying functionality in MCP wrapper.
"""

import asyncio
import json
import sys
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from mcp import ClientSession

# Configure path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import test utilities
from .test_utils import approve_server_config_using_review, run_with_wrapper_session

# Path to the prompt test server script
PROMPT_TEST_SERVER_PATH = Path(__file__).resolve().parent / "prompt_test_server.py"


# Local helper function for backward compatibility
async def run_with_wrapper(callback: Callable[[ClientSession], Awaitable[None]], config_path: str) -> None:
    """
    Run a test with a wrapper connected to the prompt test server.

    Args:
        callback: Async function that will be called with the client session
        config_path: Path to the configuration file
    """
    command = f"python {PROMPT_TEST_SERVER_PATH!s}"
    await run_with_wrapper_session(callback, "stdio", command, config_path)


class TestPromptProxying:
    """Tests for prompt proxying functionality."""

    def setup_method(self) -> None:
        """Set up test by creating temp config file."""
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.config_path = self.temp_file.name

    def teardown_method(self) -> None:
        """Clean up after test."""
        Path(self.config_path).unlink()

    @pytest.mark.asyncio()
    async def test_initial_prompt_listing(self) -> None:
        """Test that prompts are correctly listed from the downstream server after approval."""

        # Create the test command
        command = f"python {PROMPT_TEST_SERVER_PATH!s}"

        # First callback - before approval
        async def callback1(session: ClientSession) -> None:
            # List available prompts before approval - should be empty
            initial_prompts = await session.list_prompts()
            assert len(initial_prompts.prompts) == 0

            # Try to use a tool to verify we're blocked
            blocked_result = await session.call_tool("test_tool", {"message": "test"})
            blocked_response = json.loads(blocked_result.content[0].text)
            assert blocked_response["status"] == "blocked"

        # Second callback - after approval
        async def callback2(session: ClientSession) -> None:
            # Now list prompts after approval
            prompts = await session.list_prompts()

            # Verify prompts are correctly proxied after approval
            assert len(prompts.prompts) == 2
            prompt_names = [p.name for p in prompts.prompts]
            assert "greeting" in prompt_names
            assert "help" in prompt_names

            # Verify prompt details
            greeting_prompt = next(p for p in prompts.prompts if p.name == "greeting")
            assert "friendly greeting" in greeting_prompt.description
            assert any(arg.name == "name" and arg.required for arg in greeting_prompt.arguments)

        # Run first part of the test
        await run_with_wrapper(callback1, self.config_path)

        # Use review process to approve the config
        await approve_server_config_using_review("stdio", command, self.config_path)

        # Run second part of the test
        await run_with_wrapper(callback2, self.config_path)

    @pytest.mark.asyncio()
    async def test_prompt_dispatch(self) -> None:
        """Test that prompts can be dispatched through the wrapper."""

        # Create the test command
        command = f"python {PROMPT_TEST_SERVER_PATH!s}"

        # First callback - before approval, confirm blocking
        async def callback1(session: ClientSession) -> None:
            # List available tools - should only see context-protector-block when unapproved
            tools = await session.list_tools()
            assert "context-protector-block" in [t.name for t in tools.tools]

            # Call a tool to get the config (it will be blocked)
            blocked_result = await session.call_tool("test_tool", {"message": "test"})
            blocked_response = json.loads(blocked_result.content[0].text)
            assert blocked_response["status"] == "blocked"

        # Second callback - after approval
        async def callback2(session: ClientSession) -> None:
            # Now dispatch a prompt
            greeting_result = await session.get_prompt("greeting", {"name": "Test User"})

            # Verify the prompt response
            assert len(greeting_result.messages) == 1
            assert "Hello, Test User!" in greeting_result.messages[0].content.text

        # Run first part of the test
        await run_with_wrapper(callback1, self.config_path)

        # Use review process to approve the config
        await approve_server_config_using_review("stdio", command, self.config_path)

        # Run second part of the test
        await run_with_wrapper(callback2, self.config_path)

    @pytest.mark.asyncio()
    async def test_prompt_changes(self) -> None:
        """
        Test that changes to prompts are correctly proxied without affecting
        the approval status of the server configuration.
        """

        # Create the test command
        command = f"python {PROMPT_TEST_SERVER_PATH!s}"

        # First do the approval process
        await run_with_wrapper(
            lambda session: asyncio.create_task(
                session.call_tool("test_tool", {"message": "test"})
            ),
            self.config_path,
        )

        # Use review process to approve the config
        await approve_server_config_using_review("stdio", command, self.config_path)

        # Now the main callback after approval
        async def callback(session: ClientSession) -> None:
            # Initial prompts check
            initial_prompts = await session.list_prompts()
            assert len(initial_prompts.prompts) == 2
            assert "greeting" in [p.name for p in initial_prompts.prompts]
            assert "help" in [p.name for p in initial_prompts.prompts]

            # Toggle to alternate prompts
            toggle_result = await session.call_tool("toggle_prompts", {})
            assert "Toggled to alternate prompts" in toggle_result.content[0].text

            # Wait briefly for notification to be processed
            await asyncio.sleep(0.5)

            # Check updated prompts
            updated_prompts = await session.list_prompts()
            assert len(updated_prompts.prompts) == 2
            prompt_names = [p.name for p in updated_prompts.prompts]
            assert "greeting" in prompt_names
            assert "farewell" in prompt_names
            assert "help" not in prompt_names

            # Verify we can still use tools without re-approval
            tool_result = await session.call_tool("test_tool", {"message": "after prompt change"})
            response_text = tool_result.content[0].text
            assert "Echo: after prompt change" in response_text

            # Verify we can dispatch the new prompt
            farewell_result = await session.get_prompt("farewell", {"name": "Test User"})
            assert "Goodbye, Test User!" in farewell_result.messages[0].content.text

            # Verify we can use the updated version of an existing prompt
            greeting_result = await session.get_prompt(
                "greeting", {"name": "Test User", "formal": "true"}
            )
            assert "Good day, Test User" in greeting_result.messages[0].content.text

        # Run the test with the approved config
        await run_with_wrapper(callback, self.config_path)

    @pytest.mark.asyncio()
    async def test_prompt_blocked_before_approval(self) -> None:
        """Test that prompts are blocked before server config is approved."""

        # Create the test command
        command = f"python {PROMPT_TEST_SERVER_PATH!s}"

        # Part 1: Before approval
        async def callback1(session: ClientSession) -> None:
            # Try to dispatch a prompt before approval
            result = await session.get_prompt("greeting", {"name": "Test User"})

            # Should return an empty message list, not an error
            assert result.description == "Server configuration not approved"
            assert len(result.messages) == 0

            # List prompts should return an empty list before approval
            initial_prompts = await session.list_prompts()
            assert len(initial_prompts.prompts) == 0

            # Call a tool to get blocked with the config
            blocked_result = await session.call_tool("test_tool", {"message": "test"})
            blocked_response = json.loads(blocked_result.content[0].text)
            assert blocked_response["status"] == "blocked"
            # Note: server_config is no longer included to prevent information leakage

        # Part 2: After approval
        async def callback2(session: ClientSession) -> None:
            # Now prompt should work
            greeting_result = await session.get_prompt("greeting", {"name": "Test User"})
            assert len(greeting_result.messages) > 0
            assert "Hello, Test User!" in greeting_result.messages[0].content.text

            # List prompts should now return prompts after approval
            approved_prompts = await session.list_prompts()
            assert len(approved_prompts.prompts) > 0
            assert "greeting" in [p.name for p in approved_prompts.prompts]

        # Run first part of the test
        await run_with_wrapper(callback1, self.config_path)

        # Use review process to approve the config
        await approve_server_config_using_review("stdio", command, self.config_path)

        # Run second part of the test
        await run_with_wrapper(callback2, self.config_path)


if __name__ == "__main__":
    pytest.main(["-v", __file__])
