"""Tests for the MCPJsonConfig and MCPServerSpec classes."""

import json
import tempfile
from pathlib import Path

import pytest

from contextprotector.mcp_json_config import (
    MCPContextProtectorDetector,
    MCPJsonConfig,
    MCPJsonLocator,
    MCPServerSpec,
)


class TestMCPServerSpec:
    """Test cases for MCPServerSpec class."""

    def test_basic_creation(self):
        """Test basic creation of MCPServerSpec."""
        server = MCPServerSpec(command="node")
        assert server.command == "node"
        assert server.args == []
        assert server.env == {}

    def test_creation_with_args_and_env(self):
        """Test creation with args and environment variables."""
        args = ["server.js", "--port", "3000"]
        env = {"NODE_ENV": "production", "API_KEY": "secret"}
        server = MCPServerSpec(command="node", args=args, env=env)

        assert server.command == "node"
        assert server.args == args
        assert server.env == env

    def test_to_dict(self):
        """Test conversion to dictionary."""
        server = MCPServerSpec(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-postgres"],
            env={"DATABASE_URL": "postgres://localhost/test"},
        )

        expected = {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-postgres"],
            "env": {"DATABASE_URL": "postgres://localhost/test"},
        }

        assert server.to_dict() == expected

    def test_to_dict_minimal(self):
        """Test to_dict with minimal configuration."""
        server = MCPServerSpec(command="python")

        # Should only include command when args and env are empty
        expected = {"command": "python"}
        assert server.to_dict() == expected

    def test_from_dict_valid(self):
        """Test creation from valid dictionary."""
        data = {"command": "node", "args": ["server.js"], "env": {"PORT": "3000"}}

        server = MCPServerSpec.from_dict(data)
        assert server.command == "node"
        assert server.args == ["server.js"]
        assert server.env == {"PORT": "3000"}

    def test_from_dict_minimal(self):
        """Test creation from minimal dictionary."""
        data = {"command": "python"}

        server = MCPServerSpec.from_dict(data)
        assert server.command == "python"
        assert server.args == []
        assert server.env == {}

    def test_from_dict_invalid_data_type(self):
        """Test error handling for invalid data type."""
        with pytest.raises(ValueError, match="Server specification must be a dictionary"):
            MCPServerSpec.from_dict("not a dict")

    def test_from_dict_missing_command(self):
        """Test error handling for missing command."""
        with pytest.raises(
            ValueError, match="Server specification must have a valid 'command' field"
        ):
            MCPServerSpec.from_dict({})

    def test_from_dict_empty_command(self):
        """Test error handling for empty command."""
        with pytest.raises(
            ValueError, match="Server specification must have a valid 'command' field"
        ):
            MCPServerSpec.from_dict({"command": ""})

    def test_from_dict_invalid_args(self):
        """Test error handling for invalid args."""
        with pytest.raises(ValueError, match="Server 'args' must be a list of strings"):
            MCPServerSpec.from_dict({"command": "node", "args": "not a list"})

        with pytest.raises(ValueError, match="Server 'args' must be a list of strings"):
            MCPServerSpec.from_dict({"command": "node", "args": [123, "valid"]})

    def test_from_dict_invalid_env(self):
        """Test error handling for invalid env."""
        with pytest.raises(
            ValueError, match="Server 'env' must be a dictionary of string key-value pairs"
        ):
            MCPServerSpec.from_dict({"command": "node", "env": "not a dict"})

        with pytest.raises(
            ValueError, match="Server 'env' must be a dictionary of string key-value pairs"
        ):
            MCPServerSpec.from_dict({"command": "node", "env": {"PORT": 3000}})


