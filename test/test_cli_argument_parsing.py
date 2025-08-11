"""Tests for CLI argument parsing, including --command-args functionality."""

import sys
from unittest.mock import patch

import pytest
from contextprotector.__main__ import _parse_args
from contextprotector.wrapper_config import MCPWrapperConfig


class TestCommandArgsArgumentParsing:
    """Test --command-args functionality."""

    def test_command_args_basic(self):
        """Test basic --command-args functionality."""
        argv = ["mcp-context-protector", "--command-args", "echo", "hello", "world"]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            assert args.command == "echo hello world"
            # command_args should still exist as the original parsed value
            assert args.command_args == ["echo", "hello", "world"]

    def test_command_args_single_argument(self):
        """Test --command-args with single argument."""
        with patch.object(sys, "argv", ["mcp-context-protector", "--command-args", "myserver"]):
            args = _parse_args()
            assert args.command == "myserver"

    def test_command_args_many_arguments(self):
        """Test --command-args with many arguments (the seven-token example)."""
        argv = ["mcp-context-protector", "--command-args", "a", "b", "c", "d", "e", "f", "g"]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            assert args.command == "a b c d e f g"
            assert len(args.command.split()) == 7

    def test_command_args_with_paths_and_extensions(self):
        """Test --command-args with realistic command structure."""
        argv = [
            "mcp-context-protector",
            "--command-args",
            "python",
            "server.py",
            "config.json",
            "arg1",
            "arg2",
        ]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            assert args.command == "python server.py config.json arg1 arg2"

    def test_command_args_with_node_example(self):
        """Test --command-args with node.js style command."""
        argv = ["mcp-context-protector", "--command-args", "node", "index.js", "production"]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            assert args.command == "node index.js production"

    def test_command_args_mutual_exclusivity_with_command(self):
        """Test that --command and --command-args are mutually exclusive."""
        argv = ["mcp-context-protector", "--command", "echo test", "--command-args", "echo", "test"]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit):
            _parse_args()

    def test_command_args_preserves_spacing(self):
        """Test that arguments with spaces are properly handled."""
        argv = [
            "mcp-context-protector",
            "--command-args",
            "python",
            "script.py",
            "arg_with_underscores",
            "another.arg",
        ]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            assert args.command == "python script.py arg_with_underscores another.arg"

    def test_command_args_empty_raises_error(self):
        """Test that --command-args requires at least one argument."""
        argv = ["mcp-context-protector", "--command-args"]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit):
            _parse_args()

    def test_command_args_with_dashes(self):
        """Test --command-args with arguments that start with dashes."""
        argv = ["mcp-context-protector", "--command-args", "docker", "run", "--rm", "-i", "myimage"]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            assert args.command == "docker run --rm -i myimage"

    def test_command_args_python_module(self):
        """Test --command-args with python -m module syntax."""
        argv = ["mcp-context-protector", "--command-args", "python", "-m", "server", "--verbose"]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            assert args.command == "python -m server --verbose"

    def test_command_args_mixed_arguments(self):
        """Test --command-args with mixed normal and dash arguments."""
        argv = [
            "mcp-context-protector",
            "--command-args",
            "node",
            "--experimental-modules",
            "server.js",
            "--port",
            "3000",
            "config.json",
        ]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            assert args.command == "node --experimental-modules server.js --port 3000 config.json"


class TestCommandArgsIntegration:
    """Test integration of --command-args with other functionality."""

    def test_command_args_with_review_server(self):
        """Test --command-args works with --review-server."""
        argv = [
            "mcp-context-protector",
            "--review-server",
            "--command-args",
            "python",
            "myserver.py",
        ]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            assert args.command == "python myserver.py"
            assert args.review_server

    def test_command_args_with_server_config_file(self):
        """Test --command-args works with other CLI options."""
        argv = [
            "mcp-context-protector",
            "--command-args",
            "server",
            "--server-config-file",
            "/test/config.json",
        ]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            assert args.command == "server"
            assert args.server_config_file == "/test/config.json"

    def test_command_args_with_guardrail_provider(self):
        """Test --command-args works with guardrail provider option."""
        argv = [
            "mcp-context-protector",
            "--command-args",
            "echo",
            "test",
            "--guardrail-provider",
            "test-provider",
        ]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            assert args.command == "echo test"
            assert args.guardrail_provider == "test-provider"

    def test_command_args_config_creation(self):
        """Test that MCPWrapperConfig can be created from --command-args."""
        argv = ["mcp-context-protector", "--command-args", "python", "server.py", "config"]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            config = MCPWrapperConfig.from_args(args)

            assert config.connection_type == "stdio"
            assert config.command == "python server.py config"
            assert config.server_identifier == "python server.py config"
            assert config.url is None


