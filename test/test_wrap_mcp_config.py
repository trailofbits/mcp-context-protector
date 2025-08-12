"""
Tests for the wrap_mcp_config_file functionality.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from contextprotector.mcp_config import wrap_mcp_config_file


@pytest.fixture
def temp_config_file():
    """Create a temporary config file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        temp_path = f.name
    yield temp_path
    # Cleanup
    if Path(temp_path).exists():
        Path(temp_path).unlink()
    backup_path = f"{temp_path}.backup"
    if Path(backup_path).exists():
        Path(backup_path).unlink()


@pytest.fixture
def mock_protector_script():
    """Mock the protector script path."""
    return "/mock/path/mcp-context-protector.sh"


def test_wrap_command_based_servers(temp_config_file, mock_protector_script):
    """Test wrapping command-based (stdio) servers."""
    # Create initial config with command-based servers
    initial_config = {
        "mcpServers": {
            "server1": {"command": "/bin/npx", "args": ["server1", "my-arg"]},
            "simple_server": {"command": "python", "args": ["-m", "my_server"]},
            "no_args_server": {"command": "/usr/bin/node"},
        }
    }

    # Write initial config
    with open(temp_config_file, "w") as f:
        json.dump(initial_config, f, indent=2)

    # Mock the protector script path
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.resolve", return_value=Path(mock_protector_script)),
        patch("contextprotector.mcp_config.pathlib.Path") as mock_path,
    ):
        mock_path.return_value.parent.parent.parent = Path("/mock")
        mock_path.return_value.__truediv__ = lambda _, other: Path("/mock") / other

        # Mock sys.exit to capture exit calls
        with patch("sys.exit") as mock_exit:
            wrap_mcp_config_file(temp_config_file)
            mock_exit.assert_not_called()

    # Read the modified config
    with open(temp_config_file) as f:
        modified_config = json.load(f)

    # Verify servers were wrapped correctly
    servers = modified_config["mcpServers"]

    # Check server1 - has args
    assert servers["server1"]["command"] == mock_protector_script
    assert servers["server1"]["args"] == ["--command", "/bin/npx server1 my-arg"]

    # Check simple_server - has args
    assert servers["simple_server"]["command"] == mock_protector_script
    assert servers["simple_server"]["args"] == ["--command", "python -m my_server"]

    # Check no_args_server - no args originally
    assert servers["no_args_server"]["command"] == mock_protector_script
    assert servers["no_args_server"]["args"] == ["--command", "/usr/bin/node"]

    # Verify backup was created
    backup_path = f"{temp_config_file}.backup"
    assert Path(backup_path).exists()

    # Verify backup contains original config
    with open(backup_path) as f:
        backup_config = json.load(f)
    assert backup_config == initial_config


def test_wrap_http_sse_servers(temp_config_file, mock_protector_script):
    """Test wrapping HTTP and SSE servers."""
    # Create initial config with HTTP/SSE servers
    initial_config = {
        "mcpServers": {
            "http_server": {"url": "https://api.example.com/mcp"},
            "sse_server": {"url": "https://api.example.com/sse/events"},
            "events_server": {"url": "https://api.example.com/events"},
        }
    }

    # Write initial config
    with open(temp_config_file, "w") as f:
        json.dump(initial_config, f, indent=2)

    # Mock the protector script path
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.resolve", return_value=Path(mock_protector_script)),
        patch("contextprotector.mcp_config.pathlib.Path") as mock_path,
    ):
        mock_path.return_value.parent.parent.parent = Path("/mock")
        mock_path.return_value.__truediv__ = lambda _, other: Path("/mock") / other

        # Mock sys.exit to capture exit calls
        with patch("sys.exit") as mock_exit:
            wrap_mcp_config_file(temp_config_file)
            mock_exit.assert_not_called()

    # Read the modified config
    with open(temp_config_file) as f:
        modified_config = json.load(f)

    # Verify servers were wrapped correctly
    servers = modified_config["mcpServers"]

    # Check http_server - regular HTTP
    assert servers["http_server"]["command"] == mock_protector_script
    assert servers["http_server"]["args"] == ["--url", "https://api.example.com/mcp"]
    assert "url" not in servers["http_server"]

    # Check sse_server - SSE based on path
    assert servers["sse_server"]["command"] == mock_protector_script
    assert servers["sse_server"]["args"] == ["--sse-url", "https://api.example.com/sse/events"]
    assert "url" not in servers["sse_server"]

    # Check events_server - SSE based on path
    assert servers["events_server"]["command"] == mock_protector_script
    assert servers["events_server"]["args"] == ["--sse-url", "https://api.example.com/events"]
    assert "url" not in servers["events_server"]


