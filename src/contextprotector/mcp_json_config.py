"""Classes for parsing and managing MCP JSON configuration files like claude_desktop_config.json."""

import json
import pathlib
import platform
import shlex
import shutil
from dataclasses import dataclass, field
from typing import Any, TextIO

# Constants for command pattern detection
MIN_ARGS_FOR_COMMAND_PATTERN = 2


class MCPJsonLocator:
    """Utility class for locating MCP configuration files across different platforms."""

    @staticmethod
    def get_claude_desktop_config_path() -> str:
        """Get the default Claude Desktop config path based on the platform."""
        system = platform.system()
        home_dir = pathlib.Path.home()

        if system == "Windows":
            # %APPDATA%/Claude/claude_desktop_config.json
            appdata = pathlib.Path.home() / "AppData" / "Roaming"
            return str(appdata / "Claude" / "claude_desktop_config.json")
        elif system == "Darwin":  # macOS
            # ~/Library/Application Support/Claude/claude_desktop_config.json
            config_path = home_dir / "Library" / "Application Support" / "Claude"
            return str(config_path / "claude_desktop_config.json")
        else:
            # Linux/Unix fallback to XDG config dir or ~/.config
            config_dir = pathlib.Path.home() / ".config" / "Claude"
            return str(config_dir / "claude_desktop_config.json")

    @staticmethod
    def get_claude_code_config_path() -> str:
        """Get the default Claude Code config path based on the platform."""
        system = platform.system()
        home_dir = pathlib.Path.home()

        if system == "Windows":
            # %APPDATA%/Claude Code/claude_code_config.json
            appdata = pathlib.Path.home() / "AppData" / "Roaming"
            return str(appdata / "Claude Code" / "claude_code_config.json")
        elif system == "Darwin":  # macOS
            # ~/Library/Application Support/Claude Code/claude_code_config.json
            config_path = home_dir / "Library" / "Application Support" / "Claude Code"
            return str(config_path / "claude_code_config.json")
        else:
            # Linux/Unix fallback to XDG config dir or ~/.config
            config_dir = pathlib.Path.home() / ".config" / "Claude Code"
            return str(config_dir / "claude_code_config.json")

    @staticmethod
    def get_cursor_config_path() -> str:
        """Get the default Cursor MCP config path based on the platform.

        Note: This returns the global ~/.cursor/mcp.json path. Cursor also supports
        project-specific .cursor/mcp.json files, but this method returns the global one.
        """
        system = platform.system()
        home_dir = pathlib.Path.home()

        if system == "Windows":
            # %USERPROFILE%/.cursor/mcp.json
            return str(home_dir / ".cursor" / "mcp.json")
        elif system == "Darwin":  # macOS
            # ~/.cursor/mcp.json
            return str(home_dir / ".cursor" / "mcp.json")
        else:
            # Linux/Unix - same path
            return str(home_dir / ".cursor" / "mcp.json")

    @staticmethod
    def get_cursor_cline_config_path() -> str:
        """Get the legacy Cursor Cline extension config path based on the platform.

        This is for the claude-dev/cline extension configuration, which is different
        from the native Cursor MCP support.
        """
        system = platform.system()
        home_dir = pathlib.Path.home()

        if system == "Windows":
            # %APPDATA%/Cursor/User/globalStorage/saoudrizwan.claude-dev/settings/
            # cline_mcp_settings.json
            appdata = pathlib.Path.home() / "AppData" / "Roaming"
            config_path = (
                appdata
                / "Cursor"
                / "User"
                / "globalStorage"
                / "saoudrizwan.claude-dev"
                / "settings"
            )
            return str(config_path / "cline_mcp_settings.json")
        elif system == "Darwin":  # macOS
            # ~/Library/Application Support/Cursor/User/globalStorage/saoudrizwan.claude-dev/
            # settings/cline_mcp_settings.json
            config_path = (
                home_dir
                / "Library"
                / "Application Support"
                / "Cursor"
                / "User"
                / "globalStorage"
                / "saoudrizwan.claude-dev"
                / "settings"
            )
            return str(config_path / "cline_mcp_settings.json")
        else:
            # Linux/Unix fallback to XDG config dir or ~/.config
            config_path = (
                home_dir
                / ".config"
                / "Cursor"
                / "User"
                / "globalStorage"
                / "saoudrizwan.claude-dev"
                / "settings"
            )
            return str(config_path / "cline_mcp_settings.json")

    @staticmethod
    def get_windsurf_config_path() -> str:
        """Get the default Windsurf MCP config path based on the platform."""
        system = platform.system()
        home_dir = pathlib.Path.home()

        if system == "Windows":
            # %USERPROFILE%/.codeium/windsurf/mcp_config.json
            return str(home_dir / ".codeium" / "windsurf" / "mcp_config.json")
        elif system == "Darwin":  # macOS
            # ~/.codeium/windsurf/mcp_config.json
            return str(home_dir / ".codeium" / "windsurf" / "mcp_config.json")
        else:
            # Linux/Unix - same path
            return str(home_dir / ".codeium" / "windsurf" / "mcp_config.json")

    @staticmethod
    def get_continue_config_path() -> str:
        """Get the default Continue.dev MCP config path based on the platform.

        Note: Continue.dev uses YAML format (config.yaml) but this returns the legacy JSON path
        for compatibility. The actual config may be in config.yaml instead of config.json.
        """
        system = platform.system()
        home_dir = pathlib.Path.home()

        if system == "Windows":
            # %USERPROFILE%/.continue/config.json (legacy) or config.yaml (preferred)
            return str(home_dir / ".continue" / "config.json")
        elif system == "Darwin":  # macOS
            # ~/.continue/config.json (legacy) or config.yaml (preferred)
            return str(home_dir / ".continue" / "config.json")
        else:
            # Linux/Unix - same path
            return str(home_dir / ".continue" / "config.json")

    @staticmethod
    def get_continue_yaml_config_path() -> str:
        """Get the default Continue.dev YAML config path based on the platform.

        This is the preferred configuration format for Continue.dev.
        """
        system = platform.system()
        home_dir = pathlib.Path.home()

        if system == "Windows":
            # %USERPROFILE%/.continue/config.yaml
            return str(home_dir / ".continue" / "config.yaml")
        elif system == "Darwin":  # macOS
            # ~/.continue/config.yaml
            return str(home_dir / ".continue" / "config.yaml")
        else:
            # Linux/Unix - same path
            return str(home_dir / ".continue" / "config.yaml")

    @staticmethod
    def get_vscode_user_mcp_config_path() -> str:
        """Get the VS Code user MCP config path based on the platform."""
        system = platform.system()
        home_dir = pathlib.Path.home()

        if system == "Windows":
            # %APPDATA%/Code/User/mcp.json
            appdata = home_dir / "AppData" / "Roaming"
            return str(appdata / "Code" / "User" / "mcp.json")
        elif system == "Darwin":  # macOS
            # ~/Library/Application Support/Code/User/mcp.json
            return str(home_dir / "Library" / "Application Support" / "Code" / "User" / "mcp.json")
        else:
            # Linux/Unix - ~/.config/Code/User/mcp.json
            return str(home_dir / ".config" / "Code" / "User" / "mcp.json")

    @staticmethod
    def get_all_mcp_config_paths() -> dict[str, str]:
        """Get all known MCP configuration file paths for different clients.

        Returns
        -------
            Dictionary mapping client names to their config file paths

        """
        return {
            "claude-desktop": MCPJsonLocator.get_claude_desktop_config_path(),
            "claude-code": MCPJsonLocator.get_claude_code_config_path(),
            "cursor": MCPJsonLocator.get_cursor_config_path(),
            "cursor-cline": MCPJsonLocator.get_cursor_cline_config_path(),
            "windsurf": MCPJsonLocator.get_windsurf_config_path(),
            "continue": MCPJsonLocator.get_continue_config_path(),
            "continue-yaml": MCPJsonLocator.get_continue_yaml_config_path(),
            "vscode": MCPJsonLocator.get_vscode_user_mcp_config_path(),
        }