class TestMCPJsonConfig:
    """Test cases for MCPJsonConfig class."""

    def test_empty_config(self):
        """Test creation of empty configuration."""
        config = MCPJsonConfig()
        assert config.mcp_servers == {}
        assert config.global_shortcut is None
        assert config.other_config == {}

    def test_add_server_dict(self):
        """Test adding a server from dictionary."""
        config = MCPJsonConfig()
        server_data = {"command": "node", "args": ["server.js"], "env": {"PORT": "3000"}}

        config.add_server("test-server", server_data)

        assert "test-server" in config.mcp_servers
        server = config.mcp_servers["test-server"]
        assert server.command == "node"
        assert server.args == ["server.js"]
        assert server.env == {"PORT": "3000"}

    def test_add_server_object(self):
        """Test adding a server object directly."""
        config = MCPJsonConfig()
        server = MCPServerSpec(command="python", args=["server.py"])

        config.add_server("python-server", server)

        assert "python-server" in config.mcp_servers
        assert config.mcp_servers["python-server"] is server

    def test_add_server_invalid_name(self):
        """Test error handling for invalid server name."""
        config = MCPJsonConfig()
        server = MCPServerSpec(command="node")

        with pytest.raises(ValueError, match="Server name must be a non-empty string"):
            config.add_server("", server)

        with pytest.raises(ValueError, match="Server name must be a non-empty string"):
            config.add_server(123, server)

    def test_add_server_invalid_type(self):
        """Test error handling for invalid server type."""
        config = MCPJsonConfig()

        with pytest.raises(
            ValueError, match="Server must be either an MCPServerSpec object or a dictionary"
        ):
            config.add_server("test", "invalid")

    def test_remove_server(self):
        """Test removing a server."""
        config = MCPJsonConfig()
        server = MCPServerSpec(command="node")
        config.add_server("test-server", server)

        assert "test-server" in config.mcp_servers
        config.remove_server("test-server")
        assert "test-server" not in config.mcp_servers

    def test_get_server(self):
        """Test getting a server by name."""
        config = MCPJsonConfig()
        server = MCPServerSpec(command="node")
        config.add_server("test-server", server)

        retrieved = config.get_server("test-server")
        assert retrieved is server

        assert config.get_server("nonexistent") is None

    def test_list_servers(self):
        """Test listing all servers."""
        config = MCPJsonConfig()
        config.add_server("server1", MCPServerSpec(command="node"))
        config.add_server("server2", MCPServerSpec(command="python"))

        servers = config.list_servers()
        assert set(servers) == {"server1", "server2"}

    def test_to_dict(self):
        """Test conversion to dictionary."""
        config = MCPJsonConfig()
        config.global_shortcut = "Alt+C"
        config.other_config = {"theme": "dark"}

        config.add_server(
            "postgres",
            MCPServerSpec(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-postgres"],
                env={"DATABASE_URL": "postgres://localhost/test"},
            ),
        )

        result = config.to_dict()

        expected = {
            "mcpServers": {
                "postgres": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-postgres"],
                    "env": {"DATABASE_URL": "postgres://localhost/test"},
                }
            },
            "globalShortcut": "Alt+C",
            "theme": "dark",
        }

        assert result == expected

    def test_from_dict_complete(self):
        """Test creation from complete dictionary."""
        data = {
            "mcpServers": {
                "github": {
                    "command": "node",
                    "args": ["github-server.js"],
                    "env": {"GITHUB_TOKEN": "secret"},
                },
                "sqlite": {"command": "npx", "args": ["mcp-server-sqlite"]},
            },
            "globalShortcut": "Alt+C",
            "theme": "dark",
            "version": "1.0.0",
        }

        config = MCPJsonConfig.from_dict(data)

        assert config.global_shortcut == "Alt+C"
        assert config.other_config == {"theme": "dark", "version": "1.0.0"}

        assert "github" in config.mcp_servers
        github_server = config.mcp_servers["github"]
        assert github_server.command == "node"
        assert github_server.args == ["github-server.js"]
        assert github_server.env == {"GITHUB_TOKEN": "secret"}

        assert "sqlite" in config.mcp_servers
        sqlite_server = config.mcp_servers["sqlite"]
        assert sqlite_server.command == "npx"
        assert sqlite_server.args == ["mcp-server-sqlite"]
        assert sqlite_server.env == {}

    def test_from_dict_none(self):
        """Test creation from None."""
        config = MCPJsonConfig.from_dict(None)
        assert config.mcp_servers == {}
        assert config.global_shortcut is None
        assert config.other_config == {}

    def test_from_dict_invalid_type(self):
        """Test error handling for invalid data type."""
        with pytest.raises(ValueError, match="Configuration data must be a dictionary"):
            MCPJsonConfig.from_dict("not a dict")

    def test_from_dict_invalid_mcp_servers(self):
        """Test error handling for invalid mcpServers."""
        with pytest.raises(ValueError, match="'mcpServers' must be a dictionary"):
            MCPJsonConfig.from_dict({"mcpServers": "not a dict"})

    def test_from_dict_invalid_server_config(self):
        """Test error handling for invalid server configuration."""
        data = {
            "mcpServers": {
                "bad-server": {"command": ""}  # Empty command
            }
        }

        with pytest.raises(ValueError, match="Invalid server configuration for 'bad-server'"):
            MCPJsonConfig.from_dict(data)

    def test_from_dict_invalid_global_shortcut(self):
        """Test error handling for invalid global shortcut."""
        with pytest.raises(ValueError, match="'globalShortcut' must be a string"):
            MCPJsonConfig.from_dict({"globalShortcut": 123})

    def test_json_roundtrip(self):
        """Test JSON serialization and deserialization roundtrip."""
        original_config = MCPJsonConfig()
        original_config.global_shortcut = "Alt+C"
        original_config.other_config = {"theme": "dark"}

        original_config.add_server(
            "postgres",
            MCPServerSpec(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-postgres"],
                env={"DATABASE_URL": "postgres://localhost/test"},
            ),
        )

        # Serialize to JSON
        json_str = original_config.to_json()
        assert json_str is not None

        # Deserialize from JSON
        restored_config = MCPJsonConfig.from_json(json_str=json_str)

        # Compare
        assert restored_config.global_shortcut == original_config.global_shortcut
        assert restored_config.other_config == original_config.other_config
        assert len(restored_config.mcp_servers) == len(original_config.mcp_servers)

        postgres_server = restored_config.mcp_servers["postgres"]
        original_postgres = original_config.mcp_servers["postgres"]
        assert postgres_server.command == original_postgres.command
        assert postgres_server.args == original_postgres.args
        assert postgres_server.env == original_postgres.env

    def test_json_file_operations(self):
        """Test JSON file read/write operations."""
        config = MCPJsonConfig()
        config.add_server("test", MCPServerSpec(command="python"))

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            temp_path = f.name

        try:
            # Write to file
            config.to_json(path=temp_path)

            # Verify file exists and has content
            assert Path(temp_path).exists()

            # Read back from file
            restored_config = MCPJsonConfig.from_json(path=temp_path)

            assert "test" in restored_config.mcp_servers
            assert restored_config.mcp_servers["test"].command == "python"
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_from_json_validation_errors(self):
        """Test validation errors in from_json."""
        with pytest.raises(
            ValueError, match="Exactly one of json_str, path, or fp must be provided"
        ):
            MCPJsonConfig.from_json()

        with pytest.raises(
            ValueError, match="Exactly one of json_str, path, or fp must be provided"
        ):
            MCPJsonConfig.from_json(json_str="{}", path="test.json")

    def test_get_default_claude_desktop_config_path(self):
        """Test getting default Claude Desktop config path."""
        path = MCPJsonConfig.get_default_claude_desktop_config_path()
        assert isinstance(path, str)
        assert path.endswith("claude_desktop_config.json")