def test_mixed_servers(temp_config_file, mock_protector_script):
    """Test wrapping a mix of command-based and HTTP/SSE servers."""
    # Create initial config with mixed server types
    initial_config = {
        "mcpServers": {
            "stdio_server": {"command": "python", "args": ["-m", "stdio_server"]},
            "http_server": {"url": "https://api.example.com/mcp"},
            "sse_server": {"url": "https://api.example.com/sse/stream"},
        }
    }

    # Write initial config
    with open(temp_config_file, "w") as f:
        json.dump(initial_config, f, indent=2)

    # Mock the protector script path
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.resolve", return_value=Path(mock_protector_script)),
        patch("contextprotector.mcp_config.pathlib.Path") as mock_path,
    ):
        mock_path.return_value.parent.parent.parent = Path("/mock")
        mock_path.return_value.__truediv__ = lambda _, other: Path("/mock") / other

        # Mock sys.exit to capture exit calls
        with patch("sys.exit") as mock_exit:
            wrap_mcp_config_file(temp_config_file)
            mock_exit.assert_not_called()

    # Read the modified config
    with open(temp_config_file) as f:
        modified_config = json.load(f)

    # Verify all servers were wrapped correctly
    servers = modified_config["mcpServers"]

    assert servers["stdio_server"]["command"] == mock_protector_script
    assert servers["stdio_server"]["args"] == ["--command", "python -m stdio_server"]

    assert servers["http_server"]["command"] == mock_protector_script
    assert servers["http_server"]["args"] == ["--url", "https://api.example.com/mcp"]

    assert servers["sse_server"]["command"] == mock_protector_script
    assert servers["sse_server"]["args"] == ["--sse-url", "https://api.example.com/sse/stream"]


def test_already_wrapped_servers(temp_config_file, mock_protector_script):
    """Test that already wrapped servers are skipped."""
    # Create config with already wrapped servers
    initial_config = {
        "mcpServers": {
            "already_wrapped": {
                "command": mock_protector_script,
                "args": ["--command", "python -m server"],
            },
            "not_wrapped": {"command": "python", "args": ["-m", "server"]},
        }
    }

    # Write initial config
    with open(temp_config_file, "w") as f:
        json.dump(initial_config, f, indent=2)

    # Mock the protector script path
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.resolve", return_value=Path(mock_protector_script)),
        patch("contextprotector.mcp_config.pathlib.Path") as mock_path,
        patch("contextprotector.mcp_config.logger") as mock_logger,
    ):
        mock_path.return_value.parent.parent.parent = Path("/mock")
        mock_path.return_value.__truediv__ = lambda _, other: Path("/mock") / other

        # Mock sys.exit to capture exit calls
        with patch("sys.exit") as mock_exit:
            wrap_mcp_config_file(temp_config_file)
            mock_exit.assert_not_called()

        # Verify skip message was logged
        mock_logger.info.assert_any_call(
            "Server '%s' is already wrapped, skipping", "already_wrapped"
        )

    # Read the modified config
    with open(temp_config_file) as f:
        modified_config = json.load(f)

    servers = modified_config["mcpServers"]

    # Already wrapped server should be unchanged
    assert servers["already_wrapped"]["command"] == mock_protector_script
    assert servers["already_wrapped"]["args"] == ["--command", "python -m server"]

    # Not wrapped server should be wrapped
    assert servers["not_wrapped"]["command"] == mock_protector_script
    assert servers["not_wrapped"]["args"] == ["--command", "python -m server"]


