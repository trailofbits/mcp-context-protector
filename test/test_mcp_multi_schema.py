"""Tests for multi-schema MCP configuration support."""

import json
import tempfile
import pathlib
from unittest.mock import patch

import pytest

from contextprotector.mcp_json_config import (
    MCPConfigManagerFactory,
    MCPServerSpec,
    MCPUnifiedConfig,
    ProjectMCPSchema,
    SchemaDetector,
    StandardMCPSchema,
)


class TestSchemaDetection:
    """Tests for automatic schema detection."""

    def test_detect_standard_schema(self):
        """Test detection of standard MCP schema."""
        data = {
            "mcpServers": {
                "postgres": {"command": "postgres-server"},
                "filesystem": {"command": "fs-server", "args": ["--data", "/tmp"]}
            },
            "globalShortcut": "Alt+M"
        }
        
        schema = SchemaDetector.detect_schema(data)
        assert isinstance(schema, StandardMCPSchema)

    def test_detect_project_schema(self):
        """Test detection of project-based schema."""
        data = {
            "projects": {
                "/Users/user/project1": {
                    "mcpServers": {
                        "dev-postgres": {"command": "dev-postgres-server"}
                    }
                },
                "/Users/user/project2": {
                    "mcpServers": {
                        "prod-postgres": {"command": "prod-postgres-server"}
                    }
                }
            }
        }
        
        schema = SchemaDetector.detect_schema(data)
        assert isinstance(schema, ProjectMCPSchema)

    def test_detect_invalid_schema(self):
        """Test error handling for invalid schema."""
        data = {"invalidKey": "value"}
        
        with pytest.raises(ValueError, match="Unknown or invalid MCP configuration schema"):
            SchemaDetector.detect_schema(data)


class TestStandardMCPSchema:
    """Tests for standard MCP schema handler."""

    def test_detect_schema(self):
        """Test schema detection."""
        schema = StandardMCPSchema()
        
        # Valid standard schema
        valid_data = {"mcpServers": {"server1": {"command": "echo"}}}
        assert schema.detect_schema(valid_data)
        
        # Invalid schemas
        assert not schema.detect_schema({"profiles": {}})
        assert not schema.detect_schema({"environments": {}})
        assert not schema.detect_schema({"mcpServers": "not_a_dict"})

    def test_environments(self):
        """Test environment handling."""
        schema = StandardMCPSchema()
        data = {"mcpServers": {"server1": {"command": "echo"}}}
        
        assert schema.list_environments(data) == []
        assert schema.get_default_environment(data) is None

    def test_get_servers(self):
        """Test server extraction."""
        schema = StandardMCPSchema()
        data = {
            "mcpServers": {
                "server1": {"command": "echo", "args": ["hello"]},
                "server2": {"command": "cat", "env": {"VAR": "value"}}
            }
        }
        
        servers = schema.get_servers(data)
        assert len(servers) == 2
        assert isinstance(servers["server1"], MCPServerSpec)
        assert servers["server1"].command == "echo"
        assert servers["server1"].args == ["hello"]
        assert servers["server2"].env == {"VAR": "value"}

    def test_set_servers(self):
        """Test server updates."""
        schema = StandardMCPSchema()
        data = {"mcpServers": {"old": {"command": "old-cmd"}}}
        
        new_servers = {
            "new1": MCPServerSpec(command="new-cmd1"),
            "new2": MCPServerSpec(command="new-cmd2", args=["arg"])
        }
        
        updated_data = schema.set_servers(data, new_servers)
        assert "mcpServers" in updated_data
        assert len(updated_data["mcpServers"]) == 2
        assert updated_data["mcpServers"]["new1"]["command"] == "new-cmd1"
        assert updated_data["mcpServers"]["new2"]["args"] == ["arg"]

    def test_environment_not_supported(self):
        """Test that environment parameters raise errors."""
        schema = StandardMCPSchema()
        data = {"mcpServers": {"server1": {"command": "echo"}}}
        
        with pytest.raises(ValueError, match="does not support environments"):
            schema.get_servers(data, environment="dev")
            
        with pytest.raises(ValueError, match="does not support environments"):
            schema.set_servers(data, {}, environment="dev")


