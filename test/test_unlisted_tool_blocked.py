"""Regression test for the fail-open on unknown tool names in call_tool.

Issue: the wrapper only blocked a tool call when the tool name was present in the
approval database and marked unapproved
(`if name in tools_dict and not tools_dict[name]`). A tool name absent from the
database, e.g. a tool added by the downstream server without a
`tools/list_changed` notification, was proxied to the downstream server and
executed. list_tools is fail-closed for the same case, so call_tool must be too:
an unknown tool is an unapproved tool.
"""

import json
import logging
import sys
import tempfile
from pathlib import Path

import pytest
from mcp import ClientSession, types

from .test_utils import approve_server_config_using_review, run_with_wrapper_session

logger = logging.getLogger("test_unlisted_tool_blocked")


@pytest.mark.asyncio()
async def test_unlisted_tool_call_is_blocked_after_approval() -> None:
    """A tool name never seen at approval time must be blocked, not proxied."""

    async def test_callback(session: ClientSession) -> None:
        """Verify approved tools work and unlisted tools are blocked."""
        # Sanity check: an approved tool still works.
        ok_result = await session.call_tool(name="test_tool", arguments={"message": "hi"})
        assert isinstance(ok_result, types.CallToolResult)
        ok_data = json.loads(ok_result.content[0].text)
        assert ok_data["status"] == "completed", f"approved tool failed: {ok_data}"
        logger.info("approved tool call works")

        # The bypass: call a tool name that was never listed or approved.
        # Before the fix this was forwarded to the downstream server, which
        # answered with its own "Unknown tool" response, proving the call
        # reached the server. It must instead be blocked by the wrapper.
        blocked_result = await session.call_tool(name="shadow_tool_never_listed", arguments={})
        assert isinstance(blocked_result, types.CallToolResult)
        assert len(blocked_result.content) > 0

        blocked_text = blocked_result.content[0].text
        blocked_data = json.loads(blocked_text)
        assert blocked_data["status"] == "blocked", (
            f"unlisted tool call was not blocked by the wrapper: {blocked_text}"
        )
        assert "not approved" in blocked_data["reason"].lower(), (
            f"unexpected block reason: {blocked_data['reason']}"
        )
        # The downstream server must never have seen the call: its
        # "Unknown tool" reply must not leak through.
        assert "unknown tool" not in blocked_text.lower(), (
            "call reached the downstream server instead of being blocked"
        )
        logger.info("unlisted tool call correctly blocked")

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    try:
        server_script = str(Path(__file__).resolve().parent.joinpath("prompt_test_server.py"))
        server_command = f"{sys.executable} {server_script}"

        await approve_server_config_using_review("stdio", server_command, temp_file.name)
        await run_with_wrapper_session(test_callback, "stdio", server_command, temp_file.name)
    finally:
        Path(temp_file.name).unlink()
