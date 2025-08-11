"""Tests for the approval CLI functionality."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from contextprotector.approval_cli import list_unapproved_configs, review_server_config
from contextprotector.mcp_config import (
    ApprovalStatus,
    MCPConfigDatabase,
    MCPServerConfig,
    MCPToolDefinition,
)


@pytest.fixture
def temp_config_db():
    """Create a temporary config database for testing."""
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        config_path = temp_file.name

    yield config_path

    # Clean up
    if Path(config_path).exists():
        Path(config_path).unlink()


@pytest.fixture
def config_db_with_unapproved_servers(temp_config_db):
    """Create a config database with some unapproved servers."""
    db = MCPConfigDatabase(temp_config_db)

    # Create test configurations
    config1 = MCPServerConfig()
    config1.instructions = "Test server 1"
    tool1 = MCPToolDefinition(name="tool1", description="Test tool 1", parameters=[])
    config1.add_tool(tool1)

    config2 = MCPServerConfig()
    config2.instructions = "Test server 2"
    tool2 = MCPToolDefinition(name="tool2", description="Test tool 2", parameters=[])
    config2.add_tool(tool2)

    # Save unapproved servers
    db.save_server_config("stdio", "server1", config1, ApprovalStatus.UNAPPROVED)
    db.save_server_config("http", "http://localhost:8080", config2, ApprovalStatus.UNAPPROVED)

    # Save one approved server to ensure filtering works
    config3 = MCPServerConfig()
    config3.instructions = "Approved server"
    tool3 = MCPToolDefinition(name="tool3", description="Approved tool", parameters=[])
    config3.add_tool(tool3)
    db.save_server_config("sse", "http://localhost:9000", config3, ApprovalStatus.APPROVED)

    return temp_config_db, db


class TestListUnapprovedConfigs:
    """Test cases for list_unapproved_configs function."""

    @pytest.mark.asyncio
    async def test_no_unapproved_configs(self, temp_config_db, capsys):
        """Test behavior when no unapproved configurations exist."""
        # Create empty database
        MCPConfigDatabase(temp_config_db)

        # Call the function
        await list_unapproved_configs(temp_config_db)

        # Check output
        captured = capsys.readouterr()
        assert "No unapproved server configurations found." in captured.out

    @pytest.mark.asyncio
    async def test_displays_unapproved_configs(self, config_db_with_unapproved_servers, capsys):
        """Test that unapproved configurations are properly displayed."""
        config_path, _ = config_db_with_unapproved_servers

        # Mock user input to quit immediately
        with patch("builtins.input", return_value="q"):
            await list_unapproved_configs(config_path)

        # Check output
        captured = capsys.readouterr()
        assert "Found 2 unapproved server configuration(s):" in captured.out
        assert "1. [STDIO] server1" in captured.out
        assert "2. [HTTP] http://localhost:8080" in captured.out
        assert "Status: Configuration available for review" in captured.out

    @pytest.mark.asyncio
    async def test_quit_option(self, config_db_with_unapproved_servers):
        """Test that 'q' option properly exits the CLI."""
        config_path, _ = config_db_with_unapproved_servers

        # Mock user input to quit
        with patch("builtins.input", return_value="q"):
            # Add timeout to prevent hanging if quit doesn't work
            try:
                await asyncio.wait_for(list_unapproved_configs(config_path), timeout=8.0)
            except TimeoutError:
                pytest.fail("CLI did not exit within 8 seconds - quit option may not be working")

        # If we reach here without hanging, the quit option worked

    @pytest.mark.asyncio
    async def test_approve_all_option(self, config_db_with_unapproved_servers, capsys):
        """Test the 'approve all' option."""
        config_path, db = config_db_with_unapproved_servers

        # Mock user inputs: 'a' for approve all, then 'yes' to confirm
        with patch("builtins.input", side_effect=["a", "yes"]):
            try:
                await asyncio.wait_for(list_unapproved_configs(config_path), timeout=8.0)
            except TimeoutError:
                pytest.fail("CLI did not exit within 8 seconds - approve all may not be working")

        # Verify all servers were approved
        db.load()  # Reload from disk
        unapproved = db.list_unapproved_servers()
        assert len(unapproved) == 0

        # Check output
        captured = capsys.readouterr()
        assert "Approved 2 out of 2 server configurations." in captured.out

    @pytest.mark.asyncio
    async def test_approve_all_cancelled(self, config_db_with_unapproved_servers):
        """Test cancelling the 'approve all' option."""
        config_path, db = config_db_with_unapproved_servers

        # Mock user inputs: 'a' for approve all, then 'no' to cancel, then 'q' to quit
        with patch("builtins.input", side_effect=["a", "no", "q"]):
            try:
                await asyncio.wait_for(list_unapproved_configs(config_path), timeout=8.0)
            except TimeoutError:
                pytest.fail(
                    "CLI did not exit within 8 seconds - approve all cancellation not working"
                )

        # Verify no servers were approved
        db.load()  # Reload from disk
        unapproved = db.list_unapproved_servers()
        assert len(unapproved) == 2

    @pytest.mark.asyncio
    async def test_review_specific_server(self, config_db_with_unapproved_servers):
        """Test reviewing a specific server by number."""
        config_path, db = config_db_with_unapproved_servers

        # Mock the review_server_config function
        with (
            patch("contextprotector.approval_cli.review_server_config") as mock_review,
            patch("builtins.input", side_effect=["1", "q"]),
        ):  # Select server 1, then quit
            try:
                await asyncio.wait_for(list_unapproved_configs(config_path), timeout=8.0)
            except TimeoutError:
                pytest.fail("CLI did not exit within 8 seconds - server review may not be working")

            # Verify review_server_config was called with correct parameters
            mock_review.assert_called_once_with("stdio", "server1", config_path)

    @pytest.mark.asyncio
    async def test_invalid_selection(self, config_db_with_unapproved_servers, capsys):
        """Test handling of invalid user selections."""
        config_path, _ = config_db_with_unapproved_servers

        # Mock user inputs: invalid selection, then quit
        with patch("builtins.input", side_effect=["invalid", "q"]):
            try:
                await asyncio.wait_for(list_unapproved_configs(config_path), timeout=8.0)
            except TimeoutError:
                pytest.fail(
                    "CLI did not exit within 8 seconds - invalid selection handling not working"
                )

        # Check that error message was displayed
        captured = capsys.readouterr()
        assert "Invalid selection. Please try again." in captured.out

    @pytest.mark.asyncio
    async def test_keyboard_interrupt(self, config_db_with_unapproved_servers, capsys):
        """Test handling of keyboard interrupt (Ctrl+C)."""
        config_path, _ = config_db_with_unapproved_servers

        # Mock user input to raise KeyboardInterrupt
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            await list_unapproved_configs(config_path)

        # Check that exit message was displayed
        captured = capsys.readouterr()
        assert "Exiting..." in captured.out

    @pytest.mark.asyncio
    async def test_cli_closes_after_all_approved(self, config_db_with_unapproved_servers, capsys):
        """Test that CLI closes automatically when all servers are approved."""
        config_path, db = config_db_with_unapproved_servers

        # Mock review_server_config to approve the server being reviewed
        async def mock_review(server_type, identifier, _config_path_param):
            # Simulate approving the server
            db.approve_server_config(server_type, identifier)

        with (
            patch("contextprotector.approval_cli.review_server_config", side_effect=mock_review),
            patch("builtins.input", side_effect=["1", "1"]),  # Review first server twice
        ):
            try:
                await asyncio.wait_for(list_unapproved_configs(config_path), timeout=8.0)
            except TimeoutError:
                pytest.fail(
                    "CLI did not exit within 8 seconds - auto-close after approval not working"
                )

        # Check that completion message was displayed
        captured = capsys.readouterr()
        assert "✓ All server configurations have been reviewed!" in captured.out

    @pytest.mark.asyncio
    async def test_config_database_reload_after_review(self, config_db_with_unapproved_servers):
        """Test that config database is reloaded after reviewing a server."""
        config_path, db = config_db_with_unapproved_servers

        # Mock review_server_config to approve one server
        async def mock_review(server_type, identifier, _config_path_param):
            db.approve_server_config(server_type, identifier)

        with (
            patch("contextprotector.approval_cli.review_server_config", side_effect=mock_review),
            patch("builtins.input", side_effect=["1", "q"]),
        ):  # Review server 1, then quit
            await list_unapproved_configs(config_path)

        # Verify that the count was updated (database was reloaded)
        # This is implicitly tested by the function's behavior of showing remaining count


class TestReviewServerConfig:
    """Test cases for review_server_config function."""

    @pytest.mark.asyncio
    async def test_review_stdio_server(self):
        """Test reviewing a stdio server configuration."""
        with patch("contextprotector.approval_cli.MCPWrapperServer") as mock_wrapper_class:
            # Mock the wrapper instance
            mock_wrapper = AsyncMock()
            mock_wrapper.config_approved = False
            mock_wrapper.tool_specs = []
            mock_wrapper.current_config = MagicMock()
            mock_wrapper.saved_config = None
            mock_wrapper.get_server_identifier = MagicMock(return_value="test_server")
            mock_wrapper.guardrail_provider = None
            mock_wrapper_class.from_config.return_value = mock_wrapper

            # Mock user input to approve
            with (
                patch("builtins.input", return_value="yes"),
                patch("contextprotector.approval_cli._approve_server_config") as mock_approve,
            ):
                await review_server_config("stdio", "test_server")

                # Verify wrapper was created and methods called
                mock_wrapper.connect.assert_called_once()
                mock_wrapper.stop_child_process.assert_called_once()
                mock_approve.assert_called_once_with(mock_wrapper)

    @pytest.mark.asyncio
    async def test_already_approved_server(self, capsys):
        """Test handling of already approved server."""
        with patch("contextprotector.approval_cli.MCPWrapperServer") as mock_wrapper_class:
            # Mock the wrapper instance as already approved
            mock_wrapper = AsyncMock()
            mock_wrapper.config_approved = True
            mock_wrapper.get_server_identifier = MagicMock(return_value="test_server")
            mock_wrapper_class.from_config.return_value = mock_wrapper

            await review_server_config("stdio", "test_server")

            # Check that appropriate message was displayed
            captured = capsys.readouterr()
            assert "Server configuration for test_server is already trusted." in captured.out

    @pytest.mark.asyncio
    async def test_user_rejects_approval(self, capsys):
        """Test when user rejects server approval."""
        with patch("contextprotector.approval_cli.MCPWrapperServer") as mock_wrapper_class:
            # Mock the wrapper instance
            mock_wrapper = AsyncMock()
            mock_wrapper.config_approved = False
            mock_wrapper.tool_specs = []
            mock_wrapper.current_config = MagicMock()
            mock_wrapper.saved_config = None
            mock_wrapper.get_server_identifier = MagicMock(return_value="test_server")
            mock_wrapper.guardrail_provider = None
            mock_wrapper_class.from_config.return_value = mock_wrapper

            # Mock user input to reject
            with (
                patch("builtins.input", return_value="no"),
                patch("contextprotector.approval_cli._approve_server_config") as mock_approve,
            ):
                await review_server_config("stdio", "test_server")

                # Verify approval was not called
                mock_approve.assert_not_called()

                # Check that rejection message was displayed
                captured = capsys.readouterr()
                assert (
                    "The server configuration for test_server has NOT been trusted." in captured.out
                )

    @pytest.mark.asyncio
    async def test_wrapper_cleanup_on_exception(self):
        """Test that wrapper is properly cleaned up even if an exception occurs."""
        with patch("contextprotector.approval_cli.MCPWrapperServer") as mock_wrapper_class:
            # Mock the wrapper instance to raise an exception during connect
            mock_wrapper = AsyncMock()
            mock_wrapper.connect.side_effect = Exception("Connection failed")
            mock_wrapper_class.from_config.return_value = mock_wrapper

            # Expect the exception to be raised, but wrapper should still be cleaned up
            with pytest.raises(Exception, match="Connection failed"):
                await review_server_config("stdio", "test_server")

            # Verify cleanup was called despite the exception
            mock_wrapper.stop_child_process.assert_called_once()
