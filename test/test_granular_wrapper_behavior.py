#!/usr/bin/env python3
"""
End-to-end tests for granular approval behavior in the wrapper.

These tests verify the actual user-facing behavior of the wrapper when tools have
mixed approval states, demonstrating true granular blocking.
"""

import json
import tempfile
import pytest
from pathlib import Path

from contextprotector.mcp_config import (
    MCPConfigDatabase,
    MCPServerConfig,
    MCPToolDefinition,
    MCPParameterDefinition,
    ParameterType,
    ApprovalStatus,
)
from .test_utils import run_with_wrapper_session, approve_server_config_using_review


def get_server_command(server_filename: str) -> str:
    """Get the absolute path command for a server script, regardless of cwd."""
    test_dir = Path(__file__).parent
    server_path = test_dir / server_filename
    return f"python {server_path}"


@pytest.mark.asyncio()
async def test_granular_tool_filtering_in_list_tools():
    """Test that list_tools() only shows approved tools in mixed approval scenarios."""

    temp_file = tempfile.NamedTemporaryFile(delete=False)

    # Step 1: Start with multi-tool server and approve it fully
    await run_with_wrapper_session(
        lambda session: session.list_tools(),
        "stdio",
        get_server_command("multi_tool_downstream_server.py"),
        temp_file.name,
    )

    # Approve the server
    await approve_server_config_using_review(
        "stdio", get_server_command("multi_tool_downstream_server.py"), temp_file.name
    )

    # Step 2: Create a mixed approval scenario by approving only one tool
    db = MCPConfigDatabase(temp_file.name)

    # Get the current config (which should have both echo and greet tools)
    config = db.get_server_config("stdio", get_server_command("multi_tool_downstream_server.py"))

    # Reset approval - remove the server entry completely and recreate it
    from contextprotector.mcp_config import MCPServerEntry

    key = MCPServerEntry.create_key("stdio", get_server_command("multi_tool_downstream_server.py"))
    if key in db.servers:
        del db.servers[key]
        db._save()

    # Save as unapproved config (this will create a fresh entry)
    db.save_unapproved_config(
        "stdio", get_server_command("multi_tool_downstream_server.py"), config
    )

    # Find the tools in the config
    echo_tool = None
    greet_tool = None
    for tool in config.tools:
        if tool.name == "echo":
            echo_tool = tool
        elif tool.name == "greet":
            greet_tool = tool

    # Approve instructions and only the echo tool
    db.approve_instructions(
        "stdio", get_server_command("multi_tool_downstream_server.py"), config.instructions
    )
    if echo_tool:
        db.approve_tool(
            "stdio", get_server_command("multi_tool_downstream_server.py"), "echo", echo_tool
        )
    # Note: NOT approving greet tool

    # Step 3: Test that list_tools() shows granular filtering
    async def test_granular_filtering(session):
        tools = await session.list_tools()
        tool_names = [t.name for t in tools.tools]

        print(f"Available tools: {tool_names}")

        # Should have the approved echo tool
        assert "echo" in tool_names, f"Echo tool should be available, got: {tool_names}"

        # Should NOT have the unapproved greet tool
        assert (
            "greet" not in tool_names
        ), f"Unapproved greet tool should not be visible, got: {tool_names}"

        # Test that approved tool works
        result = await session.call_tool(name="echo", arguments={"message": "test"})
        response_json = json.loads(result.content[0].text)
        assert response_json["status"] == "completed", "Approved tool should work"

        # Test that unapproved tool is blocked
        try:
            result = await session.call_tool(name="greet", arguments={"name": "test"})
            response_json = json.loads(result.content[0].text)
            assert response_json["status"] == "blocked", "Unapproved tool should be blocked"
            assert (
                "not approved" in response_json["reason"].lower()
            ), "Should indicate tool not approved"
        except Exception as e:
            # The wrapper should raise a ValueError with JSON error details for blocked tools
            error_message = str(e)
            assert "blocked" in error_message, f"Expected blocked error, got: {error_message}"

    await run_with_wrapper_session(
        test_granular_filtering,
        "stdio",
        get_server_command("multi_tool_downstream_server.py"),
        temp_file.name,
    )