class TestMCPJsonLocator:
    """Test cases for MCPJsonLocator class."""

    def test_get_claude_desktop_config_path(self):
        """Test getting Claude Desktop config path."""
        path = MCPJsonLocator.get_claude_desktop_config_path()
        assert isinstance(path, str)
        assert path.endswith("claude_desktop_config.json")

    def test_get_claude_code_config_path(self):
        """Test getting Claude Code config path."""
        path = MCPJsonLocator.get_claude_code_config_path()
        assert isinstance(path, str)
        assert path.endswith("claude_code_config.json")

    def test_get_cursor_config_path(self):
        """Test getting Cursor config path."""
        path = MCPJsonLocator.get_cursor_config_path()
        assert isinstance(path, str)
        assert path.endswith("mcp.json")
        assert ".cursor" in path

    def test_get_cursor_cline_config_path(self):
        """Test getting Cursor Cline extension config path."""
        path = MCPJsonLocator.get_cursor_cline_config_path()
        assert isinstance(path, str)
        assert path.endswith("cline_mcp_settings.json")

    def test_get_windsurf_config_path(self):
        """Test getting Windsurf config path."""
        path = MCPJsonLocator.get_windsurf_config_path()
        assert isinstance(path, str)
        assert path.endswith("mcp_config.json")
        assert ".codeium" in path and "windsurf" in path

    def test_get_continue_config_path(self):
        """Test getting Continue.dev config path."""
        path = MCPJsonLocator.get_continue_config_path()
        assert isinstance(path, str)
        assert path.endswith("config.json")
        assert ".continue" in path

    def test_get_continue_yaml_config_path(self):
        """Test getting Continue.dev YAML config path."""
        path = MCPJsonLocator.get_continue_yaml_config_path()
        assert isinstance(path, str)
        assert path.endswith("config.yaml")
        assert ".continue" in path

    def test_get_vscode_user_mcp_config_path(self):
        """Test getting VS Code user MCP config path."""
        path = MCPJsonLocator.get_vscode_user_mcp_config_path()
        assert isinstance(path, str)
        assert path.endswith("mcp.json")
        # Should contain either "Code" (standard) or "Code/User"
        assert "Code" in path

    def test_get_all_mcp_config_paths(self):
        """Test getting all MCP config paths."""
        all_paths = MCPJsonLocator.get_all_mcp_config_paths()

        assert isinstance(all_paths, dict)

        # Check that all expected clients are included
        expected_clients = {
            "claude-desktop",
            "claude-code",
            "cursor",
            "cursor-cline",
            "windsurf",
            "continue",
            "continue-yaml",
            "vscode",
            "claude-settings",
        }
        assert set(all_paths.keys()) == expected_clients

        # Check that all paths are strings
        for client, path in all_paths.items():
            assert isinstance(path, str), f"Path for {client} should be a string"
            assert len(path) > 0, f"Path for {client} should not be empty"

        # Check specific path characteristics
        assert all_paths["claude-desktop"].endswith("claude_desktop_config.json")
        assert all_paths["claude-code"].endswith("claude_code_config.json")
        assert all_paths["cursor"].endswith("mcp.json")
        assert all_paths["cursor-cline"].endswith("cline_mcp_settings.json")
        assert all_paths["windsurf"].endswith("mcp_config.json")
        assert all_paths["continue"].endswith("config.json")
        assert all_paths["continue-yaml"].endswith("config.yaml")
        assert all_paths["vscode"].endswith("mcp.json")

        # Check that paths are unique (no duplicates)
        path_values = list(all_paths.values())
        assert len(path_values) == len(set(path_values)), "All paths should be unique"


