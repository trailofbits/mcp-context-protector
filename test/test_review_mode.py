"""
Tests for the MCP wrapper server review mode functionality.
"""

import sys
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Configure path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import (but don't use) the shared utility function for patching

from contextprotector.approval_cli import review_server_config
from contextprotector.mcp_config import MCPServerConfig
from contextprotector.mcp_wrapper import MCPWrapperServer

from .test_utils import approve_server_config_using_review


@pytest.mark.asyncio()
async def test_review_mode_already_trusted() -> None:
    """Test review mode when config is already trusted."""
    # Create a temporary file for config storage
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_path = temp_file.name
    temp_file.close()

    # Set up a mock wrapper that simulates a trusted configuration
    # Use MagicMock for the base with AsyncMock only for async methods
    mock_wrapper = MagicMock()
    mock_wrapper.config_approved = True
    mock_wrapper.server_identifier = "test_command"
    mock_wrapper.connect = AsyncMock(return_value=None)
    mock_wrapper.stop_child_process = AsyncMock(return_value=None)

    # Patch the MCPWrapperServer.from_config to return our mock
    # and also patch the shared utility to avoid external calls
    mock_approve_func = AsyncMock(return_value=None)
    with (
        patch.object(MCPWrapperServer, "from_config", return_value=mock_wrapper),
        patch.object(approve_server_config_using_review, "__call__", mock_approve_func),
        patch("sys.stdout", new=StringIO()) as fake_stdout,
    ):
        # Call the review function directly since we're testing its logic
        await review_server_config("stdio", "test_command", temp_path)

        # Check output
        output = fake_stdout.getvalue()
        assert "already trusted" in output
        assert "test_command" in output

        # Verify approve function wasn't called (since already trusted)
        mock_approve_func.assert_not_called()

    # Clean up
    Path(temp_path).unlink()


@pytest.mark.asyncio()
async def test_review_mode_new_server_approval() -> None:
    """Test review mode with a new server that gets approved."""
    # Create a temporary file for config storage
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_path = temp_file.name
    temp_file.close()

    # Set up a mock wrapper that simulates an untrusted configuration
    # Use MagicMock for the wrapper itself to avoid coroutine issues with sync methods
    mock_wrapper = MagicMock()
    mock_wrapper.config_approved = False
    mock_wrapper.server_identifier = "test_command"
    mock_wrapper.saved_config = None
    mock_wrapper.current_config = MCPServerConfig()
    mock_wrapper.tool_specs = [MagicMock(name="tool1", description="Tool 1 description")]
    mock_wrapper.guardrail_alert = None
    mock_wrapper.guardrail_provider = None
    # Explicitly mock synchronous methods
    mock_wrapper.get_server_identifier = MagicMock(return_value="test_command")
    mock_wrapper.connection_type = "stdio"
    # Use AsyncMock only for actual async methods
    mock_wrapper.connect = AsyncMock(return_value=None)
    mock_wrapper.stop_child_process = AsyncMock(return_value=None)
    # Mock the config_db with proper methods (all are synchronous)
    mock_wrapper.config_db = MagicMock()
    mock_wrapper.config_db.save_server_config = MagicMock()
    mock_wrapper.config_db.approve_instructions = MagicMock()
    mock_wrapper.config_db.approve_tool = MagicMock()

    # Patch the MCPWrapperServer.from_config to return our mock
    with (
        patch.object(MCPWrapperServer, "from_config", return_value=mock_wrapper),
        patch("builtins.input", return_value="yes"),
        patch("sys.stdout", new=StringIO()) as fake_stdout,
    ):
        # Call the review function
        await review_server_config("stdio", "test_command", temp_path)

        # Check output
        output = fake_stdout.getvalue()
        assert "not trusted or has changed" in output
        assert "new server" in output
        assert "TOOL LIST" in output
        assert "has been trusted" in output

    # Clean up
    Path(temp_path).unlink()


@pytest.mark.asyncio()
async def test_review_mode_modified_server_rejection() -> None:
    """Test review mode with a modified server that gets rejected."""
    # Create a temporary file for config storage
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_path = temp_file.name
    temp_file.close()

    # Create mock configs with differences
    saved_config = MCPServerConfig()
    current_config = MCPServerConfig()

    # Set up a mock wrapper that simulates a modified configuration
    # Use MagicMock for the base with AsyncMock only for async methods
    mock_wrapper = MagicMock()
    mock_wrapper.config_approved = False
    mock_wrapper.server_identifier = "test_command"
    mock_wrapper.saved_config = saved_config
    mock_wrapper.current_config = current_config

    # Create a mock diff with differences - use MagicMock not AsyncMock
    # Since diff.has_differences() is called synchronously
    mock_diff = MagicMock()
    mock_diff.has_differences.return_value = True
    mock_diff.__str__.return_value = "Mock diff output"

    # Set up the compare method to return our mock diff directly, not as a coroutine
    saved_config.compare = MagicMock(return_value=mock_diff)

    mock_wrapper.tool_specs = [AsyncMock(name="tool1", description="Tool 1 description")]
    mock_wrapper.guardrail_alert = None
    mock_wrapper.connect = AsyncMock(return_value=None)
    mock_wrapper.stop_child_process = AsyncMock(return_value=None)
    mock_wrapper.config_db.save_server_config = MagicMock()

    # Patch the MCPWrapperServer.from_config to return our mock
    with (
        patch.object(MCPWrapperServer, "from_config", return_value=mock_wrapper),
        patch("builtins.input", return_value="no"),
        patch("sys.stdout", new=StringIO()) as fake_stdout,
    ):
        # Call the review function
        await review_server_config("stdio", "test_command", temp_path)

        # Check output
        output = fake_stdout.getvalue()
        assert "not trusted or has changed" in output
        assert "Previous configuration found" in output
        assert "CONFIGURATION DIFFERENCES" in output
        assert "Mock diff output" in output
        assert "NOT been trusted" in output

        # Verify save_server_config was NOT called
        mock_wrapper.config_db.save_server_config.assert_not_called()

    # Clean up
    Path(temp_path).unlink()


@pytest.mark.asyncio()
async def test_review_mode_with_guardrail_alert() -> None:
    """Test review mode with a configuration that triggers a guardrail alert."""
    # Create a temporary file for config storage
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_path = temp_file.name
    temp_file.close()

    # Set up a mock wrapper that simulates a guardrail alert
    # Use MagicMock for the base with AsyncMock only for async methods
    mock_wrapper = MagicMock()
    mock_wrapper.config_approved = False
    mock_wrapper.server_identifier = "test_command"
    mock_wrapper.saved_config = None
    mock_wrapper.current_config = MCPServerConfig()
    mock_wrapper.tool_specs = [MagicMock(name="tool1", description="Tool 1 description")]

    # Create a mock guardrail alert - use regular MagicMock
    mock_wrapper.guardrail_alert = MagicMock()
    mock_wrapper.guardrail_alert.explanation = "Suspicious tool detected"

    mock_wrapper.connect = AsyncMock(return_value=None)
    mock_wrapper.stop_child_process = AsyncMock(return_value=None)
    mock_wrapper.config_db.save_server_config = MagicMock()

    # Mock guardrail provider - use regular MagicMock
    mock_provider = MagicMock()
    mock_provider.name = "mock_provider"

    # Patch the MCPWrapperServer.from_config to return our mock
    with (
        patch.object(MCPWrapperServer, "from_config", return_value=mock_wrapper),
        patch("builtins.input", return_value="no"),
        patch("sys.stdout", new=StringIO()) as fake_stdout,
    ):
        # Call the review function
        await review_server_config("stdio", "test_command", temp_path, mock_provider)

        # Check output
        output = fake_stdout.getvalue()
        assert "GUARDRAIL CHECK" in output
        assert "ALERT" in output
        assert "NOT been trusted" in output

        # Verify save_server_config was NOT called
        mock_wrapper.config_db.save_server_config.assert_not_called()

    # Clean up
    Path(temp_path).unlink()