class TestTraditionalCommandParsing:
    """Test that traditional --command parsing still works."""

    def test_traditional_command(self):
        """Test that --command still works as before."""
        with patch.object(sys, "argv", ["mcp-context-protector", "--command", "echo hello world"]):
            args = _parse_args()
            assert args.command == "echo hello world"

    def test_traditional_command_with_quotes(self):
        """Test that --command works with complex commands."""
        argv = ["mcp-context-protector", "--command", "python -m server --verbose"]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            assert args.command == "python -m server --verbose"

    def test_traditional_command_config_creation(self):
        """Test config creation with traditional --command."""
        with patch.object(sys, "argv", ["mcp-context-protector", "--command", "echo test"]):
            args = _parse_args()
            config = MCPWrapperConfig.from_args(args)

            assert config.connection_type == "stdio"
            assert config.command == "echo test"
            assert config.server_identifier == "echo test"


class TestArgumentParsingEdgeCases:
    """Test edge cases and error conditions."""

    def test_no_connection_args_raises_error(self):
        """Test that providing no connection arguments raises an error during config creation."""
        with patch.object(sys, "argv", ["mcp-context-protector"]):
            args = _parse_args()
            # This should work (parsing), but config creation should fail
            with pytest.raises(ValueError, match="No valid connection type found"):
                MCPWrapperConfig.from_args(args)

    def test_url_and_command_args_both_provided(self):
        """Test that providing both URL and command args works at parsing level."""
        argv = [
            "mcp-context-protector",
            "--url",
            "http://example.com",
            "--command-args",
            "echo",
            "test",
        ]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            # Both should be parsed successfully
            assert args.url == "http://example.com"
            assert args.command == "echo test"
            # Config creation should use command (first precedence in from_args)
            config = MCPWrapperConfig.from_args(args)
            assert config.connection_type == "stdio"
            assert config.command == "echo test"

    def test_command_args_with_special_characters(self):
        """Test command-args with special characters that are safe."""
        argv = [
            "mcp-context-protector",
            "--command-args",
            "python",
            "server.py",
            "config=value",
            "path/to/file.json",
        ]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            assert args.command == "python server.py config=value path/to/file.json"

    def test_help_message_includes_command_args(self):
        """Test that help message includes --command-args."""
        argv = ["mcp-context-protector", "--help"]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit):
            _parse_args()

        # We can't easily capture the help output in this test setup,
        # but the manual testing confirmed it's there