class MCPContextProtectorDetector:
    """Utility class for detecting if MCP Context Protector is already configured for a server."""

    @staticmethod
    def is_context_protector_configured(server_spec: "MCPServerSpec") -> bool:  # noqa: PLR0911
        """Check if a server configuration already uses MCP Context Protector.

        This function analyzes the command and arguments to detect various ways
        that context protector might be invoked:
        - mcp-context-protector.sh script
        - uv run mcp-context-protector
        - direct mcp-context-protector command
        - python -m contextprotector

        Args:
        ----
            server_spec: The MCP server specification to check

        Returns:
        -------
            True if context protector is detected, False otherwise

        """
        if not server_spec.command:
            return False

        # Check the command itself
        command = server_spec.command.strip()

        # Direct invocations
        if command in ("mcp-context-protector", "mcp-context-protector.sh", "mcp-context-protector.bat"):
            return True

        # Check if command ends with the script name or installed entry point
        if (command.endswith("/mcp-context-protector.sh") or 
            command.endswith("\\mcp-context-protector.sh") or
            command.endswith("/mcp-context-protector.bat") or 
            command.endswith("\\mcp-context-protector.bat") or
            command.endswith("/mcp-context-protector") or
            command.endswith("\\mcp-context-protector")):
            return True

        # Check arguments for context protector patterns
        if server_spec.args:
            args = server_spec.args

            # uv run mcp-context-protector (with optional flags)
            if command == "uv" and len(args) >= MIN_ARGS_FOR_COMMAND_PATTERN:
                # Find the "run" subcommand, which may not be at index 0 due to global flags
                run_index = None
                for i, arg in enumerate(args):
                    if arg == "run":
                        run_index = i
                        break
                
                # Check if we have "mcp-context-protector" after "run"
                if (run_index is not None and 
                    run_index + 1 < len(args) and 
                    args[run_index + 1] == "mcp-context-protector"):
                    return True

            # python -m contextprotector (including absolute paths and python variants)
            is_python_command = (
                command in ("python", "python3") or
                command.endswith("/python") or
                command.endswith("/python3") or
                command.endswith("\\python.exe") or
                command.endswith("\\python3.exe") or
                command.endswith("/python3.11") or
                (command.startswith("/") and command.split("/")[-1].startswith("python"))
            )
            if (
                is_python_command
                and len(args) >= MIN_ARGS_FOR_COMMAND_PATTERN
                and args[0] == "-m"
                and args[1] == "contextprotector"
            ):
                return True

            # Check if any arg contains context protector references
            for arg in args:
                if isinstance(arg, str) and (
                    "mcp-context-protector" in arg or 
                    # Only detect contextprotector if it's not part of a pip install command
                    ("contextprotector" in arg and not (
                        len(args) >= 3 and args[0] == "-m" and args[1] == "pip" and args[2] == "install"
                    ))
                ):
                    return True

        # Check for shell command patterns (command might include args)
        full_command = f"{command} {' '.join(server_spec.args)}" if server_spec.args else command

        try:
            # Parse as shell command to handle quoted arguments
            parsed = shlex.split(full_command)

            for i, part in enumerate(parsed):
                # Check each part for context protector patterns
                # Be more specific about mcp-context-protector matching
                if (part == "mcp-context-protector" or 
                    part == "mcp-context-protector.sh" or
                    part == "mcp-context-protector.bat" or
                    part.endswith("/mcp-context-protector") or
                    part.endswith("\\mcp-context-protector") or
                    part.endswith("/mcp-context-protector.sh") or
                    part.endswith("\\mcp-context-protector.sh") or
                    part.endswith("/mcp-context-protector.bat") or
                    part.endswith("\\mcp-context-protector.bat")):
                    return True
                if part == "contextprotector" and i > 0 and parsed[i - 1] == "-m":
                    return True

        except ValueError:
            # If shlex parsing fails, fall back to simple string search
            # Only match if it appears to be the actual command, not just a substring
            if (" mcp-context-protector " in full_command or 
                full_command.startswith("mcp-context-protector ") or
                full_command.endswith(" mcp-context-protector") or
                full_command == "mcp-context-protector" or
                " -m contextprotector " in full_command):
                return True

        return False

    @staticmethod
    def get_context_protector_installation_path() -> str | None:
        """Get the path to the current MCP Context Protector installation.

        Returns
        -------
            Path to the installation directory, or None if not found

        """
        try:
            # Try to find the installation directory
            current_file = pathlib.Path(__file__).resolve()

            # Navigate up to find the project root
            # Look for pyproject.toml or mcp-context-protector.sh
            for parent in current_file.parents:
                if (parent / "pyproject.toml").exists() and (
                    parent / "mcp-context-protector.sh"
                ).exists():
                    # Verify this is the right project by checking pyproject.toml content
                    pyproject_path = parent / "pyproject.toml"
                    try:
                        with pyproject_path.open("r") as f:
                            content = f.read()
                            if 'name = "mcp-context-protector"' in content:
                                return str(parent)
                    except OSError:
                        continue

        except Exception:  # noqa: S110
            pass

        return None

    @staticmethod
    def suggest_context_protector_command(
        original_spec: "MCPServerSpec", installation_path: str | None = None
    ) -> "MCPServerSpec":
        """Suggest how to wrap an existing server command with context protector.

        Args:
        ----
            original_spec: The original MCP server specification
            installation_path: Path to context protector installation (auto-detected if None)

        Returns:
        -------
            A new MCPServerSpec that wraps the original with context protector

        """
        if installation_path is None:
            installation_path = (
                MCPContextProtectorDetector.get_context_protector_installation_path()
            )

        if installation_path:
            # Use the shell script for maximum compatibility
            script_path = pathlib.Path(installation_path) / "mcp-context-protector.sh"
            if script_path.exists():
                # Build wrapped command: script + --command-args + original command + original args
                new_args = ["--command-args", original_spec.command]
                new_args.extend(original_spec.args)

                return MCPServerSpec(
                    command=str(script_path), args=new_args, env=original_spec.env.copy()
                )

        # Fallback: use uv run if available
        if shutil.which("uv"):
            new_args = ["run", "mcp-context-protector", "--command-args", original_spec.command]
            new_args.extend(original_spec.args)

            return MCPServerSpec(command="uv", args=new_args, env=original_spec.env.copy())

        # Final fallback: direct command (assumes it's installed)
        new_args = ["--command-args", original_spec.command]
        new_args.extend(original_spec.args)

        return MCPServerSpec(
            command="mcp-context-protector", args=new_args, env=original_spec.env.copy()
        )