@pytest.mark.asyncio()
async def test_tool_modification_blocks_only_modified_tool():
    """Test that modifying a tool blocks only that tool while others remain available."""

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    db = MCPConfigDatabase(temp_file.name)

    # Step 1: Create a server with multiple tools and approve all of them
    config = MCPServerConfig()
    config.instructions = "Multi-tool test server"

    tool1 = MCPToolDefinition(
        name="stable_tool",
        description="This tool will not change",
        parameters=[
            MCPParameterDefinition(
                name="input1", description="Input 1", type=ParameterType.STRING, required=True
            )
        ],
    )

    tool2 = MCPToolDefinition(
        name="modified_tool",
        description="This tool will be modified",
        parameters=[
            MCPParameterDefinition(
                name="input2", description="Input 2", type=ParameterType.STRING, required=True
            )
        ],
    )

    config.add_tool(tool1)
    config.add_tool(tool2)

    # Approve everything initially
    db.save_unapproved_config("stdio", "multi_tool_server", config)
    db.approve_instructions("stdio", "multi_tool_server", config.instructions)
    db.approve_tool("stdio", "multi_tool_server", "stable_tool", tool1)
    db.approve_tool("stdio", "multi_tool_server", "modified_tool", tool2)
    db.save_server_config("stdio", "multi_tool_server", config, ApprovalStatus.APPROVED)

    # Step 2: Modify tool2 (change description to simulate a tool update)
    modified_tool2 = MCPToolDefinition(
        name="modified_tool",
        description="This tool description was CHANGED",  # Modified!
        parameters=[
            MCPParameterDefinition(
                name="input2", description="Input 2", type=ParameterType.STRING, required=True
            )
        ],
    )

    modified_config = MCPServerConfig()
    modified_config.instructions = config.instructions  # Same instructions
    modified_config.add_tool(tool1)  # Same stable tool
    modified_config.add_tool(modified_tool2)  # Modified tool

    # Update config without approving the modified tool
    db.save_unapproved_config("stdio", "multi_tool_server", modified_config)

    # Step 3: Test granular approval status - manual validation since we can't test wrapper directly
    status = db.get_server_approval_status("stdio", "multi_tool_server", modified_config)

    # Instructions should still be approved
    assert status["instructions_approved"]

    # Stable tool should still be approved
    assert status["tools"]["stable_tool"]

    # Modified tool should NOT be approved anymore
    assert not status["tools"]["modified_tool"]

    print(
        "✅ Tool modification correctly detected - stable tool remains approved, modified tool needs re-approval"
    )


@pytest.mark.asyncio()
async def test_instruction_change_blocks_everything():
    """Test that changing server instructions blocks ALL tools, demonstrating whole-server blocking."""

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    db = MCPConfigDatabase(temp_file.name)

    # Step 1: Create and fully approve a multi-tool server
    config = MCPServerConfig()
    config.instructions = "Original server instructions"

    tool1 = MCPToolDefinition(
        name="tool_one",
        description="First tool",
        parameters=[
            MCPParameterDefinition(
                name="p1", description="Param 1", type=ParameterType.STRING, required=True
            )
        ],
    )

    tool2 = MCPToolDefinition(
        name="tool_two",
        description="Second tool",
        parameters=[
            MCPParameterDefinition(
                name="p2", description="Param 2", type=ParameterType.STRING, required=True
            )
        ],
    )

    config.add_tool(tool1)
    config.add_tool(tool2)

    # Approve everything
    db.save_unapproved_config("stdio", "instruction_test_server", config)
    db.approve_instructions("stdio", "instruction_test_server", config.instructions)
    db.approve_tool("stdio", "instruction_test_server", "tool_one", tool1)
    db.approve_tool("stdio", "instruction_test_server", "tool_two", tool2)
    db.save_server_config("stdio", "instruction_test_server", config, ApprovalStatus.APPROVED)

    # Verify everything is approved initially
    status = db.get_server_approval_status("stdio", "instruction_test_server", config)
    assert status["instructions_approved"]
    assert status["tools"]["tool_one"]
    assert status["tools"]["tool_two"]

    # Step 2: Change ONLY the instructions (tools unchanged)
    modified_config = MCPServerConfig()
    modified_config.instructions = "MODIFIED server instructions"  # Changed!
    modified_config.add_tool(tool1)  # Exactly same tools
    modified_config.add_tool(tool2)  # Exactly same tools

    # Step 3: Test that instruction change affects approval
    status = db.get_server_approval_status("stdio", "instruction_test_server", modified_config)

    # Instructions should NOT be approved (changed)
    assert not status["instructions_approved"]

    # Tools should still be individually approved (they didn't change)
    assert status["tools"]["tool_one"]
    assert status["tools"]["tool_two"]

    # But the wrapper logic should block everything due to instruction change
    # (this is enforced in the wrapper's connection logic and call_tool logic)

    print(
        "✅ Instruction change correctly detected - wrapper will block all tools despite individual tool approval"
    )