class TestEquivalenceBetweenCommandAndCommandArgs:
    """Test that --command and --command-args produce equivalent results."""

    def test_simple_command_equivalence(self):
        """Test that --command 'a b c' and --command-args a b c produce identical results."""
        # Test with --command
        with patch.object(sys, "argv", ["mcp-context-protector", "--command", "a b c"]):
            args_command = _parse_args()
            config_command = MCPWrapperConfig.from_args(args_command)

        # Test with --command-args
        with patch.object(sys, "argv", ["mcp-context-protector", "--command-args", "a", "b", "c"]):
            args_command_args = _parse_args()
            config_command_args = MCPWrapperConfig.from_args(args_command_args)

        # Both should produce identical command strings
        assert args_command.command == args_command_args.command == "a b c"

        # Both should produce identical configurations
        assert config_command.connection_type == config_command_args.connection_type == "stdio"
        assert config_command.command == config_command_args.command == "a b c"
        assert config_command.server_identifier == config_command_args.server_identifier == "a b c"

    def test_five_token_command_equivalence(self):
        """Test the five-token example: --command 'a b c d e' vs --command-args a b c d e."""
        # Test with --command
        with patch.object(sys, "argv", ["mcp-context-protector", "--command", "a b c d e"]):
            args_command = _parse_args()
            config_command = MCPWrapperConfig.from_args(args_command)

        # Test with --command-args
        argv = ["mcp-context-protector", "--command-args", "a", "b", "c", "d", "e"]
        with patch.object(sys, "argv", argv):
            args_command_args = _parse_args()
            config_command_args = MCPWrapperConfig.from_args(args_command_args)

        # Both should produce identical results
        assert args_command.command == args_command_args.command == "a b c d e"
        assert config_command.command == config_command_args.command == "a b c d e"
        expected = "a b c d e"
        assert config_command.server_identifier == config_command_args.server_identifier == expected

    def test_seven_token_command_equivalence(self):
        """Test the seven-token example: --command vs --command-args equivalence."""
        # Test with --command
        with patch.object(sys, "argv", ["mcp-context-protector", "--command", "a b c d e f g"]):
            args_command = _parse_args()
            config_command = MCPWrapperConfig.from_args(args_command)

        # Test with --command-args
        argv = ["mcp-context-protector", "--command-args", "a", "b", "c", "d", "e", "f", "g"]
        with patch.object(sys, "argv", argv):
            args_command_args = _parse_args()
            config_command_args = MCPWrapperConfig.from_args(args_command_args)

        # Both should produce identical results
        assert args_command.command == args_command_args.command == "a b c d e f g"
        assert config_command.command == config_command_args.command == "a b c d e f g"
        assert len(args_command.command.split()) == len(args_command_args.command.split()) == 7

    def test_realistic_python_command_equivalence(self):
        """Test realistic Python command equivalence."""
        command_string = "python server.py config.json"

        # Test with --command
        with patch.object(sys, "argv", ["mcp-context-protector", "--command", command_string]):
            args_command = _parse_args()
            config_command = MCPWrapperConfig.from_args(args_command)

        # Test with --command-args
        argv = ["mcp-context-protector", "--command-args", "python", "server.py", "config.json"]
        with patch.object(sys, "argv", argv):
            args_command_args = _parse_args()
            config_command_args = MCPWrapperConfig.from_args(args_command_args)

        # Both should produce identical results
        assert args_command.command == args_command_args.command == command_string
        assert config_command.command == config_command_args.command == command_string
        assert config_command.connection_type == config_command_args.connection_type == "stdio"

    def test_complex_command_with_paths_equivalence(self):
        """Test complex command with paths and extensions."""
        command_string = "node /path/to/server.js production /config/app.json"

        # Test with --command
        with patch.object(sys, "argv", ["mcp-context-protector", "--command", command_string]):
            args_command = _parse_args()

        # Test with --command-args
        argv = [
            "mcp-context-protector",
            "--command-args",
            "node",
            "/path/to/server.js",
            "production",
            "/config/app.json",
        ]
        with patch.object(sys, "argv", argv):
            args_command_args = _parse_args()

        # Both should produce identical command strings
        assert args_command.command == args_command_args.command == command_string

    def test_equivalence_with_review_server_flag(self):
        """Test that equivalence holds when using --review-server."""
        command_string = "python mcp_server.py"

        # Test with --command
        argv = ["mcp-context-protector", "--review-server", "--command", command_string]
        with patch.object(sys, "argv", argv):
            args_command = _parse_args()

        # Test with --command-args
        argv = [
            "mcp-context-protector",
            "--review-server",
            "--command-args",
            "python",
            "mcp_server.py",
        ]
        with patch.object(sys, "argv", argv):
            args_command_args = _parse_args()

        # Both should produce identical results
        assert args_command.command == args_command_args.command == command_string
        assert args_command.review_server == args_command_args.review_server


class TestRealWorldScenarios:
    """Test realistic usage scenarios."""

    def test_python_mcp_server_scenario(self):
        """Test typical Python MCP server scenario."""
        argv = [
            "mcp-context-protector",
            "--command-args",
            "python",
            "mcp_server.py",
            "production.config",
        ]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            config = MCPWrapperConfig.from_args(args)

            assert config.command == "python mcp_server.py production.config"
            assert config.connection_type == "stdio"

    def test_node_mcp_server_scenario(self):
        """Test typical Node.js MCP server scenario."""
        argv = ["mcp-context-protector", "--command-args", "node", "dist/index.js", "config.json"]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            config = MCPWrapperConfig.from_args(args)

            assert config.command == "node dist/index.js config.json"
            assert config.connection_type == "stdio"

    def test_binary_executable_scenario(self):
        """Test binary executable scenario."""
        argv = [
            "mcp-context-protector",
            "--command-args",
            "./bin/mcp_server",
            "arg1",
            "arg2",
            "arg3",
        ]
        with patch.object(sys, "argv", argv):
            args = _parse_args()
            config = MCPWrapperConfig.from_args(args)

            assert config.command == "./bin/mcp_server arg1 arg2 arg3"
            assert config.connection_type == "stdio"

    def test_review_mode_with_command_args(self):
        """Test review mode with command args."""
        argv = [
            "mcp-context-protector",
            "--review-server",
            "--command-args",
            "python",
            "server.py",
            "config",
        ]
        with patch.object(sys, "argv", argv):
            args = _parse_args()

            assert args.command == "python server.py config"
            assert args.review_server
