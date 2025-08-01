"""
Tests for granular tool-level approval system.

This module tests the granular approval behaviors:
- New tool addition → only that tool is blocked
- Tool modification → only that tool is blocked
- Tool removal → tool disappears without reapproval
- Mixed approval states → some tools work, others blocked
"""

import tempfile

import pytest
from contextprotector.mcp_config import (
    ApprovalStatus,
    MCPConfigDatabase,
    MCPParameterDefinition,
    MCPServerConfig,
    MCPToolDefinition,
    ParameterType,
)


@pytest.mark.asyncio()
async def test_granular_approval_database_logic() -> None:
    """Test the granular approval logic at the database level."""

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    db = MCPConfigDatabase(temp_file.name)

    # Step 1: Create initial server configuration with one tool
    config = MCPServerConfig()
    config.instructions = "Test server instructions"

    original_tool = MCPToolDefinition(
        name="original_tool",
        description="Original tool",
        parameters=[
            MCPParameterDefinition(
                name="param1", description="Test param", type=ParameterType.STRING, required=True
            )
        ],
    )
    config.add_tool(original_tool)

    # Save and approve everything
    db.save_unapproved_config("stdio", "test_server", config)
    db.approve_instructions("stdio", "test_server", config.instructions)
    db.approve_tool("stdio", "test_server", "original_tool", original_tool)
    db.save_server_config("stdio", "test_server", config, ApprovalStatus.APPROVED)

    # Verify initial approval
    status = db.get_server_approval_status("stdio", "test_server", config)
    assert status["instructions_approved"]
    assert status["tools"]["original_tool"]
    assert status["server_approved"]

    # Step 2: Add a new tool to the configuration
    config_with_new_tool = MCPServerConfig()
    config_with_new_tool.instructions = config.instructions  # Same instructions
    config_with_new_tool.add_tool(original_tool)  # Same original tool

    new_tool = MCPToolDefinition(
        name="new_added_tool",
        description="A newly added tool",
        parameters=[
            MCPParameterDefinition(
                name="param1", description="Test param", type=ParameterType.STRING, required=True
            )
        ],
    )
    config_with_new_tool.add_tool(new_tool)

    # Step 3: Test granular approval status with new tool
    status = db.get_server_approval_status("stdio", "test_server", config_with_new_tool)

    # Instructions should still be approved (unchanged)
    assert status["instructions_approved"]

    # Original tool should still be approved
    assert status["tools"]["original_tool"]

    # New tool should NOT be approved
    assert not status["tools"]["new_added_tool"]

    # Server should still be considered approved (granular system)
    assert status["server_approved"]


@pytest.mark.asyncio()
async def test_tool_modification_granular_blocking() -> None:
    """Test that modifying a tool blocks only that tool, not other approved tools."""

    temp_file = tempfile.NamedTemporaryFile(delete=False)

    # Step 1: Create and approve a server with multiple tools
    db = MCPConfigDatabase(temp_file.name)
    config = MCPServerConfig()
    config.instructions = "Test server with multiple tools"

    # Add two tools
    tool1 = MCPToolDefinition(
        name="tool1",
        description="First tool",
        parameters=[
            MCPParameterDefinition(
                name="param1", description="Param 1", type=ParameterType.STRING, required=True
            )
        ],
    )
    tool2 = MCPToolDefinition(
        name="tool2",
        description="Second tool",
        parameters=[
            MCPParameterDefinition(
                name="param2", description="Param 2", type=ParameterType.STRING, required=True
            )
        ],
    )

    config.add_tool(tool1)
    config.add_tool(tool2)

    # Save and approve everything
    db.save_unapproved_config("stdio", "test_multi_tool_server", config)
    db.approve_instructions("stdio", "test_multi_tool_server", config.instructions)
    db.approve_tool("stdio", "test_multi_tool_server", "tool1", tool1)
    db.approve_tool("stdio", "test_multi_tool_server", "tool2", tool2)
    db.save_server_config("stdio", "test_multi_tool_server", config, ApprovalStatus.APPROVED)

    # Step 2: Modify tool1 (change description)
    modified_tool1 = MCPToolDefinition(
        name="tool1",
        description="First tool - MODIFIED DESCRIPTION",  # Changed!
        parameters=[
            MCPParameterDefinition(
                name="param1", description="Param 1", type=ParameterType.STRING, required=True
            )
        ],
    )

    modified_config = MCPServerConfig()
    modified_config.instructions = config.instructions  # Same instructions
    modified_config.add_tool(modified_tool1)  # Modified tool
    modified_config.add_tool(tool2)  # Unchanged tool

    db.save_unapproved_config("stdio", "test_multi_tool_server", modified_config)

    # Step 3: Test granular blocking - tool1 blocked, tool2 still works
    approval_status = db.get_server_approval_status(
        "stdio", "test_multi_tool_server", modified_config
    )

    # Instructions should still be approved
    assert approval_status["instructions_approved"]

    # tool1 should NOT be approved (was modified)
    assert not approval_status["tools"]["tool1"]

    # tool2 should still be approved (unchanged)
    assert approval_status["tools"]["tool2"]