class TestMCPJsonConfigFilename:
    """Test cases for MCPJsonConfig filename functionality."""

    def test_filename_field_default(self):
        """Test that filename field defaults to None."""
        config = MCPJsonConfig()
        assert config.filename is None

    def test_filename_field_initialization(self):
        """Test explicit filename initialization."""
        config = MCPJsonConfig(filename="/path/to/config.json")
        assert config.filename == "/path/to/config.json"

    def test_from_dict_with_filename(self):
        """Test from_dict with filename parameter."""
        data = {"mcpServers": {"test": {"command": "node"}}}
        config = MCPJsonConfig.from_dict(data, filename="/test/config.json")

        assert config.filename == "/test/config.json"
        assert "test" in config.mcp_servers

    def test_from_json_path_sets_filename(self):
        """Test that loading from file path sets filename."""
        config_data = {"mcpServers": {"test": {"command": "python", "args": ["server.py"]}}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            config = MCPJsonConfig.from_json(path=temp_path)
            assert config.filename == temp_path
            assert "test" in config.mcp_servers
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_from_json_file_object_sets_filename(self):
        """Test that loading from named file object sets filename."""
        config_data = {"mcpServers": {"test": {"command": "go", "args": ["run", "main.go"]}}}

        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            f.seek(0)

            config = MCPJsonConfig.from_json(fp=f)
            assert config.filename == f.name
            temp_path = f.name

        try:
            assert "test" in config.mcp_servers
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_from_json_string_no_filename(self):
        """Test that loading from JSON string doesn't set filename."""
        json_str = '{"mcpServers": {"test": {"command": "rust-analyzer"}}}'
        config = MCPJsonConfig.from_json(json_str=json_str)

        assert config.filename is None
        assert "test" in config.mcp_servers

    def test_to_json_uses_filename_as_default(self):
        """Test that to_json uses filename as default path."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            config = MCPJsonConfig(filename=f.name)
            config.add_server("test", {"command": "node", "args": ["server.js"]})

            # Should use the filename as default path
            result = config.to_json()
            assert result is None  # Returns None when writing to file

            # Verify file was written
            assert Path(f.name).exists()

            # Verify content
            with open(f.name) as read_f:
                written_data = json.load(read_f)
                assert "mcpServers" in written_data
                assert "test" in written_data["mcpServers"]

            Path(f.name).unlink(missing_ok=True)

    def test_to_json_explicit_path_overrides_filename(self):
        """Test that explicit path overrides filename."""
        config = MCPJsonConfig(filename="/should/not/be/used.json")
        config.add_server("test", {"command": "python"})

        with tempfile.NamedTemporaryFile(delete=False) as f:
            explicit_path = f.name

            # Should use explicit path, not filename
            result = config.to_json(path=explicit_path)
            assert result is None

            # Verify file was written to explicit path
            assert Path(explicit_path).exists()
            Path(explicit_path).unlink(missing_ok=True)

    def test_save_method_basic(self):
        """Test the save convenience method."""
        config = MCPJsonConfig()
        config.add_server("test", {"command": "docker", "args": ["run", "myimage"]})

        with tempfile.NamedTemporaryFile(delete=False) as f:
            temp_path = f.name

            # Save to specific path
            config.save(path=temp_path)

            # Should update the filename
            assert config.filename == temp_path

            # Verify file was written
            assert Path(temp_path).exists()

            # Verify content
            saved_config = MCPJsonConfig.from_json(path=temp_path)
            assert "test" in saved_config.mcp_servers
            assert saved_config.mcp_servers["test"].command == "docker"

            Path(temp_path).unlink(missing_ok=True)

    def test_save_method_uses_filename(self):
        """Test that save method uses instance filename."""
        config = MCPJsonConfig()
        config.add_server("test", {"command": "npm", "args": ["start"]})

        with tempfile.NamedTemporaryFile(delete=False) as f:
            config.filename = f.name

            # Save without explicit path - should use filename
            config.save()

            # Verify file was written
            assert Path(f.name).exists()

            # Verify content
            with open(f.name) as read_f:
                saved_data = json.load(read_f)
                assert "mcpServers" in saved_data
                assert "test" in saved_data["mcpServers"]

            Path(f.name).unlink(missing_ok=True)

    def test_save_method_no_path_or_filename_error(self):
        """Test that save method raises error when no path or filename available."""
        config = MCPJsonConfig()  # No filename set
        config.add_server("test", {"command": "java", "args": ["-jar", "app.jar"]})

        with pytest.raises(ValueError, match="No path provided and configuration has no filename"):
            config.save()

    def test_round_trip_with_filename_preservation(self):
        """Test that filename is preserved through load/save cycles."""
        original_config = MCPJsonConfig()
        original_config.add_server(
            "postgres",
            {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-postgres"],
                "env": {"DATABASE_URL": "postgres://localhost/test"},
            },
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            temp_path = f.name

        try:
            # Save original config
            original_config.save(path=temp_path)

            # Load it back
            loaded_config = MCPJsonConfig.from_json(path=temp_path)

            # Should preserve filename
            assert loaded_config.filename == temp_path

            # Should preserve content
            assert "postgres" in loaded_config.mcp_servers
            postgres_server = loaded_config.mcp_servers["postgres"]
            assert postgres_server.command == "npx"
            assert postgres_server.env == {"DATABASE_URL": "postgres://localhost/test"}

            # Modify and save again (should use same filename)
            loaded_config.add_server("github", {"command": "node", "args": ["github-server.js"]})
            loaded_config.save()

            # Load again to verify
            final_config = MCPJsonConfig.from_json(path=temp_path)
            assert "postgres" in final_config.mcp_servers
            assert "github" in final_config.mcp_servers

        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestMCPContextProtectorDetector:
    """Test cases for MCPContextProtectorDetector class."""

    def test_direct_command_detection(self):
        """Test detection of direct mcp-context-protector commands."""
        # Direct command
        spec1 = MCPServerSpec(command="mcp-context-protector")
        assert MCPContextProtectorDetector.is_context_protector_configured(spec1)

        # Shell script
        spec2 = MCPServerSpec(command="mcp-context-protector.sh")
        assert MCPContextProtectorDetector.is_context_protector_configured(spec2)

        # Full path commands
        spec3 = MCPServerSpec(command="/path/to/mcp-context-protector.sh")
        assert MCPContextProtectorDetector.is_context_protector_configured(spec3)

        spec4 = MCPServerSpec(command="C:\\path\\to\\mcp-context-protector.bat")
        assert MCPContextProtectorDetector.is_context_protector_configured(spec4)

    def test_uv_run_detection(self):
        """Test detection of uv run mcp-context-protector patterns."""
        spec = MCPServerSpec(
            command="uv",
            args=["run", "mcp-context-protector", "--command-args", "node", "server.js"],
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec)

        # Should not detect other uv commands
        spec_false = MCPServerSpec(command="uv", args=["run", "other-command"])
        assert not MCPContextProtectorDetector.is_context_protector_configured(spec_false)

    def test_python_module_detection(self):
        """Test detection of python -m contextprotector patterns."""
        spec1 = MCPServerSpec(
            command="python", args=["-m", "contextprotector", "--command-args", "node", "server.js"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec1)

        spec2 = MCPServerSpec(command="python3", args=["-m", "contextprotector"])
        assert MCPContextProtectorDetector.is_context_protector_configured(spec2)

        # Should not detect other python modules
        spec_false = MCPServerSpec(command="python", args=["-m", "other_module"])
        assert not MCPContextProtectorDetector.is_context_protector_configured(spec_false)

    def test_argument_pattern_detection(self):
        """Test detection of context protector in arguments."""
        # Context protector in an argument
        spec1 = MCPServerSpec(
            command="bash", args=["/path/to/mcp-context-protector.sh", "--command-args", "node"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec1)

        # Contextprotector module reference
        spec2 = MCPServerSpec(
            command="docker", args=["run", "--rm", "-v", "/path/contextprotector:/app", "node"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec2)

    def test_shell_command_parsing(self):
        """Test parsing of complex shell commands."""
        # Quoted command with context protector
        spec1 = MCPServerSpec(
            command="bash",
            args=["-c", "'/path/to/mcp-context-protector.sh --command-args node server.js'"],
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec1)

        # Complex shell command
        spec2 = MCPServerSpec(
            command="sh",
            args=["-c", "cd /app && mcp-context-protector --command-args python -m server"],
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec2)

    def test_false_positives_avoided(self):
        """Test that false positives are avoided."""
        # Regular commands should not be detected
        spec1 = MCPServerSpec(command="node", args=["server.js"])
        assert not MCPContextProtectorDetector.is_context_protector_configured(spec1)

        spec2 = MCPServerSpec(command="python", args=["-m", "http.server"])
        assert not MCPContextProtectorDetector.is_context_protector_configured(spec2)

        spec3 = MCPServerSpec(command="npx", args=["@modelcontextprotocol/server-postgres"])
        assert not MCPContextProtectorDetector.is_context_protector_configured(spec3)

        # Empty command
        spec4 = MCPServerSpec(command="")
        assert not MCPContextProtectorDetector.is_context_protector_configured(spec4)

    def test_arbitrary_path_detection(self):
        """Test detection of mcp-context-protector at arbitrary filesystem paths."""
        # Unix-style absolute path
        spec1 = MCPServerSpec(command="/usr/local/bin/mcp-context-protector")
        assert MCPContextProtectorDetector.is_context_protector_configured(spec1)
        
        # Relative path
        spec2 = MCPServerSpec(command="./scripts/mcp-context-protector")
        assert MCPContextProtectorDetector.is_context_protector_configured(spec2)
        
        # Deep nested path
        spec3 = MCPServerSpec(command="/home/user/.local/bin/tools/mcp-context-protector.sh")
        assert MCPContextProtectorDetector.is_context_protector_configured(spec3)
        
        # Windows-style path
        spec4 = MCPServerSpec(command=r"C:\Users\User\AppData\Local\mcp-context-protector\mcp-context-protector.bat")
        assert MCPContextProtectorDetector.is_context_protector_configured(spec4)
        
        # Path with spaces (quoted)
        spec5 = MCPServerSpec(command="/path with spaces/mcp-context-protector.sh")
        assert MCPContextProtectorDetector.is_context_protector_configured(spec5)

    def test_uv_run_comprehensive_patterns(self):
        """Test comprehensive uv run patterns with various configurations."""
        # Standard uv run pattern
        spec1 = MCPServerSpec(
            command="uv",
            args=["run", "mcp-context-protector", "--command-args", "python", "server.py"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec1)
        
        # uv run with additional uv flags after run
        spec2 = MCPServerSpec(
            command="uv",
            args=["run", "--python", "3.11", "mcp-context-protector", "--command-args", "node", "server.js"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec2)
        
        # uv with global flags before run  
        spec2b = MCPServerSpec(
            command="uv",
            args=["--verbose", "--directory", "/path", "run", "mcp-context-protector", "--command-args", "python", "test.py"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec2b)
        
        # uv run with env vars and complex command args
        spec3 = MCPServerSpec(
            command="uv",
            args=[
                "run", 
                "mcp-context-protector", 
                "--command-args", 
                "docker", 
                "run", 
                "--rm", 
                "-v", 
                "/data:/app/data",
                "myimage:latest"
            ],
            env={"UV_CACHE_DIR": "/tmp/uv"}
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec3)
        
        # Should NOT detect other uv run commands
        spec_false1 = MCPServerSpec(command="uv", args=["run", "pytest"])
        assert not MCPContextProtectorDetector.is_context_protector_configured(spec_false1)
        
        spec_false2 = MCPServerSpec(command="uv", args=["run", "black", "."])
        assert not MCPContextProtectorDetector.is_context_protector_configured(spec_false2)

    def test_python_module_comprehensive_patterns(self):
        """Test comprehensive python -m contextprotector patterns."""
        # Standard python -m pattern
        spec1 = MCPServerSpec(
            command="python", 
            args=["-m", "contextprotector", "--command-args", "rust-analyzer", "--stdio"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec1)
        
        # python3 variant
        spec2 = MCPServerSpec(
            command="python3", 
            args=["-m", "contextprotector", "--command-args", "go", "run", "server.go"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec2)
        
        # With python flags
        spec3 = MCPServerSpec(
            command="python",
            args=["-O", "-m", "contextprotector", "--command-args", "java", "-jar", "server.jar"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec3)
        
        # Absolute python path
        spec4 = MCPServerSpec(
            command="/usr/bin/python3.11",
            args=["-m", "contextprotector", "--command-args", "npm", "start"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec4)
        
        # Virtual env python
        spec5 = MCPServerSpec(
            command="/path/to/venv/bin/python",
            args=["-m", "contextprotector", "--command-args", "php", "server.php"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec5)
        
        # Should NOT detect other python modules
        spec_false1 = MCPServerSpec(command="python", args=["-m", "http.server"])
        assert not MCPContextProtectorDetector.is_context_protector_configured(spec_false1)
        
        spec_false2 = MCPServerSpec(command="python3", args=["-m", "pip", "install", "contextprotector"])
        assert not MCPContextProtectorDetector.is_context_protector_configured(spec_false2)

    def test_complex_shell_invocation_patterns(self):
        """Test detection in complex shell invocation patterns."""
        # Shell script that calls mcp-context-protector
        spec1 = MCPServerSpec(
            command="bash",
            args=["/path/to/wrapper.sh", "/usr/local/bin/mcp-context-protector", "--command-args", "server"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec1)
        
        # Environment variable expansion in shell
        spec2 = MCPServerSpec(
            command="sh",
            args=["-c", "$HOME/bin/mcp-context-protector.sh --command-args python -m myserver"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec2)
        
        # Complex shell pipeline
        spec3 = MCPServerSpec(
            command="bash",
            args=["-c", "cd /app && /opt/mcp-context-protector/mcp-context-protector --command-args node index.js | tee server.log"]
        )
        assert MCPContextProtectorDetector.is_context_protector_configured(spec3)

    def test_edge_cases(self):
        """Test edge cases and error handling."""
        # Command with whitespace
        spec1 = MCPServerSpec(command="  mcp-context-protector  ")
        assert MCPContextProtectorDetector.is_context_protector_configured(spec1)

        # Malformed shell command (should fall back gracefully)
        spec2 = MCPServerSpec(command="bash", args=["-c", "unclosed quote 'mcp-context-protector"])
        assert MCPContextProtectorDetector.is_context_protector_configured(spec2)
        
        # Case sensitivity test - should be case sensitive for security
        spec3 = MCPServerSpec(command="MCP-CONTEXT-PROTECTOR")  # uppercase
        assert not MCPContextProtectorDetector.is_context_protector_configured(spec3)
        
        # Partial matches should not be detected
        spec4 = MCPServerSpec(command="my-mcp-context-protector-wrapper")
        assert not MCPContextProtectorDetector.is_context_protector_configured(spec4)
        
        # Empty args list
        spec5 = MCPServerSpec(command="mcp-context-protector", args=[])
        assert MCPContextProtectorDetector.is_context_protector_configured(spec5)

    def test_get_installation_path(self):
        """Test getting context protector installation path."""
        # This should find the current installation
        path = MCPContextProtectorDetector.get_context_protector_installation_path()
        if path:  # May be None in test environments
            assert isinstance(path, str)
            assert Path(path).exists()
            assert (Path(path) / "pyproject.toml").exists()

    def test_suggest_context_protector_command(self):
        """Test suggesting context protector wrapped commands."""
        original = MCPServerSpec(
            command="node", args=["server.js", "--port", "3000"], env={"NODE_ENV": "production"}
        )

        # Test without installation path (fallback modes)
        suggested = MCPContextProtectorDetector.suggest_context_protector_command(original, None)

        # Should wrap the original command
        assert "mcp-context-protector" in suggested.command or (
            suggested.command == "uv" and "mcp-context-protector" in suggested.args
        )

        # Should preserve original command and args
        assert "node" in suggested.args
        assert "server.js" in suggested.args
        assert "--port" in suggested.args
        assert "3000" in suggested.args

        # Should preserve environment
        assert suggested.env == original.env

    def test_suggest_with_installation_path(self):
        """Test suggesting with explicit installation path."""
        original = MCPServerSpec(command="python", args=["server.py"])

        # Get the actual installation path if available
        install_path = MCPContextProtectorDetector.get_context_protector_installation_path()

        if install_path:
            suggested = MCPContextProtectorDetector.suggest_context_protector_command(
                original, install_path
            )

            # Should use the shell script from the installation path
            assert suggested.command.endswith("mcp-context-protector.sh")
            assert "--command-args" in suggested.args
            assert "python" in suggested.args
            assert "server.py" in suggested.args


class TestMCPServerSpecMutations:
    """Test cases for MCPServerSpec mutation methods."""

    def test_with_context_protector_basic(self):
        """Test adding context protector to a basic server spec."""
        original = MCPServerSpec(
            command="node", args=["server.js", "--port", "3000"], env={"NODE_ENV": "production"}
        )

        # Should not be detected as using context protector initially
        assert not MCPContextProtectorDetector.is_context_protector_configured(original)

        # Add context protector
        protected = original.with_context_protector()

        # Should now be detected as using context protector
        assert MCPContextProtectorDetector.is_context_protector_configured(protected)

        # Should preserve environment
        assert protected.env == original.env

        # Should contain original command in args
        assert "node" in protected.args
        assert "server.js" in protected.args
        assert "--port" in protected.args
        assert "3000" in protected.args

    def test_with_context_protector_already_protected(self):
        """Test error when trying to add context protector to already protected server."""
        # Start with a context protector wrapped server
        protected = MCPServerSpec(
            command="mcp-context-protector.sh", args=["--command-args", "node", "server.js"]
        )

        # Should raise error when trying to add protection again
        with pytest.raises(ValueError, match="already configured to use MCP Context Protector"):
            protected.with_context_protector()

    def test_without_context_protector_direct_command(self):
        """Test removing context protector from direct command pattern."""
        protected = MCPServerSpec(
            command="mcp-context-protector",
            args=["--command-args", "node", "server.js", "--port", "3000"],
            env={"NODE_ENV": "production"},
        )

        # Should be detected as using context protector
        assert MCPContextProtectorDetector.is_context_protector_configured(protected)

        # Remove context protector
        original = protected.without_context_protector()

        # Should not be detected as using context protector anymore
        assert not MCPContextProtectorDetector.is_context_protector_configured(original)

        # Should restore original command
        assert original.command == "node"
        assert original.args == ["server.js", "--port", "3000"]
        assert original.env == {"NODE_ENV": "production"}

    def test_without_context_protector_shell_script(self):
        """Test removing context protector from shell script pattern."""
        protected = MCPServerSpec(
            command="/path/to/mcp-context-protector.sh",
            args=["--command-args", "python", "server.py"],
            env={"API_KEY": "secret"},
        )

        original = protected.without_context_protector()

        assert original.command == "python"
        assert original.args == ["server.py"]
        assert original.env == {"API_KEY": "secret"}

    def test_without_context_protector_uv_run(self):
        """Test removing context protector from uv run pattern."""
        protected = MCPServerSpec(
            command="uv",
            args=[
                "run",
                "mcp-context-protector",
                "--command-args",
                "npx",
                "server",
                "--config",
                "prod.json",
            ],
            env={"DEBUG": "false"},
        )

        original = protected.without_context_protector()

        assert original.command == "npx"
        assert original.args == ["server", "--config", "prod.json"]
        assert original.env == {"DEBUG": "false"}
        
        # Test UV with global flags before run
        protected_with_flags = MCPServerSpec(
            command="uv",
            args=[
                "--verbose",
                "--directory", 
                "/project",
                "run",
                "mcp-context-protector",
                "--command-args",
                "python",
                "server.py"
            ],
            env={"PYTHONPATH": "/app"},
        )
        original_with_flags = protected_with_flags.without_context_protector()
        assert original_with_flags.command == "python"
        assert original_with_flags.args == ["server.py"]
        assert original_with_flags.env == {"PYTHONPATH": "/app"}

    def test_without_context_protector_python_module(self):
        """Test removing context protector from python -m pattern."""
        protected = MCPServerSpec(
            command="python3",
            args=["-m", "contextprotector", "--command-args", "docker", "run", "--rm", "myimage"],
            env={"DOCKER_HOST": "tcp://localhost:2376"},
        )

        original = protected.without_context_protector()

        assert original.command == "docker"
        assert original.args == ["run", "--rm", "myimage"]
        assert original.env == {"DOCKER_HOST": "tcp://localhost:2376"}

    def test_without_context_protector_not_protected(self):
        """Test error when trying to remove context protector from unprotected server."""
        original = MCPServerSpec(command="node", args=["server.js"])

        with pytest.raises(ValueError, match="not configured to use MCP Context Protector"):
            original.without_context_protector()

    def test_without_context_protector_malformed(self):
        """Test error when context protector pattern is malformed."""
        # Missing --command-args
        malformed = MCPServerSpec(
            command="mcp-context-protector",
            args=["node", "server.js"],  # Missing --command-args
        )

        with pytest.raises(ValueError, match="Expected --command-args"):
            malformed.without_context_protector()

        # --command-args but no command after it
        malformed2 = MCPServerSpec(
            command="mcp-context-protector",
            args=["--command-args"],  # No command after --command-args
        )

        with pytest.raises(ValueError, match="No command found after --command-args"):
            malformed2.without_context_protector()

    def test_round_trip_transformation(self):
        """Test that adding and removing context protector preserves the original."""
        original = MCPServerSpec(
            command="python",
            args=["-m", "http.server", "8080"],
            env={"HOST": "127.0.0.1", "PORT": "8080"},
        )

        # Add context protector
        protected = original.with_context_protector()
        assert MCPContextProtectorDetector.is_context_protector_configured(protected)

        # Remove context protector
        restored = protected.without_context_protector()
        assert not MCPContextProtectorDetector.is_context_protector_configured(restored)

        # Should be equivalent to original
        assert restored.command == original.command
        assert restored.args == original.args
        assert restored.env == original.env

    def test_multiple_round_trips(self):
        """Test multiple add/remove cycles."""
        original = MCPServerSpec(command="go", args=["run", "main.go"], env={"GO111MODULE": "on"})

        # First cycle
        protected1 = original.with_context_protector()
        restored1 = protected1.without_context_protector()

        # Second cycle
        protected2 = restored1.with_context_protector()
        restored2 = protected2.without_context_protector()

        # All restored versions should match original
        assert restored1.command == original.command
        assert restored1.args == original.args
        assert restored1.env == original.env

        assert restored2.command == original.command
        assert restored2.args == original.args
        assert restored2.env == original.env

    def test_with_context_protector_explicit_path(self):
        """Test adding context protector with explicit installation path."""
        original = MCPServerSpec(command="rust-analyzer", args=["--stdio"])

        # Get current installation path if available
        install_path = MCPContextProtectorDetector.get_context_protector_installation_path()

        if install_path:
            protected = original.with_context_protector(install_path)

            # Should use the installation path
            assert protected.command.startswith(install_path)
            assert protected.command.endswith("mcp-context-protector.sh")

            # Should preserve original command and args
            assert "rust-analyzer" in protected.args
            assert "--stdio" in protected.args

    def test_edge_case_empty_args(self):
        """Test mutation with empty arguments."""
        original = MCPServerSpec(command="simple-server", args=[])

        # Add protection
        protected = original.with_context_protector()
        assert MCPContextProtectorDetector.is_context_protector_configured(protected)
        assert "simple-server" in protected.args

        # Remove protection
        restored = protected.without_context_protector()
        assert restored.command == "simple-server"
        assert restored.args == []

    def test_edge_case_empty_env(self):
        """Test mutation with empty environment."""
        original = MCPServerSpec(command="worker", args=["--daemon"], env={})

        # Add protection
        protected = original.with_context_protector()
        assert protected.env == {}

        # Remove protection
        restored = protected.without_context_protector()
        assert restored.env == {}

    def test_preserve_original_immutability(self):
        """Test that mutation methods don't modify the original object."""
        original = MCPServerSpec(command="server", args=["--port", "8080"], env={"DEBUG": "true"})

        # Store original state
        orig_command = original.command
        orig_args = original.args.copy()
        orig_env = original.env.copy()

        # Apply mutations
        protected = original.with_context_protector()

        # Original should be unchanged
        assert original.command == orig_command
        assert original.args == orig_args
        assert original.env == orig_env

        # Apply reverse mutation
        restored = protected.without_context_protector()

        # Original should still be unchanged
        assert original.command == orig_command
        assert original.args == orig_args
        assert original.env == orig_env

        # Restored version should match original
        assert original.command == restored.command
        assert original.args == restored.args
        assert original.env == restored.env


class TestClaudeDesktopExamples:
    """Test with real-world Claude Desktop configuration examples."""

    def test_postgres_example(self):
        """Test the PostgreSQL server example from documentation."""
        config_data = {
            "mcpServers": {
                "postgres": {
                    "command": "npx",
                    "args": [
                        "-y",
                        "@modelcontextprotocol/server-postgres",
                        "postgresql://localhost/mydb",
                    ],
                }
            }
        }

        config = MCPJsonConfig.from_dict(config_data)

        assert "postgres" in config.mcp_servers
        postgres_server = config.mcp_servers["postgres"]
        assert postgres_server.command == "npx"
        assert postgres_server.args == [
            "-y",
            "@modelcontextprotocol/server-postgres",
            "postgresql://localhost/mydb",
        ]
        assert postgres_server.env == {}

    def test_complex_multi_server_example(self):
        """Test a complex multi-server configuration."""
        config_data = {
            "globalShortcut": "Alt+C",
            "mcpServers": {
                "github": {
                    "command": "node",
                    "args": ["/path/to/github/server/index.js"],
                    "env": {"SAMPLE_CONFIG_VAR": "test_value"},
                },
                "sqlite": {
                    "command": "npx",
                    "args": ["mcp-server-sqlite", "--db-path", "/path/to/database.db"],
                },
                "filesystem": {
                    "command": "node",
                    "args": ["/path/to/filesystem/server/index.js", "/allowed/directory"],
                },
            },
        }

        config = MCPJsonConfig.from_dict(config_data)

        assert config.global_shortcut == "Alt+C"
        assert len(config.mcp_servers) == 3

        # Test GitHub server
        github = config.mcp_servers["github"]
        assert github.command == "node"
        assert github.env["SAMPLE_CONFIG_VAR"] == "test_value"

        # Test SQLite server
        sqlite = config.mcp_servers["sqlite"]
        assert sqlite.command == "npx"
        assert "--db-path" in sqlite.args

        # Test filesystem server
        filesystem = config.mcp_servers["filesystem"]
        assert filesystem.command == "node"
        assert "/allowed/directory" in filesystem.args

        # Test roundtrip
        json_str = config.to_json()
        restored = MCPJsonConfig.from_json(json_str=json_str)
        assert len(restored.mcp_servers) == 3
        assert restored.global_shortcut == "Alt+C"