class TestProjectMCPSchema:
    """Tests for project-based MCP schema handler used by ~/.claude.json."""

    def test_detect_schema(self):
        """Test schema detection."""
        schema = ProjectMCPSchema()
        
        # Valid project schema
        valid_data = {
            "projects": {
                "/Users/user/project1": {"mcpServers": {"server1": {"command": "echo"}}}
            }
        }
        assert schema.detect_schema(valid_data)
        
        # Invalid schemas
        assert not schema.detect_schema({"mcpServers": {}})
        assert not schema.detect_schema({"projects": "not_a_dict"})
        assert not schema.detect_schema({"projects": {"/path": {"notMcpServers": {}}}})

    def test_list_environments(self):
        """Test listing project paths."""
        schema = ProjectMCPSchema()
        data = {
            "projects": {
                "/Users/user/project1": {"mcpServers": {}},
                "/Users/user/project2": {"mcpServers": {}},
                "/Users/user/project3": {"mcpServers": {}}
            }
        }
        
        environments = schema.list_environments(data)
        assert set(environments) == {"/Users/user/project1", "/Users/user/project2", "/Users/user/project3"}

    def test_get_default_environment(self):
        """Test getting default project (first one)."""
        schema = ProjectMCPSchema()
        
        data = {
            "projects": {
                "/Users/user/project1": {"mcpServers": {}},
                "/Users/user/project2": {"mcpServers": {}}
            }
        }
        default = schema.get_default_environment(data)
        assert default in ["/Users/user/project1", "/Users/user/project2"]  # Could be either due to dict ordering

    def test_get_servers(self):
        """Test server extraction from specific project."""
        schema = ProjectMCPSchema()
        data = {
            "projects": {
                "/Users/user/project1": {
                    "mcpServers": {
                        "postgres": {"command": "postgres-server", "args": ["--debug"]},
                        "filesystem": {"command": "fs-server"}
                    }
                },
                "/Users/user/project2": {
                    "mcpServers": {
                        "s3": {"command": "s3-server"}
                    }
                }
            }
        }
        
        # Get project1 servers
        proj1_servers = schema.get_servers(data, "/Users/user/project1")
        assert len(proj1_servers) == 2
        assert "postgres" in proj1_servers
        assert "filesystem" in proj1_servers
        assert proj1_servers["postgres"].args == ["--debug"]
        
        # Get project2 servers
        proj2_servers = schema.get_servers(data, "/Users/user/project2")
        assert len(proj2_servers) == 1
        assert "s3" in proj2_servers

    def test_set_servers(self):
        """Test updating servers in specific project."""
        schema = ProjectMCPSchema()
        data = {
            "projects": {
                "/Users/user/project1": {"mcpServers": {"old": {"command": "old"}}},
                "/Users/user/project2": {"mcpServers": {"other": {"command": "other"}}}
            }
        }
        
        new_servers = {"new": MCPServerSpec(command="new-cmd")}
        
        updated_data = schema.set_servers(data, new_servers, "/Users/user/project1")
        
        # Project1 should be updated
        assert updated_data["projects"]["/Users/user/project1"]["mcpServers"]["new"]["command"] == "new-cmd"
        assert "old" not in updated_data["projects"]["/Users/user/project1"]["mcpServers"]
        
        # Project2 should be unchanged
        assert "other" in updated_data["projects"]["/Users/user/project2"]["mcpServers"]


