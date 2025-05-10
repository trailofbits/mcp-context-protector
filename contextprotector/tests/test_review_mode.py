"""
Tests for the MCP wrapper server review mode functionality.
"""

import os
import tempfile
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from io import StringIO

from ..mcp_wrapper import review_server_config, MCPWrapperServer
from ..mcp_config import MCPServerConfig


@pytest.mark.asyncio
async def test_review_mode_already_trusted():
    """Test review mode when config is already trusted."""
    # Create a temporary file for config storage
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_path = temp_file.name
    temp_file.close()

    # Set up a mock wrapper that simulates a trusted configuration
    mock_wrapper = MagicMock()
    mock_wrapper.config_approved = True
    mock_wrapper.server_identifier = "test_command"
    mock_wrapper.start_child_process = AsyncMock(return_value=None)
    mock_wrapper.stop_child_process = AsyncMock(return_value=None)

    # Patch the MCPWrapperServer.wrap_stdio to return our mock
    with patch.object(MCPWrapperServer, "wrap_stdio", return_value=mock_wrapper):
        # Create mock args
        with patch(
            "argparse.ArgumentParser.parse_args",
            return_value=MagicMock(
                review=True,
                command="test_command",
                url=None,
                config_file=temp_path,
                guardrail_provider=None,
                list_guardrail_providers=False,
            ),
        ):
            # Capture stdout for assertion
            with patch("sys.stdout", new=StringIO()) as fake_stdout:
                # Call the review function
                await review_server_config("stdio", "test_command", temp_path)

                # Check output
                output = fake_stdout.getvalue()
                assert "already trusted" in output
                assert "test_command" in output

    # Clean up
    os.unlink(temp_path)


@pytest.mark.asyncio
async def test_review_mode_new_server_approval():
    """Test review mode with a new server that gets approved."""
    # Create a temporary file for config storage
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_path = temp_file.name
    temp_file.close()

    # Set up a mock wrapper that simulates an untrusted configuration
    mock_wrapper = MagicMock()
    mock_wrapper.config_approved = False
    mock_wrapper.server_identifier = "test_command"
    mock_wrapper.saved_config = None
    mock_wrapper.current_config = MCPServerConfig()
    mock_wrapper.tool_specs = [
        MagicMock(name="tool1", description="Tool 1 description")
    ]
    mock_wrapper.guardrail_alert = None
    mock_wrapper.start_child_process = AsyncMock(return_value=None)
    mock_wrapper.stop_child_process = AsyncMock(return_value=None)
    mock_wrapper.config_db.save_server_config = MagicMock()

    # Patch the MCPWrapperServer.wrap_stdio to return our mock
    with patch.object(MCPWrapperServer, "wrap_stdio", return_value=mock_wrapper):
        # Mock user input to simulate 'yes' response
        with patch("builtins.input", return_value="yes"):
            # Capture stdout for assertion
            with patch("sys.stdout", new=StringIO()) as fake_stdout:
                # Call the review function
                await review_server_config("stdio", "test_command", temp_path)

                # Check output
                output = fake_stdout.getvalue()
                assert "not trusted or has changed" in output
                assert "new server" in output
                assert "TOOL LIST" in output
                assert "has been trusted" in output

    # Clean up
    os.unlink(temp_path)


@pytest.mark.asyncio
async def test_review_mode_modified_server_rejection():
    """Test review mode with a modified server that gets rejected."""
    # Create a temporary file for config storage
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_path = temp_file.name
    temp_file.close()

    # Create mock configs with differences
    saved_config = MCPServerConfig()
    current_config = MCPServerConfig()

    # Set up a mock wrapper that simulates a modified configuration
    mock_wrapper = MagicMock()
    mock_wrapper.config_approved = False
    mock_wrapper.server_identifier = "test_command"
    mock_wrapper.saved_config = saved_config
    mock_wrapper.current_config = current_config

    # Create a mock diff with differences
    mock_diff = MagicMock()
    mock_diff.has_differences.return_value = True
    mock_diff.__str__.return_value = "Mock diff output"

    # Set up the compare method to return our mock diff
    saved_config.compare = MagicMock(return_value=mock_diff)

    mock_wrapper.tool_specs = [
        MagicMock(name="tool1", description="Tool 1 description")
    ]
    mock_wrapper.guardrail_alert = None
    mock_wrapper.start_child_process = AsyncMock(return_value=None)
    mock_wrapper.stop_child_process = AsyncMock(return_value=None)
    mock_wrapper.config_db.save_server_config = MagicMock()

    # Patch the MCPWrapperServer.wrap_stdio to return our mock
    with patch.object(MCPWrapperServer, "wrap_stdio", return_value=mock_wrapper):
        # Mock user input to simulate 'no' response
        with patch("builtins.input", return_value="no"):
            # Capture stdout for assertion
            with patch("sys.stdout", new=StringIO()) as fake_stdout:
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
    os.unlink(temp_path)


@pytest.mark.asyncio
async def test_review_mode_with_guardrail_alert():
    """Test review mode with a configuration that triggers a guardrail alert."""
    # Create a temporary file for config storage
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_path = temp_file.name
    temp_file.close()

    # Set up a mock wrapper that simulates a guardrail alert
    mock_wrapper = MagicMock()
    mock_wrapper.config_approved = False
    mock_wrapper.server_identifier = "test_command"
    mock_wrapper.saved_config = None
    mock_wrapper.current_config = MCPServerConfig()
    mock_wrapper.tool_specs = [
        MagicMock(name="tool1", description="Tool 1 description")
    ]

    # Create a mock guardrail alert
    mock_wrapper.guardrail_alert = MagicMock()
    mock_wrapper.guardrail_alert.explanation = "Suspicious tool detected"

    mock_wrapper.start_child_process = AsyncMock(return_value=None)
    mock_wrapper.stop_child_process = AsyncMock(return_value=None)
    mock_wrapper.config_db.save_server_config = MagicMock()

    # Mock guardrail provider
    mock_provider = MagicMock()
    mock_provider.name = "mock_provider"

    # Patch the MCPWrapperServer.wrap_stdio to return our mock
    with patch.object(MCPWrapperServer, "wrap_stdio", return_value=mock_wrapper):
        # Mock user input to simulate 'no' response
        with patch("builtins.input", return_value="no"):
            # Capture stdout for assertion
            with patch("sys.stdout", new=StringIO()) as fake_stdout:
                # Call the review function
                await review_server_config(
                    "stdio", "test_command", temp_path, mock_provider
                )

                # Check output
                output = fake_stdout.getvalue()
                assert "GUARDRAIL CHECK" in output
                assert "ALERT" in output
                assert "Suspicious tool detected" in output
                assert "NOT been trusted" in output

                # Verify save_server_config was NOT called
                mock_wrapper.config_db.save_server_config.assert_not_called()

    # Clean up
    os.unlink(temp_path)
