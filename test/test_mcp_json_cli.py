"""Tests for the MCP JSON CLI functionality."""

import pathlib
import tempfile
from unittest.mock import Mock, patch

from contextprotector.mcp_json_cli import (
    AllMCPJsonManager,
    DiscoveredMCPConfig,
    MCPJsonManager,
    WrapMCPJsonManager,
)
from contextprotector.mcp_json_config import MCPJsonConfig, MCPServerSpec


class TestMCPJsonManager:
    """Tests for MCPJsonManager class."""

    def test_init_with_existing_file(self):
        """Test initializing with an existing file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"mcpServers": {"test": {"command": "echo"}}}')
            f.flush()

            manager = MCPJsonManager(f.name)
            assert manager.file_path == pathlib.Path(f.name)
            assert manager.config is None  # Not loaded until run()

            # Clean up
            pathlib.Path(f.name).unlink()

    def test_init_with_nonexistent_file(self):
        """Test initializing with a non-existent file."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=True) as f:
            non_existent = f.name
        # File is now deleted, so it doesn't exist
        manager = MCPJsonManager(non_existent)
        assert manager.file_path == pathlib.Path(non_existent)

    def test_load_config_existing_file(self):
        """Test loading an existing configuration file."""
        config_data = {
            "mcpServers": {
                "test-server": {
                    "command": "python",
                    "args": ["-m", "test_module"],
                    "env": {"TEST_VAR": "value"},
                }
            },
            "globalShortcut": "Ctrl+M",
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            import json

            json.dump(config_data, f, indent=2)
            f.flush()

            manager = MCPJsonManager(f.name)
            manager._load_config()

            assert manager.config is not None
            assert len(manager.config.mcp_servers) == 1
            assert "test-server" in manager.config.mcp_servers
            assert manager.config.global_shortcut == "Ctrl+M"
            assert manager.original_json != ""

            # Clean up
            pathlib.Path(f.name).unlink()

    def test_load_config_nonexistent_file(self):
        """Test loading a non-existent configuration file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            non_existent_path = pathlib.Path(temp_dir) / "new_config.json"

            manager = MCPJsonManager(str(non_existent_path))
            manager._load_config()

            assert manager.config is not None
            assert len(manager.config.mcp_servers) == 0
            assert manager.config.filename == str(non_existent_path)
            assert manager.original_json == "{}"

    @patch("builtins.print")
    def test_display_config_empty(self, mock_print):
        """Test displaying an empty configuration."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = MCPJsonManager(f.name)
            manager.config = MCPJsonConfig()

            manager._display_config()

            # Check that print was called with appropriate messages
            mock_print.assert_any_call("No MCP servers configured.")

    @patch("builtins.print")
    def test_display_config_with_servers(self, mock_print):
        """Test displaying a configuration with servers."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = MCPJsonManager(f.name)
            manager.config = MCPJsonConfig()

            # Add a protected server
            protected_server = MCPServerSpec(
                command="mcp-context-protector",
                args=["--command-args", "python", "-m", "test_module"],
                env={"TEST_VAR": "value"},
            )
            manager.config.add_server("protected-server", protected_server)

            # Add an unprotected server
            unprotected_server = MCPServerSpec(
                command="python", args=["-m", "another_module"], env={}
            )
            manager.config.add_server("unprotected-server", unprotected_server)

            manager._display_config()

            # Verify that both servers are displayed with correct status
            printed_output = [call.args[0] for call in mock_print.call_args_list if call.args]
            output_text = "\n".join(str(line) for line in printed_output)

            assert "protected-server" in output_text
            assert "unprotected-server" in output_text
            assert "PROTECTED" in output_text
            assert "UNPROTECTED" in output_text

    def test_toggle_server_protection_add_protection(self):
        """Test adding protection to an unprotected server."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = MCPJsonManager(f.name)
            manager.config = MCPJsonConfig()

            # Add an unprotected server
            unprotected_server = MCPServerSpec(command="python", args=["-m", "test_module"])
            manager.config.add_server("test-server", unprotected_server)

            # Toggle protection (should add it)
            with patch("builtins.print"):
                manager._toggle_server_protection(1)

            # Verify protection was added
            updated_server = manager.config.get_server("test-server")
            assert updated_server is not None

            # The command should now include context protector
            from contextprotector.mcp_json_config import MCPContextProtectorDetector

            assert MCPContextProtectorDetector.is_context_protector_configured(updated_server)

    def test_toggle_server_protection_remove_protection(self):
        """Test removing protection from a protected server."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = MCPJsonManager(f.name)
            manager.config = MCPJsonConfig()

            # Add a protected server
            protected_server = MCPServerSpec(
                command="mcp-context-protector",
                args=["--command-args", "python", "-m", "test_module"],
            )
            manager.config.add_server("test-server", protected_server)

            # Toggle protection (should remove it)
            with patch("builtins.print"):
                manager._toggle_server_protection(1)

            # Verify protection was removed
            updated_server = manager.config.get_server("test-server")
            assert updated_server is not None
            assert updated_server.command == "python"
            assert updated_server.args == ["-m", "test_module"]

    @patch("builtins.input", side_effect=["y"])
    def test_save_with_confirmation_yes(self, mock_input):  # noqa: ARG002
        """Test saving with user confirmation (yes)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"mcpServers": {}}')
            f.flush()

            manager = MCPJsonManager(f.name)
            manager.config = MCPJsonConfig(filename=f.name)
            manager.config.add_server("test", MCPServerSpec(command="echo"))
            manager.original_json = '{"mcpServers": {}}'

            with patch("builtins.print"):
                result = manager._save_with_confirmation()

            assert result is True

            # Verify file was updated
            updated_content = pathlib.Path(f.name).read_text()
            assert "test" in updated_content

            # Clean up
            pathlib.Path(f.name).unlink()
            backup_path = pathlib.Path(f.name + ".backup")
            if backup_path.exists():
                backup_path.unlink()

    @patch("builtins.input", side_effect=["n"])
    def test_save_with_confirmation_no(self, mock_input):  # noqa: ARG002
        """Test saving with user confirmation (no)."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = MCPJsonManager(f.name)
            manager.config = MCPJsonConfig()
            manager.config.add_server("test", MCPServerSpec(command="echo"))
            manager.original_json = '{"mcpServers": {}}'

            with patch("builtins.print"):
                result = manager._save_with_confirmation()

            assert result is False

    def test_save_with_confirmation_no_changes(self):
        """Test saving when there are no changes."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = MCPJsonManager(f.name)
            manager.config = MCPJsonConfig()
            original_json = manager.config.to_json(indent=2)
            manager.original_json = original_json or "{}"

            with patch("builtins.print") as mock_print:
                result = manager._save_with_confirmation()

            assert result is True
            mock_print.assert_any_call("No changes to save.")

    @patch("contextprotector.mcp_json_cli.MCPJsonManager._run_repl")
    @patch("contextprotector.mcp_json_cli.MCPJsonManager._display_config")
    @patch("contextprotector.mcp_json_cli.MCPJsonManager._load_config")
    def test_run_success(self, mock_load, mock_display, mock_repl):
        """Test successful run of the manager."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = MCPJsonManager(f.name)
            manager.run()

            mock_load.assert_called_once()
            mock_display.assert_called_once()
            mock_repl.assert_called_once()

    @patch(
        "contextprotector.mcp_json_cli.MCPJsonManager._load_config",
        side_effect=Exception("Test error"),
    )
    @patch("sys.exit")
    def test_run_with_exception(self, mock_exit, mock_load):  # noqa: ARG002
        """Test run with an exception."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = MCPJsonManager(f.name)

            with patch("builtins.print"):
                manager.run()

            mock_exit.assert_called_once_with(1)

    def test_manage_mcp_json_file_function(self):
        """Test the main entry point function."""
        with patch("contextprotector.mcp_json_cli.MCPJsonManager") as mock_manager_class:
            mock_manager = Mock()
            mock_manager_class.return_value = mock_manager

            from contextprotector.mcp_json_cli import manage_mcp_json_file

            with tempfile.NamedTemporaryFile(suffix=".json") as f:
                manage_mcp_json_file(f.name)

                mock_manager_class.assert_called_once_with(f.name)
                mock_manager.run.assert_called_once()

    @patch("builtins.input", side_effect=["q"])
    @patch("builtins.print")
    def test_repl_quit_command(self, mock_print, mock_input):  # noqa: ARG002
        """Test REPL quit command."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = MCPJsonManager(f.name)
            manager.config = MCPJsonConfig()

            manager._run_repl()

            # Should exit without saving
            mock_print.assert_any_call("Exiting without saving...")

    @patch("builtins.input", side_effect=["r", "q"])
    @patch("contextprotector.mcp_json_cli.MCPJsonManager._display_config")
    @patch("contextprotector.mcp_json_cli.MCPJsonManager._load_config")
    def test_repl_refresh_command(self, mock_load, mock_display, mock_input):  # noqa: ARG002
        """Test REPL refresh command."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = MCPJsonManager(f.name)
            manager.config = MCPJsonConfig()

            with patch("builtins.print"):
                manager._run_repl()

            # Both _load_config and _display_config should be called once for refresh
            assert mock_load.call_count == 1
            assert mock_display.call_count == 1

    @patch("builtins.input", side_effect=["r", "q"])
    def test_repl_refresh_reloads_from_disk(self, mock_input):  # noqa: ARG002
        """Test that refresh command actually reloads the file from disk."""
        import json

        # Create initial config file
        config_data = {"mcpServers": {"initial-server": {"command": "echo", "args": ["initial"]}}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()

            manager = MCPJsonManager(f.name)
            manager._load_config()

            # Verify initial state
            assert len(manager.config.mcp_servers) == 1
            assert "initial-server" in manager.config.mcp_servers

            # Modify the file on disk (simulating external change)
            modified_config = {
                "mcpServers": {
                    "initial-server": {"command": "echo", "args": ["initial"]},
                    "new-server": {"command": "python", "args": ["-m", "test"]},
                }
            }

            with open(f.name, "w") as update_f:
                json.dump(modified_config, update_f, indent=2)

            # Run the REPL with refresh command
            with patch("builtins.print"):
                manager._run_repl()

            # Verify the config was reloaded from disk
            assert len(manager.config.mcp_servers) == 2
            assert "initial-server" in manager.config.mcp_servers
            assert "new-server" in manager.config.mcp_servers

            # Clean up
            pathlib.Path(f.name).unlink()

    @patch("builtins.input", side_effect=["invalid", "q"])
    @patch("builtins.print")
    def test_repl_invalid_command(self, mock_print, mock_input):  # noqa: ARG002
        """Test REPL with invalid command."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = MCPJsonManager(f.name)
            manager.config = MCPJsonConfig()

            manager._run_repl()

            mock_print.assert_any_call("Invalid choice.")

    @patch("builtins.input", side_effect=["q", "q", "q"])  # Need 'q' for each _run_repl call
    @patch("builtins.print")
    def test_repl_dynamic_command_display(self, mock_print, mock_input):  # noqa: ARG002
        """Test REPL displays correct server range in commands."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = MCPJsonManager(f.name)
            manager.config = MCPJsonConfig()

            # Test with no servers
            manager._run_repl()

            # Check that no server selection command is shown when there are no servers
            printed_output = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
            help_lines = [line for line in printed_output if "Select server" in line]
            assert len(help_lines) == 0  # No server selection line when no servers

            # Reset mock and test with one server
            mock_print.reset_mock()
            manager.config.add_server("test1", MCPServerSpec(command="echo"))

            manager._run_repl()

            printed_output = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
            help_lines = [line for line in printed_output if "Select server" in line]
            assert len(help_lines) > 0
            assert "[1]" in help_lines[0]  # Should show [1] for single server

            # Reset mock and test with multiple servers
            mock_print.reset_mock()
            manager.config.add_server("test2", MCPServerSpec(command="python"))

            manager._run_repl()

            printed_output = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
            help_lines = [line for line in printed_output if "Select server" in line]
            assert len(help_lines) > 0
            assert "[1-2]" in help_lines[0]  # Should show [1-2] for two servers


class TestAllMCPJsonManager:
    """Tests for AllMCPJsonManager class."""

    def test_init(self):
        """Test initializing AllMCPJsonManager."""
        manager = AllMCPJsonManager()
        assert manager.discovered_configs == []

    @patch("contextprotector.mcp_json_cli.MCPJsonLocator.get_all_mcp_config_paths")
    def test_discover_configs_no_files(self, mock_get_paths):
        """Test discovery when no config files exist."""
        mock_get_paths.return_value = {
            "claude-desktop": "/nonexistent/claude_desktop_config.json",
            "cursor": "/nonexistent/mcp.json",
        }

        manager = AllMCPJsonManager()
        with patch("builtins.print"):
            manager._discover_configs()

        assert len(manager.discovered_configs) == 0

    @patch("contextprotector.mcp_json_cli.MCPJsonLocator.get_all_mcp_config_paths")
    def test_discover_configs_with_files(self, mock_get_paths):
        """Test discovery when config files exist."""
        import json

        # Create temporary config files
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f1:
            config1 = {"mcpServers": {"server1": {"command": "echo"}}}
            json.dump(config1, f1)
            f1.flush()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f2:
            config2 = {
                "mcpServers": {
                    "server1": {"command": "echo"},
                    "server2": {"command": "python", "args": ["-m", "test"]},
                }
            }
            json.dump(config2, f2)
            f2.flush()

        mock_get_paths.return_value = {
            "claude-desktop": f1.name,
            "cursor": f2.name,
        }

        manager = AllMCPJsonManager()
        with patch("builtins.print"):
            manager._discover_configs()

        # Should have discovered both configs
        assert len(manager.discovered_configs) == 2

        # Check that configs are sorted by client name
        assert manager.discovered_configs[0].client_name == "claude-desktop"
        assert manager.discovered_configs[0].server_count == 1  # 1 server

        assert manager.discovered_configs[1].client_name == "cursor"
        assert manager.discovered_configs[1].server_count == 2  # 2 servers

        # Clean up
        pathlib.Path(f1.name).unlink()
        pathlib.Path(f2.name).unlink()

    @patch("contextprotector.mcp_json_cli.MCPJsonLocator.get_all_mcp_config_paths")
    def test_discover_configs_with_invalid_file(self, mock_get_paths):
        """Test discovery when a config file exists but is invalid."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("invalid json content")
            f.flush()

        mock_get_paths.return_value = {"claude-desktop": f.name}

        manager = AllMCPJsonManager()
        with patch("builtins.print"):
            manager._discover_configs()

        # Should still discover the file but with server_count = -1
        assert len(manager.discovered_configs) == 1
        assert manager.discovered_configs[0].client_name == "claude-desktop"
        assert manager.discovered_configs[0].server_count == -1  # Unable to parse

        # Clean up
        pathlib.Path(f.name).unlink()

    @patch("builtins.print")
    def test_display_configs_various_server_counts(self, mock_print):
        """Test displaying configs with various server counts."""
        manager = AllMCPJsonManager()
        manager.discovered_configs = [
            DiscoveredMCPConfig("claude-desktop", "/path/to/claude.json", 0, None),
            DiscoveredMCPConfig("cursor", "/path/to/cursor.json", 1, None),
            DiscoveredMCPConfig("windsurf", "/path/to/windsurf.json", 3, None),
            DiscoveredMCPConfig("invalid-config", "/path/to/invalid.json", -1, None),
        ]

        manager._display_configs()

        # Check that print was called with appropriate messages
        printed_output = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
        output_text = "\n".join(printed_output)

        assert "CLAUDE-DESKTOP" in output_text
        assert "(no servers configured)" in output_text
        assert "CURSOR" in output_text
        assert "(1 server)" in output_text
        assert "WINDSURF" in output_text
        assert "(3 servers)" in output_text
        assert "INVALID-CONFIG" in output_text
        assert "(unable to parse)" in output_text

    @patch("builtins.input", side_effect=["q"])
    @patch("builtins.print")
    def test_run_selection_loop_quit(self, mock_print, mock_input):  # noqa: ARG002
        """Test selection loop with quit command."""
        manager = AllMCPJsonManager()
        manager.discovered_configs = [
            DiscoveredMCPConfig("test-client", "/path/to/test.json", 1, None)
        ]

        manager._run_selection_loop()

        # Should have printed exit message
        mock_print.assert_any_call("Exiting...")

    @patch("builtins.input", side_effect=["r", "q"])
    @patch("contextprotector.mcp_json_cli.AllMCPJsonManager._discover_configs")
    @patch("contextprotector.mcp_json_cli.AllMCPJsonManager._display_configs")
    def test_run_selection_loop_refresh(self, mock_display, mock_discover, mock_input):  # noqa: ARG002
        """Test selection loop with refresh command."""
        manager = AllMCPJsonManager()
        manager.discovered_configs = [
            DiscoveredMCPConfig("test-client", "/path/to/test.json", 1, None)
        ]

        # Mock discover_configs to repopulate the configs after clearing
        def mock_discover_side_effect():
            manager.discovered_configs = [
                DiscoveredMCPConfig("test-client", "/path/to/test.json", 1, None)
            ]

        mock_discover.side_effect = mock_discover_side_effect

        with patch("builtins.print"):
            manager._run_selection_loop()

        # Should have called discover and display once for refresh
        assert mock_discover.call_count == 1
        assert mock_display.call_count == 1

    @patch("builtins.input", side_effect=["r", "q"])
    @patch("contextprotector.mcp_json_cli.AllMCPJsonManager._discover_configs")
    @patch("builtins.print")
    def test_run_selection_loop_refresh_no_configs(self, mock_print, mock_discover, mock_input):  # noqa: ARG002
        """Test selection loop with refresh command that finds no configs."""
        manager = AllMCPJsonManager()
        manager.discovered_configs = [
            DiscoveredMCPConfig("test-client", "/path/to/test.json", 1, None)
        ]

        # Mock discover_configs to clear configs (simulating no configs found)
        def mock_discover_side_effect():
            manager.discovered_configs = []

        mock_discover.side_effect = mock_discover_side_effect

        manager._run_selection_loop()

        # Should have called discover once and printed no configs message
        assert mock_discover.call_count == 1
        mock_print.assert_any_call("No MCP configuration files found in known locations.")

    @patch("builtins.input", side_effect=["1", "q"])
    @patch("contextprotector.mcp_json_cli.MCPJsonManager")
    def test_run_selection_loop_valid_selection(self, mock_manager_class, mock_input):  # noqa: ARG002
        """Test selection loop with valid config selection."""
        mock_manager = Mock()
        mock_manager_class.return_value = mock_manager

        manager = AllMCPJsonManager()
        manager.discovered_configs = [
            DiscoveredMCPConfig("test-client", "/path/to/test.json", 1, None)
        ]

        # Mock the _discover_configs to prevent it from clearing discovered_configs
        with patch.object(manager, "_discover_configs"), patch("builtins.print"):
            manager._run_selection_loop()

        # Should have created and run the individual manager
        mock_manager_class.assert_called_once_with("/path/to/test.json", None)
        mock_manager.run.assert_called_once()

    @patch("builtins.input", side_effect=["1", "n", "q"])
    def test_run_selection_loop_unparseable_config_declined(self, mock_input):  # noqa: ARG002
        """Test selection loop with unparseable config that user declines to manage."""
        manager = AllMCPJsonManager()
        manager.discovered_configs = [
            DiscoveredMCPConfig("test-client", "/path/to/test.json", -1, None)
        ]

        with patch("builtins.print"):
            manager._run_selection_loop()

        # Should not have tried to create a manager since user declined

    @patch("builtins.input", side_effect=["invalid", "q"])
    @patch("builtins.print")
    def test_run_selection_loop_invalid_input(self, mock_print, mock_input):  # noqa: ARG002
        """Test selection loop with invalid input."""
        manager = AllMCPJsonManager()
        manager.discovered_configs = [
            DiscoveredMCPConfig("test-client", "/path/to/test.json", 1, None)
        ]

        manager._run_selection_loop()

        # Should have printed error message
        printed_output = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
        error_messages = [msg for msg in printed_output if "Invalid choice" in msg]
        assert len(error_messages) > 0

    @patch("contextprotector.mcp_json_cli.AllMCPJsonManager._discover_configs")
    @patch("contextprotector.mcp_json_cli.AllMCPJsonManager._display_configs")
    @patch("contextprotector.mcp_json_cli.AllMCPJsonManager._run_selection_loop")
    def test_run_with_configs(self, mock_selection, mock_display, mock_discover):
        """Test full run method when configs are found."""
        manager = AllMCPJsonManager()

        # Mock that we discovered some configs
        def mock_discover_side_effect():
            manager.discovered_configs = [
                DiscoveredMCPConfig("test-client", "/path/to/test.json", 1, None)
            ]

        mock_discover.side_effect = mock_discover_side_effect

        manager.run()

        mock_discover.assert_called_once()
        mock_display.assert_called_once()
        mock_selection.assert_called_once()

    @patch("contextprotector.mcp_json_cli.AllMCPJsonManager._discover_configs")
    @patch("builtins.print")
    def test_run_no_configs_found(self, mock_print, mock_discover):
        """Test run method when no configs are found."""
        manager = AllMCPJsonManager()

        # Mock that no configs were discovered
        def mock_discover_side_effect():
            manager.discovered_configs = []

        mock_discover.side_effect = mock_discover_side_effect

        manager.run()

        mock_discover.assert_called_once()
        mock_print.assert_any_call("No MCP configuration files found in known locations.")

    def test_manage_all_mcp_json_files_function(self):
        """Test the main entry point function."""
        with patch("contextprotector.mcp_json_cli.AllMCPJsonManager") as mock_manager_class:
            mock_manager = Mock()
            mock_manager_class.return_value = mock_manager

            from contextprotector.mcp_json_cli import manage_all_mcp_json_files

            manage_all_mcp_json_files()

            mock_manager_class.assert_called_once()
            mock_manager.run.assert_called_once()


class TestWrapMCPJsonManager:
    """Tests for WrapMCPJsonManager class."""

    def test_init(self):
        """Test initializing WrapMCPJsonManager."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = WrapMCPJsonManager(f.name)
            assert manager.file_path == pathlib.Path(f.name)
            assert manager.config is None
            assert manager.original_json == ""
            assert manager.servers_to_wrap == []
            assert manager.servers_already_wrapped == []

    def test_load_config(self):
        """Test loading configuration."""
        import json

        config_data = {
            "mcpServers": {"test-server": {"command": "python", "args": ["-m", "test_module"]}}
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()

            manager = WrapMCPJsonManager(f.name)
            with patch("builtins.print"):
                manager._load_config()

            assert manager.config is not None
            servers = manager.config.get_servers()
            assert len(servers) == 1
            assert "test-server" in servers
            assert manager.original_json != ""

            # Clean up
            pathlib.Path(f.name).unlink()

    def test_analyze_servers_none_wrapped(self):
        """Test analyzing servers when none are wrapped."""
        import json

        config_data = {
            "mcpServers": {
                "server1": {"command": "python", "args": ["-m", "test1"]},
                "server2": {"command": "echo", "args": ["hello"]},
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()

            manager = WrapMCPJsonManager(f.name)
            with patch("builtins.print"):
                manager._load_config()
            manager._analyze_servers()

            assert len(manager.servers_to_wrap) == 2
            assert "server1" in manager.servers_to_wrap
            assert "server2" in manager.servers_to_wrap
            assert len(manager.servers_already_wrapped) == 0

            # Clean up
            pathlib.Path(f.name).unlink()

    def test_analyze_servers_some_wrapped(self):
        """Test analyzing servers when some are already wrapped."""
        import json

        config_data = {
            "mcpServers": {
                "unwrapped": {"command": "python", "args": ["-m", "test"]},
                "wrapped": {
                    "command": "mcp-context-protector",
                    "args": ["--command-args", "python", "-m", "test"],
                },
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()

            manager = WrapMCPJsonManager(f.name)
            with patch("builtins.print"):
                manager._load_config()
            manager._analyze_servers()

            assert len(manager.servers_to_wrap) == 1
            assert "unwrapped" in manager.servers_to_wrap
            assert len(manager.servers_already_wrapped) == 1
            assert "wrapped" in manager.servers_already_wrapped

            # Clean up
            pathlib.Path(f.name).unlink()

    def test_analyze_servers_comprehensive_wrapped_patterns(self):
        """Test analyzing servers with comprehensive wrapped patterns including uv and arbitrary
        paths."""
        import json

        config_data = {
            "mcpServers": {
                "unwrapped-python": {"command": "python", "args": ["-m", "myserver"]},
                "unwrapped-node": {"command": "node", "args": ["server.js"]},
                "wrapped-direct": {
                    "command": "mcp-context-protector",
                    "args": ["--command-args", "python", "-m", "server1"],
                },
                "wrapped-script": {
                    "command": "mcp-context-protector.sh",
                    "args": ["--command-args", "node", "app.js"],
                },
                "wrapped-absolute-path": {
                    "command": "/usr/local/bin/mcp-context-protector",
                    "args": ["--command-args", "rust-analyzer", "--stdio"],
                },
                "wrapped-uv-run": {
                    "command": "uv",
                    "args": [
                        "run",
                        "mcp-context-protector",
                        "--command-args",
                        "go",
                        "run",
                        "main.go",
                    ],
                },
                "wrapped-python-module": {
                    "command": "python3",
                    "args": [
                        "-m",
                        "contextprotector",
                        "--command-args",
                        "java",
                        "-jar",
                        "server.jar",
                    ],
                },
                "wrapped-venv-python": {
                    "command": "/path/to/venv/bin/python",
                    "args": [
                        "-m",
                        "contextprotector",
                        "--command-args",
                        "docker",
                        "run",
                        "myimage",
                    ],
                },
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()

            manager = WrapMCPJsonManager(f.name)
            with patch("builtins.print"):
                manager._load_config()
            manager._analyze_servers()

            # Should identify exactly 2 servers to wrap
            assert len(manager.servers_to_wrap) == 2
            assert "unwrapped-python" in manager.servers_to_wrap
            assert "unwrapped-node" in manager.servers_to_wrap

            # Should identify 6 already wrapped servers
            assert len(manager.servers_already_wrapped) == 6
            assert "wrapped-direct" in manager.servers_already_wrapped
            assert "wrapped-script" in manager.servers_already_wrapped
            assert "wrapped-absolute-path" in manager.servers_already_wrapped
            assert "wrapped-uv-run" in manager.servers_already_wrapped
            assert "wrapped-python-module" in manager.servers_already_wrapped
            assert "wrapped-venv-python" in manager.servers_already_wrapped

            # Clean up
            pathlib.Path(f.name).unlink()

    @patch("builtins.print")
    def test_display_analysis(self, mock_print):
        """Test displaying analysis results."""
        import json

        config_data = {
            "mcpServers": {
                "unwrapped": {"command": "python", "args": ["-m", "test"]},
                "wrapped": {"command": "mcp-context-protector", "args": ["--command-args", "echo"]},
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()

            manager = WrapMCPJsonManager(f.name)
            manager._load_config()
            manager._analyze_servers()
            manager._display_analysis()

            # Clean up
            pathlib.Path(f.name).unlink()

            # Check that print was called with appropriate messages
            printed_output = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
            output_text = "\n".join(printed_output)

            assert "MCP Server Wrapping Analysis" in output_text
            assert "Already Protected" in output_text
            assert "wrapped" in output_text
            assert "Servers to Wrap" in output_text
            assert "unwrapped" in output_text

    @patch("builtins.input", return_value="y")
    def test_confirm_wrapping_yes(self, mock_input):  # noqa: ARG002
        """Test confirming wrapping with yes."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = WrapMCPJsonManager(f.name)
            manager.servers_to_wrap = ["test-server"]

            with patch("builtins.print"):
                result = manager._confirm_wrapping()

            assert result is True

    @patch("builtins.input", return_value="n")
    def test_confirm_wrapping_no(self, mock_input):  # noqa: ARG002
        """Test confirming wrapping with no."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = WrapMCPJsonManager(f.name)
            manager.servers_to_wrap = ["test-server"]

            with patch("builtins.print"):
                result = manager._confirm_wrapping()

            assert result is False

    @patch("builtins.print")
    def test_wrap_servers(self, mock_print):
        """Test wrapping servers."""
        import json

        config_data = {
            "mcpServers": {"test-server": {"command": "python", "args": ["-m", "test_module"]}}
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()

            manager = WrapMCPJsonManager(f.name)
            manager._load_config()
            manager._analyze_servers()
            manager._wrap_servers()

            # Verify the server was wrapped
            from contextprotector.mcp_json_config import MCPContextProtectorDetector

            servers = manager.config.get_servers()
            wrapped_spec = servers["test-server"]
            assert MCPContextProtectorDetector.is_context_protector_configured(wrapped_spec)

            # Check that success message was printed
            printed_output = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
            success_messages = [msg for msg in printed_output if "Successfully wrapped" in msg]
            assert len(success_messages) > 0

            # Clean up
            pathlib.Path(f.name).unlink()

    @patch("builtins.input", side_effect=["y"])
    def test_save_with_confirmation_yes(self, mock_input):  # noqa: ARG002
        """Test saving with confirmation (yes)."""
        import json

        config_data = {"mcpServers": {"test": {"command": "echo"}}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            f.flush()

            manager = WrapMCPJsonManager(f.name)
            manager.config = MCPJsonConfig(filename=f.name)
            # Modify the config to create a difference
            manager.config.add_server("new-server", MCPServerSpec(command="python"))
            manager.original_json = json.dumps(config_data, indent=2)

            with patch("builtins.print"):
                result = manager._save_with_confirmation()

            assert result is True

            # Verify backup was created
            backup_path = pathlib.Path(f.name + ".backup")
            assert backup_path.exists()

            # Clean up
            pathlib.Path(f.name).unlink()
            if backup_path.exists():
                backup_path.unlink()

    @patch("builtins.input", side_effect=["n"])
    def test_save_with_confirmation_no(self, mock_input):  # noqa: ARG002
        """Test saving with confirmation (no)."""
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            manager = WrapMCPJsonManager(f.name)
            manager.config = MCPJsonConfig()
            manager.config.add_server("test", MCPServerSpec(command="echo"))
            manager.original_json = '{"mcpServers": {}}'

            with patch("builtins.print"):
                result = manager._save_with_confirmation()

            assert result is False

    @patch("sys.exit")
    def test_run_nonexistent_file(self, mock_exit):
        """Test running with a non-existent file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            nonexistent_path = pathlib.Path(temp_dir) / "nonexistent.json"

            manager = WrapMCPJsonManager(str(nonexistent_path))

            with patch("builtins.print"):
                manager.run()

            # Should have been called with exit code 1
            mock_exit.assert_called_with(1)
            # Allow for the possibility it's called more than once due to nested exceptions
            assert mock_exit.call_count >= 1

    def test_run_no_servers_to_wrap_already_wrapped(self):
        """Test running when all servers are already wrapped."""
        import json

        config_data = {
            "mcpServers": {
                "wrapped": {
                    "command": "mcp-context-protector",
                    "args": ["--command-args", "python", "-m", "test"],
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()

            manager = WrapMCPJsonManager(f.name)

            with patch("builtins.print") as mock_print:
                manager.run()

            # Should print message about all servers being wrapped
            printed_output = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
            success_messages = [msg for msg in printed_output if "already wrapped" in msg]
            assert len(success_messages) > 0

            # Clean up
            pathlib.Path(f.name).unlink()

    def test_run_no_servers_in_config(self):
        """Test running with a config that has no servers."""
        import json

        config_data = {"mcpServers": {}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()

            manager = WrapMCPJsonManager(f.name)

            with patch("builtins.print") as mock_print:
                manager.run()

            # Should print message about no servers found
            printed_output = [str(call.args[0]) for call in mock_print.call_args_list if call.args]
            no_servers_messages = [msg for msg in printed_output if "No MCP servers found" in msg]
            assert len(no_servers_messages) > 0

            # Clean up
            pathlib.Path(f.name).unlink()

    def test_wrap_mcp_json_file_function(self):
        """Test the main entry point function."""
        with patch("contextprotector.mcp_json_cli.WrapMCPJsonManager") as mock_manager_class:
            mock_manager = Mock()
            mock_manager_class.return_value = mock_manager

            from contextprotector.mcp_json_cli import wrap_mcp_json_file

            with tempfile.NamedTemporaryFile(suffix=".json") as f:
                wrap_mcp_json_file(f.name)

                mock_manager_class.assert_called_once_with(f.name, None)
                mock_manager.run.assert_called_once()


class TestCLIIntegration:
    """Tests for CLI integration."""

    @patch("contextprotector.mcp_json_cli.manage_mcp_json_file")
    def test_main_with_manage_mcp_json_file(self, mock_manage):  # noqa: ARG002
        """Test main function with --manage-mcp-json-file option."""
        from contextprotector.__main__ import _parse_args

        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            # Mock sys.argv to test argument parsing
            test_args = ["mcp-context-protector", "--manage-mcp-json-file", f.name]

            with patch("sys.argv", test_args):
                args = _parse_args()

            assert args.manage_mcp_json_file == f.name
            assert not args.review_server
            assert not args.review_quarantine
            assert not args.list_guardrail_providers

    @patch("contextprotector.mcp_json_cli.manage_all_mcp_json_files")
    def test_main_with_manage_all_mcp_json(self, mock_manage_all):  # noqa: ARG002
        """Test main function with --manage-all-mcp-json option."""
        from contextprotector.__main__ import _parse_args

        # Mock sys.argv to test argument parsing
        test_args = ["mcp-context-protector", "--manage-all-mcp-json"]

        with patch("sys.argv", test_args):
            args = _parse_args()

        assert args.manage_all_mcp_json is True
        assert not args.manage_mcp_json_file
        assert not args.review_server
        assert not args.review_quarantine
        assert not args.list_guardrail_providers

    @patch("contextprotector.mcp_json_cli.wrap_mcp_json_file")
    def test_main_with_wrap_mcp_json(self, mock_wrap):  # noqa: ARG002
        """Test main function with --wrap-mcp-json option."""
        from contextprotector.__main__ import _parse_args

        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            # Mock sys.argv to test argument parsing
            test_args = ["mcp-context-protector", "--wrap-mcp-json", f.name]

            with patch("sys.argv", test_args):
                args = _parse_args()

            assert args.wrap_mcp_json == f.name
            assert not args.manage_mcp_json_file
            assert not args.manage_all_mcp_json
            assert not args.review_server
            assert not args.review_quarantine
            assert not args.list_guardrail_providers