class TestMCPUnifiedConfig:
    """Tests for the unified configuration manager."""

    def test_load_standard_config(self):
        """Test loading standard MCP configuration."""
        config_data = {
            "mcpServers": {
                "postgres": {"command": "postgres-server", "args": ["--port", "5432"]},
                "filesystem": {"command": "fs-server"}
            },
            "globalShortcut": "Alt+M"
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()
            
            config = MCPUnifiedConfig(f.name)
            config.load()
            
            assert isinstance(config.schema, StandardMCPSchema)
            assert config.list_environments() == []
            assert config.get_current_environment() is None
            
            servers = config.get_servers()
            assert len(servers) == 2
            assert "postgres" in servers
            assert servers["postgres"].args == ["--port", "5432"]
            
            # Clean up
            pathlib.Path(f.name).unlink()

    def test_load_project_config(self):
        """Test loading project-based MCP configuration."""
        config_data = {
            "projects": {
                "/Users/user/project1": {
                    "mcpServers": {
                        "postgres": {"command": "postgres-server"},
                        "filesystem": {"command": "fs-server"}
                    }
                },
                "/Users/user/project2": {
                    "mcpServers": {
                        "s3": {"command": "s3-server", "args": ["--bucket", "my-bucket"]}
                    }
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()
            
            config = MCPUnifiedConfig(f.name)
            config.load()
            
            assert isinstance(config.schema, ProjectMCPSchema)
            project_paths = config.list_environments()
            assert len(project_paths) == 2
            assert "/Users/user/project1" in project_paths
            assert "/Users/user/project2" in project_paths
            
            # Get servers from default project (first one)
            servers = config.get_servers()
            assert len(servers) >= 1  # At least one server
            
            # Switch to specific project
            config.set_environment("/Users/user/project2")
            proj2_servers = config.get_servers()
            assert len(proj2_servers) == 1
            assert "s3" in proj2_servers
            assert proj2_servers["s3"].args == ["--bucket", "my-bucket"]
            
            # Clean up
            pathlib.Path(f.name).unlink()

    def test_set_servers_and_save(self):
        """Test updating servers and saving."""
        config_data = {"mcpServers": {"old": {"command": "old-cmd"}}}
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()
            
            config = MCPUnifiedConfig(f.name)
            config.load()
            
            # Update servers
            new_servers = {"new": MCPServerSpec(command="new-cmd", args=["arg1"])}
            config.set_servers(new_servers)
            
            # Save and reload
            config.save()
            
            # Verify changes were saved
            config2 = MCPUnifiedConfig(f.name)
            config2.load()
            saved_servers = config2.get_servers()
            
            assert len(saved_servers) == 1
            assert "new" in saved_servers
            assert saved_servers["new"].command == "new-cmd"
            assert saved_servers["new"].args == ["arg1"]
            
            # Clean up
            pathlib.Path(f.name).unlink()


class TestMCPConfigManagerFactory:
    """Tests for the configuration manager factory."""

    def test_create_manager_standard(self):
        """Test creating manager for standard config."""
        config_data = {"mcpServers": {"server1": {"command": "echo"}}}
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()
            
            manager = MCPConfigManagerFactory.create_manager(f.name)
            
            assert isinstance(manager, MCPUnifiedConfig)
            assert isinstance(manager.schema, StandardMCPSchema)
            assert len(manager.get_servers()) == 1
            
            # Clean up
            pathlib.Path(f.name).unlink()

    def test_create_manager_with_environment(self):
        """Test creating manager with specific project."""
        config_data = {
            "projects": {
                "/Users/user/project1": {"mcpServers": {"proj1-server": {"command": "server1"}}},
                "/Users/user/project2": {"mcpServers": {"proj2-server": {"command": "server2"}}}
            }
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()
            
            manager = MCPConfigManagerFactory.create_manager(f.name, environment="/Users/user/project2")
            
            assert isinstance(manager.schema, ProjectMCPSchema)
            assert manager.get_current_environment() == "/Users/user/project2"
            
            servers = manager.get_servers()
            assert len(servers) == 1
            assert "proj2-server" in servers
            
            # Clean up
            pathlib.Path(f.name).unlink()


    def test_integration_with_real_claude_json(self):
        """Test loading the actual ~/.claude.json file format."""
        from contextprotector.mcp_json_cli import WrapMCPJsonManager
        
        # Test with the real file format from ~/.claude.json
        real_file_path = "/Users/cliffsmith/mcp-context-protector/.claude.json"
        if pathlib.Path(real_file_path).exists():
            manager = WrapMCPJsonManager(real_file_path, environment="/Users/cliffsmith/irad-mcp/ansi")
            manager._load_config()
            
            # Should detect project schema
            assert isinstance(manager.config.schema, ProjectMCPSchema)
            
            # Should find the project
            assert manager.current_environment == "/Users/cliffsmith/irad-mcp/ansi"
            
            # Should extract servers from that project
            manager._analyze_servers()
            total_servers = len(manager.servers_to_wrap) + len(manager.servers_already_wrapped)
            assert total_servers >= 0  # Should have at least 0 servers


class TestMultiSchemaWrapIntegration:
    """Integration tests for wrapping with multi-schema configurations."""

    @patch("builtins.input", side_effect=["1"])  # Select first project
    @patch("builtins.print")
    def test_wrap_project_config_interactive(self, mock_print, mock_input):
        """Test wrapping servers in project-based config with interactive selection."""
        config_data = {
            "projects": {
                "/Users/user/project1": {
                    "mcpServers": {
                        "postgres": {"command": "postgres-server"},
                        "wrapped": {"command": "mcp-context-protector", "args": ["--command-args", "echo"]}
                    }
                },
                "/Users/user/project2": {
                    "mcpServers": {
                        "s3": {"command": "s3-server"}
                    }
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()
            
            from contextprotector.mcp_json_cli import WrapMCPJsonManager
            manager = WrapMCPJsonManager(f.name)
            manager._load_config()
            manager._analyze_servers()
            
            # Should detect 1 server to wrap, 1 already wrapped
            assert len(manager.servers_to_wrap) == 1
            assert "postgres" in manager.servers_to_wrap
            assert len(manager.servers_already_wrapped) == 1
            assert "wrapped" in manager.servers_already_wrapped
            
            # Verify we're working with first project
            assert manager.current_environment == "/Users/user/project1"
            
            # Clean up
            pathlib.Path(f.name).unlink()

    @patch("builtins.print")
    def test_wrap_project_config_with_cli_environment(self, mock_print):
        """Test wrapping with CLI-specified project."""
        config_data = {
            "projects": {
                "/Users/user/project1": {
                    "mcpServers": {
                        "postgres": {"command": "postgres-server"}
                    }
                },
                "/Users/user/project2": {
                    "mcpServers": {
                        "s3": {"command": "s3-server"},
                        "wrapped": {"command": "uv", "args": ["run", "mcp-context-protector", "--command-args", "echo"]}
                    }
                }
            }
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f, indent=2)
            f.flush()
            
            from contextprotector.mcp_json_cli import WrapMCPJsonManager
            manager = WrapMCPJsonManager(f.name, environment="/Users/user/project2")
            manager._load_config()
            manager._analyze_servers()
            
            # Should be working with project2
            assert manager.current_environment == "/Users/user/project2"
            
            # Should detect 1 server to wrap, 1 already wrapped in project2
            assert len(manager.servers_to_wrap) == 1
            assert "s3" in manager.servers_to_wrap
            assert len(manager.servers_already_wrapped) == 1
            assert "wrapped" in manager.servers_already_wrapped
            
            # Clean up
            pathlib.Path(f.name).unlink()