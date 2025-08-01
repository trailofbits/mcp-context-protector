"""
Simplified tests for the quarantine_release functionality.
"""

import json
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from contextprotector.guardrail_providers.mock_provider import MockGuardrailProvider
from contextprotector.mcp_wrapper import MCPWrapperServer
from contextprotector.quarantine import ToolResponseQuarantine


@pytest.fixture()
def setup_quarantine_test() -> Generator[tuple[ToolResponseQuarantine, str, str], None, None]:
    """Create a test quarantine with sample data."""
    # Create a temporary file for the quarantine
    tmp_file = tempfile.NamedTemporaryFile(delete=False)
    tmp_file.close()

    # Initialize the quarantine
    quarantine = ToolResponseQuarantine(tmp_file.name)

    # Add a test response
    test_tool_name = "test_tool"
    test_tool_input = {"param": "value"}
    test_tool_output = "This is a test tool response"
    test_reason = "Test quarantine reason"

    # Add a quarantined response
    response_id = quarantine.quarantine_response(
        tool_name=test_tool_name,
        tool_input=test_tool_input,
        tool_output=test_tool_output,
        reason=test_reason,
    )

    # Get the response and mark it as released
    quarantine.release_response(response_id)

    # Add another response that is not released
    unreleased_id = quarantine.quarantine_response(
        tool_name="unreleased_tool",
        tool_input={"param": "value2"},
        tool_output="This should not be released",
        reason="Not released test",
    )

    # Return the quarantine file and IDs
    yield {
        "quarantine_path": tmp_file.name,
        "released_id": response_id,
        "unreleased_id": unreleased_id,
        "test_tool_name": test_tool_name,
        "test_tool_input": test_tool_input,
        "test_tool_output": test_tool_output,
        "test_reason": test_reason,
    }

    # Clean up
    if Path(tmp_file.name).exists():
        Path(tmp_file.name).unlink()


@pytest.mark.asyncio()
async def test_quarantine_release_success(setup_quarantine_test: any) -> None:
    """Test successfully releasing a quarantined response."""
    test_data = setup_quarantine_test

    # Create a wrapper with a guardrail provider and quarantine
    provider = MockGuardrailProvider()
    wrapper = MCPWrapperServer(
        guardrail_provider=provider, quarantine_path=test_data["quarantine_path"]
    )

    # Call the quarantine_release tool handler
    result = await wrapper._handle_quarantine_release({"uuid": test_data["released_id"]})

    # Verify the result
    assert len(result) == 1
    assert result[0].type == "text"

    # Parse the JSON response
    response_data = json.loads(result[0].text)
    assert response_data["status"] == "completed"

    # Parse the nested response
    tool_info = json.loads(response_data["response"])
    assert tool_info["tool_name"] == test_data["test_tool_name"]
    assert tool_info["tool_input"] == test_data["test_tool_input"]
    assert tool_info["tool_output"] == test_data["test_tool_output"]
    assert tool_info["quarantine_reason"] == test_data["test_reason"]
    assert tool_info["quarantine_id"] == test_data["released_id"]

    # Verify that the response has been deleted from the quarantine
    quarantine = ToolResponseQuarantine(test_data["quarantine_path"])
    assert quarantine.get_response(test_data["released_id"]) is None


@pytest.mark.asyncio()
async def test_quarantine_release_unreleased_fails(setup_quarantine_test: any) -> None:
    """Test that attempting to release an unreleased response fails."""
    test_data = setup_quarantine_test

    # Create a wrapper with a guardrail provider and quarantine
    provider = MockGuardrailProvider()
    wrapper = MCPWrapperServer(
        guardrail_provider=provider, quarantine_path=test_data["quarantine_path"]
    )

    # Call the quarantine_release tool handler with an unreleased ID
    result = await wrapper._handle_quarantine_release({"uuid": test_data["unreleased_id"]})

    # Verify that the correct error message is returned as TextContent
    assert len(result) == 1
    assert result[0].type == "text"
    error_msg = result[0].text
    assert "not marked for release" in error_msg
    assert "--review-quarantine" in error_msg

    # Verify that the response still exists in the quarantine
    quarantine = ToolResponseQuarantine(test_data["quarantine_path"])
    assert quarantine.get_response(test_data["unreleased_id"]) is not None


@pytest.mark.asyncio()
async def test_quarantine_release_invalid_uuid(setup_quarantine_test: any) -> None:
    """Test that attempting to release with an invalid UUID fails."""
    test_data = setup_quarantine_test

    # Create a wrapper with a guardrail provider and quarantine
    provider = MockGuardrailProvider()
    wrapper = MCPWrapperServer(
        guardrail_provider=provider, quarantine_path=test_data["quarantine_path"]
    )

    # Call the quarantine_release tool handler with an invalid UUID
    with pytest.raises(ValueError, match="No quarantined response found"):
        await wrapper._handle_quarantine_release({"uuid": "invalid-uuid"})