def test_invalid_server_configs(temp_config_file, mock_protector_script):
    """Test handling of invalid server configurations."""
    # Create config with invalid servers
    initial_config = {
        "mcpServers": {
            "invalid_server": "not a dict",
            "no_transport": {"other_field": "value"},
            "valid_server": {"command": "python", "args": ["-m", "server"]},
        }
    }

    # Write initial config
    with open(temp_config_file, "w") as f:
        json.dump(initial_config, f, indent=2)

    # Mock the protector script path and logging
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.resolve", return_value=Path(mock_protector_script)),
        patch("contextprotector.mcp_config.pathlib.Path") as mock_path,
        patch("contextprotector.mcp_config.logger") as mock_logger,
    ):
        mock_path.return_value.parent.parent.parent = Path("/mock")
        mock_path.return_value.__truediv__ = lambda _, other: Path("/mock") / other

        # Mock sys.exit to capture exit calls
        with patch("sys.exit") as mock_exit:
            wrap_mcp_config_file(temp_config_file)
            mock_exit.assert_not_called()

        # Verify warning messages were logged
        mock_logger.warning.assert_any_call(
            "Skipping server '%s' - invalid configuration", "invalid_server"
        )
        mock_logger.warning.assert_any_call(
            "Server '%s' has no recognized transport method, skipping", "no_transport"
        )

    # Read the modified config
    with open(temp_config_file) as f:
        modified_config = json.load(f)

    servers = modified_config["mcpServers"]

    # Invalid servers should be unchanged
    assert servers["invalid_server"] == "not a dict"
    assert servers["no_transport"] == {"other_field": "value"}

    # Valid server should be wrapped
    assert servers["valid_server"]["command"] == mock_protector_script
    assert servers["valid_server"]["args"] == ["--command", "python -m server"]


def test_file_not_found():
    """Test error handling when config file doesn't exist."""
    with pytest.raises(SystemExit) as exc_info:
        wrap_mcp_config_file("nonexistent.json")

    assert exc_info.value.code == 1


def test_protector_script_not_found(temp_config_file):
    """Test error handling when protector script doesn't exist."""
    # Create minimal valid config
    config = {"mcpServers": {"test": {"command": "test"}}}
    with open(temp_config_file, "w") as f:
        json.dump(config, f)

    # Mock script doesn't exist
    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(SystemExit) as exc_info:
            wrap_mcp_config_file(temp_config_file)

        assert exc_info.value.code == 1


def test_invalid_json(temp_config_file):
    """Test error handling for invalid JSON."""
    # Write invalid JSON
    with open(temp_config_file, "w") as f:
        f.write("{ invalid json }")

    with pytest.raises(SystemExit) as exc_info:
        wrap_mcp_config_file(temp_config_file)

    assert exc_info.value.code == 1


def test_no_mcp_servers_section(temp_config_file):
    """Test error handling when mcpServers section is missing."""
    # Create config without mcpServers
    config = {"otherSection": {}}
    with open(temp_config_file, "w") as f:
        json.dump(config, f)

    with pytest.raises(SystemExit) as exc_info:
        wrap_mcp_config_file(temp_config_file)

    assert exc_info.value.code == 1


def test_invalid_mcp_servers_section(temp_config_file):
    """Test error handling when mcpServers is not a dictionary."""
    # Create config with invalid mcpServers
    config = {"mcpServers": "not a dict"}
    with open(temp_config_file, "w") as f:
        json.dump(config, f)

    with pytest.raises(SystemExit) as exc_info:
        wrap_mcp_config_file(temp_config_file)

    assert exc_info.value.code == 1