@pytest.mark.asyncio()
async def test_tool_removal_no_reapproval_needed() -> None:
    """Test that removing a tool simply makes it disappear without requiring reapproval."""

    temp_file = tempfile.NamedTemporaryFile(delete=False)

    # Step 1: Create and approve a server with multiple tools
    db = MCPConfigDatabase(temp_file.name)
    config = MCPServerConfig()
    config.instructions = "Test server with tools for removal"

    tool1 = MCPToolDefinition(
        name="keep_tool",
        description="Tool to keep",
        parameters=[
            MCPParameterDefinition(
                name="param1", description="Param 1", type=ParameterType.STRING, required=True
            )
        ],
    )
    tool2 = MCPToolDefinition(
        name="remove_tool",
        description="Tool to remove",
        parameters=[
            MCPParameterDefinition(
                name="param2", description="Param 2", type=ParameterType.STRING, required=True
            )
        ],
    )

    config.add_tool(tool1)
    config.add_tool(tool2)

    # Approve everything
    db.save_unapproved_config("stdio", "test_removal_server", config)
    db.approve_instructions("stdio", "test_removal_server", config.instructions)
    db.approve_tool("stdio", "test_removal_server", "keep_tool", tool1)
    db.approve_tool("stdio", "test_removal_server", "remove_tool", tool2)
    db.save_server_config("stdio", "test_removal_server", config, ApprovalStatus.APPROVED)

    # Step 2: Remove tool2
    reduced_config = MCPServerConfig()
    reduced_config.instructions = config.instructions  # Same instructions
    reduced_config.add_tool(tool1)  # Only keep tool1
    # tool2 is removed

    db.save_unapproved_config("stdio", "test_removal_server", reduced_config)

    # Step 3: Test that removal doesn't require reapproval
    approval_status = db.get_server_approval_status("stdio", "test_removal_server", reduced_config)

    # Instructions should still be approved
    assert approval_status["instructions_approved"]

    # Remaining tool should still be approved
    assert approval_status["tools"]["keep_tool"]

    # Removed tool should not be in the tools dict
    assert "remove_tool" not in approval_status["tools"]


@pytest.mark.asyncio()
async def test_server_instructions_change_blocks_everything() -> None:
    """Test that changing server instructions blocks the entire server."""

    temp_file = tempfile.NamedTemporaryFile(delete=False)

    # Step 1: Create and approve a server
    db = MCPConfigDatabase(temp_file.name)
    config = MCPServerConfig()
    config.instructions = "Original instructions"

    tool = MCPToolDefinition(
        name="test_tool",
        description="Test tool",
        parameters=[
            MCPParameterDefinition(
                name="param", description="Test param", type=ParameterType.STRING, required=True
            )
        ],
    )
    config.add_tool(tool)

    # Approve everything
    db.save_unapproved_config("stdio", "test_instruction_server", config)
    db.approve_instructions("stdio", "test_instruction_server", config.instructions)
    db.approve_tool("stdio", "test_instruction_server", "test_tool", tool)
    db.save_server_config("stdio", "test_instruction_server", config, ApprovalStatus.APPROVED)

    # Step 2: Change only the instructions
    modified_config = MCPServerConfig()
    modified_config.instructions = "MODIFIED instructions"  # Changed!
    modified_config.add_tool(tool)  # Same tool

    # Step 3: Test that instruction change is detected without saving as unapproved
    approval_status = db.get_server_approval_status(
        "stdio", "test_instruction_server", modified_config
    )

    # Instructions should NOT be approved (changed)
    assert not approval_status["instructions_approved"]

    # Tool itself should still be approved (hasn't changed)
    assert approval_status["tools"]["test_tool"]

    # Server should still be considered approved in the database
    assert approval_status["server_approved"]

    # The key test: instructions changed should block everything in wrapper logic
    assert not (
        db.are_instructions_approved(
            "stdio", "test_instruction_server", modified_config.instructions
        )
    )