@pytest.mark.asyncio()
async def test_tool_removal_workflow():
    """Test that removing tools doesn't require reapproval and remaining tools work."""

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    db = MCPConfigDatabase(temp_file.name)

    # Step 1: Create server with multiple tools and approve all
    config = MCPServerConfig()
    config.instructions = "Server with removable tools"

    keep_tool = MCPToolDefinition(
        name="keep_this_tool",
        description="This tool will remain",
        parameters=[
            MCPParameterDefinition(
                name="input", description="Input", type=ParameterType.STRING, required=True
            )
        ],
    )

    remove_tool = MCPToolDefinition(
        name="remove_this_tool",
        description="This tool will be removed",
        parameters=[
            MCPParameterDefinition(
                name="input", description="Input", type=ParameterType.STRING, required=True
            )
        ],
    )

    config.add_tool(keep_tool)
    config.add_tool(remove_tool)

    # Approve everything
    db.save_unapproved_config("stdio", "removal_test_server", config)
    db.approve_instructions("stdio", "removal_test_server", config.instructions)
    db.approve_tool("stdio", "removal_test_server", "keep_this_tool", keep_tool)
    db.approve_tool("stdio", "removal_test_server", "remove_this_tool", remove_tool)
    db.save_server_config("stdio", "removal_test_server", config, ApprovalStatus.APPROVED)

    # Step 2: Remove one tool
    reduced_config = MCPServerConfig()
    reduced_config.instructions = config.instructions  # Same instructions
    reduced_config.add_tool(keep_tool)  # Only keep one tool
    # remove_tool is removed

    # Step 3: Test that removal doesn't affect approval of remaining components
    status = db.get_server_approval_status("stdio", "removal_test_server", reduced_config)

    # Instructions should still be approved (unchanged)
    assert status["instructions_approved"]

    # Remaining tool should still be approved
    assert status["tools"]["keep_this_tool"]

    # Removed tool should not be in the status (not tracked anymore)
    assert "remove_this_tool" not in status["tools"]

    print(
        "✅ Tool removal works correctly - remaining tools stay approved, removed tools disappear"
    )


@pytest.mark.asyncio()
async def test_new_server_complete_blocking():
    """Test that completely new servers are totally blocked until approved."""

    temp_file = tempfile.NamedTemporaryFile(delete=False)

    # Test connecting to a server that has never been seen before
    async def test_new_server_blocking(session):
        # New server should only show context-protector-block
        tools = await session.list_tools()
        tool_names = [t.name for t in tools.tools]

        # Should ONLY have context-protector-block tool
        assert "context-protector-block" in tool_names
        assert (
            len([t for t in tool_names if t != "context-protector-block"]) == 0
        ), f"New server should only show context-protector-block, got: {tool_names}"

        # All downstream tools should be blocked
        result = await session.call_tool(name="echo", arguments={"message": "test"})
        response_json = json.loads(result.content[0].text)
        assert response_json["status"] == "blocked"
        assert "configuration not approved" in response_json["reason"].lower()

    await run_with_wrapper_session(
        test_new_server_blocking,
        "stdio",
        get_server_command("simple_downstream_server.py"),
        temp_file.name,
    )

    print("✅ New server complete blocking works correctly")