def test_backup_creation_failure(temp_config_file):
    """Test error handling when backup creation fails."""
    # Create minimal valid config
    config = {"mcpServers": {"test": {"command": "test"}}}
    with open(temp_config_file, "w") as f:
        json.dump(config, f)

    # Mock backup creation failure
    backup_exception = Exception("Backup failed")
    with patch("shutil.copy2", side_effect=backup_exception):
        with pytest.raises(SystemExit) as exc_info:
            wrap_mcp_config_file(temp_config_file)

        assert exc_info.value.code == 1


def test_write_failure_with_recovery(temp_config_file, mock_protector_script):
    """Test error handling when writing modified config fails, and backup recovery."""
    # Create initial config
    initial_config = {
        "mcpServers": {"test_server": {"command": "python", "args": ["-m", "server"]}}
    }

    with open(temp_config_file, "w") as f:
        json.dump(initial_config, f, indent=2)

    # Mock successful backup creation but failed write
    write_exception = Exception("Write failed")

    def open_side_effect(path, mode="r"):
        if "backup" in path or mode == "r":
            return open(path, mode)
        elif mode == "w":
            # Mock failed write
            mock_file = Mock()
            mock_file.__enter__ = Mock(return_value=mock_file)
            mock_file.__exit__ = Mock(return_value=None)
            mock_file.write = Mock(side_effect=write_exception)
            return mock_file

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.resolve", return_value=Path(mock_protector_script)),
        patch("contextprotector.mcp_config.pathlib.Path") as mock_path,
        patch("json.dump", side_effect=write_exception),
        patch("sys.exit") as mock_exit,
        patch("contextprotector.mcp_config.logger") as mock_logger,
    ):
        mock_path.return_value.parent.parent.parent = Path("/mock")
        mock_path.return_value.__truediv__ = lambda _, other: Path("/mock") / other

        wrap_mcp_config_file(temp_config_file)

        mock_exit.assert_called_once_with(1)
        mock_logger.error.assert_called()
        mock_logger.info.assert_called_with("Restored original config from backup")


def test_no_servers_modified(temp_config_file, mock_protector_script):
    """Test when no servers need to be modified."""
    # Create config with only already wrapped servers
    initial_config = {
        "mcpServers": {
            "wrapped_server": {
                "command": mock_protector_script,
                "args": ["--command", "python -m server"],
            }
        }
    }

    with open(temp_config_file, "w") as f:
        json.dump(initial_config, f, indent=2)

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.resolve", return_value=Path(mock_protector_script)),
        patch("contextprotector.mcp_config.pathlib.Path") as mock_path,
        patch("contextprotector.mcp_config.logger") as mock_logger,
    ):
        mock_path.return_value.parent.parent.parent = Path("/mock")
        mock_path.return_value.__truediv__ = lambda _, other: Path("/mock") / other

        wrap_mcp_config_file(temp_config_file)

        mock_logger.info.assert_any_call(
            "Server '%s' is already wrapped, skipping", "wrapped_server"
        )
        mock_logger.info.assert_called_with("No servers were modified")


def test_non_list_args_handling(temp_config_file, mock_protector_script):
    """Test handling of non-list args (string args)."""
    # Create config with string args instead of list
    initial_config = {
        "mcpServers": {"string_args_server": {"command": "python", "args": "-m server --verbose"}}
    }

    with open(temp_config_file, "w") as f:
        json.dump(initial_config, f, indent=2)

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.resolve", return_value=Path(mock_protector_script)),
        patch("contextprotector.mcp_config.pathlib.Path") as mock_path,
    ):
        mock_path.return_value.parent.parent.parent = Path("/mock")
        mock_path.return_value.__truediv__ = lambda _, other: Path("/mock") / other

        with patch("sys.exit") as mock_exit:
            wrap_mcp_config_file(temp_config_file)
            mock_exit.assert_not_called()

    # Read the modified config
    with open(temp_config_file) as f:
        modified_config = json.load(f)

    servers = modified_config["mcpServers"]

    # Verify string args were handled correctly
    assert servers["string_args_server"]["command"] == mock_protector_script
    assert servers["string_args_server"]["args"] == ["--command", "python -m server --verbose"]