@pytest.mark.asyncio()
async def test_mixed_approval_states() -> None:
    """Test behavior when some tools are approved and others are not."""

    temp_file = tempfile.NamedTemporaryFile(delete=False)

    # Step 1: Create a server with multiple tools
    db = MCPConfigDatabase(temp_file.name)
    config = MCPServerConfig()
    config.instructions = "Test server with mixed tool states"

    approved_tool = MCPToolDefinition(
        name="approved_tool",
        description="This tool is approved",
        parameters=[
            MCPParameterDefinition(
                name="param1", description="Param 1", type=ParameterType.STRING, required=True
            )
        ],
    )

    unapproved_tool = MCPToolDefinition(
        name="unapproved_tool",
        description="This tool is not approved",
        parameters=[
            MCPParameterDefinition(
                name="param2", description="Param 2", type=ParameterType.STRING, required=True
            )
        ],
    )

    config.add_tool(approved_tool)
    config.add_tool(unapproved_tool)

    # Step 2: Approve only instructions and one tool
    db.save_unapproved_config("stdio", "test_mixed_server", config)
    db.approve_instructions("stdio", "test_mixed_server", config.instructions)
    db.approve_tool("stdio", "test_mixed_server", "approved_tool", approved_tool)
    # Note: NOT approving unapproved_tool
    db.save_server_config("stdio", "test_mixed_server", config, ApprovalStatus.APPROVED)

    # Step 3: Test mixed approval status
    approval_status = db.get_server_approval_status("stdio", "test_mixed_server", config)

    assert approval_status["instructions_approved"]
    assert approval_status["tools"]["approved_tool"]
    assert not approval_status["tools"]["unapproved_tool"]

    # Test that we can distinguish between approved and unapproved tools
    assert db.is_tool_approved("stdio", "test_mixed_server", "approved_tool", approved_tool)
    assert not (
        db.is_tool_approved("stdio", "test_mixed_server", "unapproved_tool", unapproved_tool)
    )


@pytest.mark.asyncio()
async def test_tool_parameter_modification_blocking() -> None:
    """Test that changing tool parameters blocks only that tool."""

    temp_file = tempfile.NamedTemporaryFile(delete=False)

    db = MCPConfigDatabase(temp_file.name)

    # Original tool
    original_tool = MCPToolDefinition(
        name="param_test_tool",
        description="Tool for parameter testing",
        parameters=[
            MCPParameterDefinition(
                name="param1",
                description="Original param",
                type=ParameterType.STRING,
                required=True,
            )
        ],
    )

    # Modified tool (different parameter description)
    modified_tool = MCPToolDefinition(
        name="param_test_tool",
        description="Tool for parameter testing",  # Same description
        parameters=[
            MCPParameterDefinition(
                name="param1",
                description="MODIFIED param",
                type=ParameterType.STRING,
                required=True,
            )
        ],
    )

    # Test that parameter change is detected
    assert original_tool != modified_tool

    # Set up approval for original tool
    config = MCPServerConfig()
    config.add_tool(original_tool)

    db.save_unapproved_config("stdio", "param_test_server", config)
    db.approve_instructions("stdio", "param_test_server", config.instructions)
    db.approve_tool("stdio", "param_test_server", "param_test_tool", original_tool)

    # Test that modified tool is not approved
    assert db.is_tool_approved("stdio", "param_test_server", "param_test_tool", original_tool)
    assert not (db.is_tool_approved("stdio", "param_test_server", "param_test_tool", modified_tool))