@dataclass
class MCPServerSpec:
    """Specification for an MCP server from a configuration file."""

    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary representation."""
        result: dict[str, Any] = {"command": self.command}
        if self.args:
            result["args"] = self.args
        if self.env:
            result["env"] = self.env
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPServerSpec":
        """Create from a dictionary representation."""
        if not isinstance(data, dict):
            raise ValueError("Server specification must be a dictionary")

        command = data.get("command")
        if not command or not isinstance(command, str):
            raise ValueError("Server specification must have a valid 'command' field")

        args = data.get("args", [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError("Server 'args' must be a list of strings")

        env = data.get("env", {})
        if not isinstance(env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in env.items()
        ):
            raise ValueError("Server 'env' must be a dictionary of string key-value pairs")

        return cls(command=command, args=args, env=env)

    def with_context_protector(self, installation_path: str | None = None) -> "MCPServerSpec":
        """Return a new MCPServerSpec that wraps this server with context protector.

        Args:
        ----
            installation_path: Path to context protector installation (auto-detected if None)

        Returns:
        -------
            A new MCPServerSpec that wraps the current server with context protector

        Raises:
        ------
            ValueError: If the server is already using context protector

        """
        # Check if already using context protector
        if MCPContextProtectorDetector.is_context_protector_configured(self):
            raise ValueError("Server is already configured to use MCP Context Protector")

        return MCPContextProtectorDetector.suggest_context_protector_command(
            self, installation_path
        )

    def without_context_protector(self) -> "MCPServerSpec":
        """Return a new MCPServerSpec with context protector removed.

        This method attempts to extract the original server command from a context protector
        wrapped configuration by parsing the --command-args pattern.

        Returns
        -------
            A new MCPServerSpec with context protector removed

        Raises
        ------
            ValueError: If the server is not using context protector or cannot be unwrapped

        """
        # Check if using context protector
        if not MCPContextProtectorDetector.is_context_protector_configured(self):
            raise ValueError("Server is not configured to use MCP Context Protector")

        # Try to extract the original command from different patterns

        # Pattern 1: Direct mcp-context-protector with --command-args
        if (
            self.command in ("mcp-context-protector", "mcp-context-protector.sh", "mcp-context-protector.bat")
            or self.command.endswith("/mcp-context-protector.sh")
            or self.command.endswith("\\mcp-context-protector.sh")
            or self.command.endswith("/mcp-context-protector.bat")
            or self.command.endswith("\\mcp-context-protector.bat")
        ):
            return self._extract_from_command_args()

        # Pattern 2: uv run mcp-context-protector (with optional flags)
        if self.command == "uv" and len(self.args) >= MIN_ARGS_FOR_COMMAND_PATTERN:
            # Find the "run" subcommand, which may not be at index 0 due to global flags
            run_index = None
            for i, arg in enumerate(self.args):
                if arg == "run":
                    run_index = i
                    break
            
            # Check if we have "mcp-context-protector" after "run"
            if (run_index is not None and 
                run_index + 1 < len(self.args) and 
                self.args[run_index + 1] == "mcp-context-protector"):
                return self._extract_from_uv_run(run_index)

        # Pattern 3: python -m contextprotector
        if (
            self.command in ("python", "python3")
            and len(self.args) >= MIN_ARGS_FOR_COMMAND_PATTERN
            and self.args[0] == "-m"
            and self.args[1] == "contextprotector"
        ):
            return self._extract_from_python_module()

        # Pattern 4: Complex shell commands - try to parse
        if self.args:
            for i, arg in enumerate(self.args):
                if isinstance(arg, str) and "--command-args" in arg:
                    # Handle cases where --command-args is part of a larger argument
                    try:
                        return self._extract_from_shell_pattern(i)
                    except Exception:  # noqa: S112
                        continue

        # If we can't parse it, raise an error
        raise ValueError(
            "Cannot automatically extract original server command from context protector "
            "configuration. The server appears to use context protector but in an "
            "unrecognized pattern."
        )

    def _extract_from_command_args(self) -> "MCPServerSpec":
        """Extract original command from --command-args pattern."""
        if not self.args or "--command-args" not in self.args:
            raise ValueError("Expected --command-args in arguments")

        try:
            command_args_index = self.args.index("--command-args")
            if command_args_index + 1 >= len(self.args):
                raise ValueError("No command found after --command-args")

            # Extract original command and args
            original_command = self.args[command_args_index + 1]
            original_args = self.args[command_args_index + 2 :]

            return MCPServerSpec(command=original_command, args=original_args, env=self.env.copy())
        except (ValueError, IndexError) as e:
            raise ValueError(f"Could not parse --command-args pattern: {e}") from e

    def _extract_from_uv_run(self, run_index: int = 0) -> "MCPServerSpec":
        """Extract original command from uv run pattern.
        
        Args:
        ----
            run_index: Index of the "run" argument in self.args
        """
        # Skip to after "run" and "mcp-context-protector"
        remaining_args = self.args[run_index + 2:]  # Skip "run" and "mcp-context-protector"

        if not remaining_args or "--command-args" not in remaining_args:
            raise ValueError("Expected --command-args in uv run pattern")

        try:
            command_args_index = remaining_args.index("--command-args")
            if command_args_index + 1 >= len(remaining_args):
                raise ValueError("No command found after --command-args")

            original_command = remaining_args[command_args_index + 1]
            original_args = remaining_args[command_args_index + 2 :]

            return MCPServerSpec(command=original_command, args=original_args, env=self.env.copy())
        except (ValueError, IndexError) as e:
            raise ValueError(f"Could not parse uv run pattern: {e}") from e

    def _extract_from_python_module(self) -> "MCPServerSpec":
        """Extract original command from python -m contextprotector pattern."""
        # Skip "-m", "contextprotector", then look for --command-args
        remaining_args = self.args[2:]  # Skip "-m" and "contextprotector"

        if not remaining_args or "--command-args" not in remaining_args:
            raise ValueError("Expected --command-args in python -m pattern")

        try:
            command_args_index = remaining_args.index("--command-args")
            if command_args_index + 1 >= len(remaining_args):
                raise ValueError("No command found after --command-args")

            original_command = remaining_args[command_args_index + 1]
            original_args = remaining_args[command_args_index + 2 :]

            return MCPServerSpec(command=original_command, args=original_args, env=self.env.copy())
        except (ValueError, IndexError) as e:
            raise ValueError(f"Could not parse python -m pattern: {e}") from e

    def _extract_from_shell_pattern(self, start_index: int) -> "MCPServerSpec":
        """Extract original command from shell command pattern."""
        # This is a more complex case - try to find --command-args and extract what follows
        remaining_args = self.args[start_index:]

        # Look for --command-args in the remaining arguments
        for i, arg in enumerate(remaining_args):
            if "--command-args" in str(arg) and i + 1 < len(remaining_args):
                # Found --command-args, now extract the command
                original_command = remaining_args[i + 1]
                original_args = remaining_args[i + 2 :]

                return MCPServerSpec(
                    command=original_command, args=original_args, env=self.env.copy()
                )

        raise ValueError("Could not locate original command in shell pattern")


@dataclass
class MCPJsonConfig:
    """Class representing an MCP JSON configuration file like claude_desktop_config.json."""

    mcp_servers: dict[str, MCPServerSpec] = field(default_factory=dict)
    global_shortcut: str | None = None
    other_config: dict[str, Any] = field(default_factory=dict)
    filename: str | None = None

    def add_server(self, name: str, server: MCPServerSpec | dict[str, Any]) -> None:
        """Add an MCP server to the configuration.

        Args:
        ----
            name: Name of the MCP server
            server: Either an MCPServerSpec object or a dictionary with server properties

        Raises:
        ------
            ValueError: If name is empty or server specification is invalid

        """
        if not name or not isinstance(name, str):
            raise ValueError("Server name must be a non-empty string")

        if isinstance(server, dict):
            self.mcp_servers[name] = MCPServerSpec.from_dict(server)
        elif isinstance(server, MCPServerSpec):
            self.mcp_servers[name] = server
        else:
            raise ValueError("Server must be either an MCPServerSpec object or a dictionary")

    def remove_server(self, name: str) -> None:
        """Remove an MCP server from the configuration by name."""
        self.mcp_servers.pop(name, None)

    def get_server(self, name: str) -> MCPServerSpec | None:
        """Get an MCP server from the configuration by name."""
        return self.mcp_servers.get(name)

    def list_servers(self) -> list[str]:
        """List all server names in the configuration."""
        return list(self.mcp_servers.keys())

    def to_dict(self) -> dict[str, Any]:
        """Convert the configuration to a dictionary."""
        result: dict[str, Any] = {
            "mcpServers": {name: server.to_dict() for name, server in self.mcp_servers.items()}
        }

        if self.global_shortcut:
            result["globalShortcut"] = self.global_shortcut

        result.update(self.other_config)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, filename: str | None = None) -> "MCPJsonConfig":
        """Create a configuration from a dictionary.

        Args:
        ----
            data: Dictionary containing the configuration data
            filename: Optional filename to associate with this configuration

        Returns:
        -------
            MCPJsonConfig instance

        Raises:
        ------
            ValueError: If the configuration data is invalid

        """
        config = cls(filename=filename)

        if data is None:
            return config

        if not isinstance(data, dict):
            raise ValueError("Configuration data must be a dictionary")

        # Parse mcpServers section
        mcp_servers_data = data.get("mcpServers", {})
        if not isinstance(mcp_servers_data, dict):
            raise ValueError("'mcpServers' must be a dictionary")

        for name, server_data in mcp_servers_data.items():
            try:
                config.add_server(name, server_data)
            except ValueError as e:
                raise ValueError(f"Invalid server configuration for '{name}': {e}") from e

        # Parse global shortcut
        global_shortcut = data.get("globalShortcut")
        if global_shortcut is not None and not isinstance(global_shortcut, str):
            raise ValueError("'globalShortcut' must be a string")
        config.global_shortcut = global_shortcut

        # Store other configuration keys
        config.other_config = {
            k: v for k, v in data.items() if k not in ("mcpServers", "globalShortcut")
        }

        return config

    def to_json(
        self, path: str | None = None, fp: TextIO | None = None, indent: int = 2
    ) -> str | None:
        """Serialize the configuration to JSON.

        Args:
        ----
            path: Optional file path to write the JSON to. If not provided and this config has a
                  filename, that will be used as the default path.
            fp: Optional file-like object to write the JSON to
            indent: Number of spaces for indentation (default: 2)

        Returns:
        -------
            JSON string if neither path nor fp is provided, None otherwise

        """
        config_dict = self.to_dict()
        json_str = json.dumps(config_dict, indent=indent)

        # Use the instance filename as default if no path specified
        write_path = path or self.filename

        if write_path:
            with pathlib.Path(write_path).open("w") as f:
                f.write(json_str)
            return None
        if fp:
            fp.write(json_str)
            return None
        return json_str

    def save(self, path: str | None = None, indent: int = 2) -> None:
        """Save the configuration to a file.

        This is a convenience method that calls to_json() with file writing.

        Args:
        ----
            path: Optional file path to write to. If not provided, uses the instance filename.
            indent: Number of spaces for indentation (default: 2)

        Raises:
        ------
            ValueError: If no path is provided and the instance has no filename

        """
        write_path = path or self.filename

        if not write_path:
            raise ValueError("No path provided and configuration has no filename")

        self.to_json(path=write_path, indent=indent)

        # Update the instance filename if we used a new path
        if path:
            self.filename = path

    @classmethod
    def from_json(
        cls, json_str: str | None = None, path: str | None = None, fp: TextIO | None = None
    ) -> "MCPJsonConfig":
        """Deserialize the configuration from JSON.

        Args:
        ----
            json_str: JSON string to parse
            path: Optional file path to read the JSON from
            fp: Optional file-like object to read the JSON from

        Returns:
        -------
            MCPJsonConfig instance

        Raises:
        ------
            ValueError: If no source is provided or multiple sources are provided
            json.JSONDecodeError: If the JSON is invalid
            FileNotFoundError: If the specified path does not exist

        """
        if sum(x is not None for x in (json_str, path, fp)) != 1:
            msg = "Exactly one of json_str, path, or fp must be provided"
            raise ValueError(msg)

        data = None
        source_filename = None

        if path:
            with pathlib.Path(path).open("r") as f:
                data = json.load(f)
                source_filename = path
        elif fp:
            data = json.load(fp)
            # Try to get filename from file object if it has a name attribute
            if hasattr(fp, "name") and fp.name not in {"<stdin>", "<stdout>"}:
                source_filename = fp.name
        elif json_str is not None:
            data = json.loads(json_str)

        return cls.from_dict(data, filename=source_filename)

    @classmethod
    def get_default_claude_desktop_config_path(cls) -> str:
        """Get the default Claude Desktop config path based on the platform.

        This method is deprecated. Use MCPJsonLocator.get_claude_desktop_config_path() instead.
        """
        return MCPJsonLocator.get_claude_desktop_config_path()
