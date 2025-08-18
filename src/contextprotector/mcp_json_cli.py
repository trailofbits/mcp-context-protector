"""Interactive CLI for managing MCP JSON configuration files."""

import difflib
import json
import pathlib
import sys

from .mcp_json_config import (
    EnvironmentSelector,
    MCPConfigManagerFactory,
    MCPContextProtectorDetector,
    MCPJsonConfig,
    MCPJsonLocator,
    MCPServerSpec,
    MCPUnifiedConfig,
)

# Constants for display formatting
MAX_ARGS_DISPLAY_LENGTH = 60
MAX_ENV_KEYS_PREVIEW = 3
MAX_ARGS_PREVIEW_LENGTH = 60


class MCPJsonManager:
    """Interactive manager for MCP JSON configuration files."""

    def __init__(self, file_path: str, environment: str | None = None) -> None:
        """Initialize the manager with a configuration file path.

        Args:
        ----
            file_path: Path to the MCP JSON configuration file
            environment: Specific project/environment to manage (for multi-project configs)

        """
        self.file_path = pathlib.Path(file_path)
        self.environment = environment
        self.config: MCPJsonConfig | MCPUnifiedConfig | None = None
        self.original_json: str = ""

    def run(self) -> None:
        """Run the interactive MCP JSON management interface."""
        try:
            self._load_config()
            self._display_config()
            self._run_repl()
        except KeyboardInterrupt:
            print("\n\nExiting...")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    def _load_config(self) -> None:
        """Load the MCP JSON configuration file."""
        if not self.file_path.exists():
            print(f"Creating new MCP configuration file: {self.file_path}")
            self.config = MCPJsonConfig(filename=str(self.file_path))
            self.original_json = "{}"
        else:
            print(f"Loading MCP configuration from: {self.file_path}")
            
            # Try unified config first to handle multi-project configs
            try:
                unified_config = MCPConfigManagerFactory.create_manager(str(self.file_path), self.environment)
                environments = unified_config.list_environments()
                
                if environments:
                    # Multi-project config
                    if self.environment:
                        unified_config.set_environment(self.environment)
                        print(f"Managing project: {self.environment}")
                    else:
                        # Select first project as default
                        first_env = environments[0] 
                        unified_config.set_environment(first_env)
                        print(f"Managing project: {first_env}")
                    
                    self.config = unified_config
                else:
                    # Single-project config - fall back to legacy for compatibility
                    self.config = MCPJsonConfig.from_json(path=str(self.file_path))
                    
            except Exception:
                # Fallback to legacy config
                self.config = MCPJsonConfig.from_json(path=str(self.file_path))
            
            self.original_json = self.file_path.read_text()

        # Get server count for display
        if hasattr(self.config, 'get_servers'):
            servers = self.config.get_servers()
            server_count = len(servers)
        else:
            server_count = len(self.config.mcp_servers)
            
        print(f"Loaded {server_count} MCP server(s)\n")

    def _get_servers(self) -> dict[str, MCPServerSpec]:
        """Get servers from either config type."""
        if hasattr(self.config, 'get_servers'):
            return self.config.get_servers()
        else:
            return self.config.mcp_servers

    def _display_config(self) -> None:
        """Display the current configuration in a human-readable format."""
        if not self.config:
            return

        print("=" * 60)
        print("MCP JSON Configuration")
        print("=" * 60)

        # Get servers and show current project if applicable
        servers = self._get_servers()
        
        if hasattr(self.config, 'get_current_environment'):
            current_env = self.config.get_current_environment()
            if current_env:
                print(f"Current Project: {current_env}")
        
        # Show global shortcut for legacy configs
        global_shortcut = getattr(self.config, 'global_shortcut', None)
        if global_shortcut:
            print(f"Global Shortcut: {global_shortcut}")

        if not servers:
            print("No MCP servers configured.")
            return

        print(f"\nConfigured Servers ({len(servers)}):")
        print("-" * 40)

        for i, (name, server) in enumerate(servers.items(), 1):
            protected = MCPContextProtectorDetector.is_context_protector_configured(server)
            protection_status = "🛡️  PROTECTED" if protected else "⚠️  UNPROTECTED"

            print(f"\n{i:2d}. {name} ({protection_status})")
            print(f"    Command: {server.command}")

            if server.args:
                args_str = " ".join(server.args)
                if len(args_str) > MAX_ARGS_DISPLAY_LENGTH:
                    args_str = args_str[:57] + "..."
                print(f"    Args: {args_str}")

            if server.env:
                env_count = len(server.env)
                env_preview = ", ".join(list(server.env.keys())[:MAX_ENV_KEYS_PREVIEW])
                if len(server.env) > MAX_ENV_KEYS_PREVIEW:
                    env_preview += "..."
                print(f"    Environment ({env_count}): {env_preview}")

        print()

    def _run_repl(self) -> None:
        """Run the interactive REPL for managing servers."""
        if not self.config:
            return

        while True:
            print("=" * 60)
            print("MCP JSON Manager")
            print("=" * 60)
            print("Commands:")
            servers = self._get_servers()
            server_count = len(servers)
            if server_count > 0:
                if server_count == 1:
                    print("  [1]    - Select server 1 to toggle protection")
                else:
                    print(f"  [1-{server_count}]  - Select server by number to toggle protection")
            print("  'r'    - Reload from disk and refresh display")
            print("  'q'    - Quit without saving")
            print("  's'    - Save changes")
            print()

            try:
                choice = input("Enter your choice: ").strip().lower()

                if choice == "q":
                    print("Exiting without saving...")
                    break
                elif choice == "r":
                    print("Reloading configuration from disk...")
                    self._load_config()
                    self._display_config()
                elif choice == "s":
                    if self._save_with_confirmation():
                        print("Configuration saved successfully!")
                        break
                elif choice.isdigit():
                    server_num = int(choice)
                    servers = self._get_servers()
                    if 1 <= server_num <= len(servers):
                        self._toggle_server_protection(server_num)
                        self._display_config()
                    else:
                        server_count = len(servers)
                        print(f"Invalid server number. Please choose 1-{server_count}")
                else:
                    print("Invalid choice.")

            except (EOFError, KeyboardInterrupt):
                print("\n\nExiting...")
                break
            except ValueError:
                print("Invalid input. Please enter a number or command.")

    def _toggle_server_protection(self, server_num: int) -> None:
        """Toggle context protector for the specified server.

        Args:
        ----
            server_num: 1-based server number

        """
        if not self.config:
            return

        servers = self._get_servers()
        server_names = list(servers.keys())
        server_name = server_names[server_num - 1]
        current_spec = servers[server_name]

        is_protected = MCPContextProtectorDetector.is_context_protector_configured(current_spec)

        try:
            if is_protected:
                # Remove protection
                new_spec = current_spec.without_context_protector()
                action = "Removed"
                print(f"\n🔓 Removing protection from '{server_name}'...")
            else:
                # Add protection
                new_spec = current_spec.with_context_protector()
                action = "Added"
                print(f"\n🛡️  Adding protection to '{server_name}'...")

            # Update the configuration
            if hasattr(self.config, 'get_servers'):
                # Unified config - update servers
                updated_servers = servers.copy()
                updated_servers[server_name] = new_spec
                self.config.set_servers(updated_servers)
            else:
                # Legacy config - direct update
                self.config.mcp_servers[server_name] = new_spec

            print(f"{action} context protector for '{server_name}'")
            print(f"New command: {new_spec.command}")
            if new_spec.args:
                print(f"New args: {' '.join(new_spec.args)}")

        except ValueError as e:
            print(f"\nError: {e}")

    def _save_with_confirmation(self) -> bool:
        """Show diff and ask for confirmation before saving.

        Returns
        -------
            True if the user confirmed and file was saved, False otherwise

        """
        if not self.config:
            return False

        # Generate new JSON without saving
        if hasattr(self.config, 'raw_data'):
            # Unified config - use raw_data
            new_json = json.dumps(self.config.raw_data, indent=2)
        else:
            # Legacy config - use to_dict
            new_json = json.dumps(self.config.to_dict(), indent=2)

        # Check if there are any changes
        if new_json.strip() == self.original_json.strip():
            print("No changes to save.")
            return True

        # Show the diff
        print("\n" + "=" * 60)
        print("PROPOSED CHANGES")
        print("=" * 60)

        original_lines = self.original_json.splitlines(keepends=True)
        new_lines = new_json.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"{self.file_path} (original)",
            tofile=f"{self.file_path} (modified)",
            lineterm="",
        )

        for line in diff:
            if line.startswith("+++") or line.startswith("---"):
                print(f"\033[1m{line}\033[0m", end="")  # Bold
            elif line.startswith("@@"):
                print(f"\033[36m{line}\033[0m", end="")  # Cyan
            elif line.startswith("+"):
                print(f"\033[32m{line}\033[0m", end="")  # Green
            elif line.startswith("-"):
                print(f"\033[31m{line}\033[0m", end="")  # Red
            else:
                print(line, end="")

        print("\n" + "=" * 60)

        # Ask for confirmation
        while True:
            confirm = input("Do you want to save these changes? [y/N]: ").strip().lower()
            if confirm in ("", "n", "no"):
                print("Changes not saved.")
                return False
            elif confirm in ("y", "yes"):
                break
            else:
                print("Please enter 'y' for yes or 'n' for no.")

        # Create backup if file exists
        if self.file_path.exists():
            backup_path = self.file_path.with_suffix(self.file_path.suffix + ".backup")
            backup_path.write_text(self.original_json)
            print(f"Backup saved to: {backup_path}")

        # Save the file
        try:
            if hasattr(self.config, 'raw_data'):
                # Unified config - has save() method
                self.config.save()
            else:
                # Legacy config - save with file path
                self.config.save()
            self.original_json = new_json  # Update our reference
            return True
        except Exception as e:
            print(f"Error saving file: {e}")
            return False


def manage_mcp_json_file(file_path: str) -> None:
    """Manage MCP JSON file management interactively.

    Args:
    ----
        file_path: Path to the MCP JSON configuration file

    """
    manager = MCPJsonManager(file_path)
    manager.run()


class AllMCPJsonManager:
    """Manager for discovering and selecting from all available MCP JSON configuration files."""

    def __init__(self) -> None:
        """Initialize the all MCP JSON manager."""
        # (client_name, path, server_count, environment)
        self.discovered_configs: list[tuple[str, str, int, str | None]] = []

    def run(self) -> None:
        """Run the discovery and selection interface."""
        try:
            self._discover_configs()
            if not self.discovered_configs:
                print("No MCP configuration files found in known locations.")
                return

            self._display_configs()
            self._run_selection_loop()
        except KeyboardInterrupt:
            print("\n\nExiting...")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    def _discover_configs(self) -> None:
        """Discover MCP configuration files from all known locations."""
        print("Searching for MCP configuration files...")

        all_paths = MCPJsonLocator.get_all_mcp_config_paths()

        for client_name, config_path in all_paths.items():
            config_file = pathlib.Path(config_path)

            if config_file.exists():
                try:
                    # Use unified config to handle all schema types
                    config = MCPConfigManagerFactory.create_manager(config_path)
                    environments = config.list_environments()
                    
                    if environments:
                        # Multi-project/environment config - add each project separately
                        for env in environments:
                            config.set_environment(env)
                            servers = config.get_servers()
                            server_count = len(servers)
                            
                            # Only add projects/environments that have MCP servers configured
                            if server_count > 0:
                                # Format: (client_name, config_path, server_count, environment)
                                env_display = env if len(env) <= 50 else "..." + env[-47:]
                                display_name = f"{client_name} ({env_display})"
                                self.discovered_configs.append((display_name, config_path, server_count, env))
                    else:
                        # Single-project config - show as before
                        servers = config.get_servers()
                        server_count = len(servers)
                        self.discovered_configs.append((client_name, config_path, server_count, None))
                        
                except Exception:
                    # If we can't parse it, still show it but with unknown server count
                    self.discovered_configs.append((client_name, config_path, -1, None))

        # Sort by client name for consistent display
        self.discovered_configs.sort(key=lambda x: x[0])

    def _display_configs(self) -> None:
        """Display the discovered configuration files."""
        print("\n" + "=" * 80)
        print("Discovered MCP Configuration Files")
        print("=" * 80)

        for i, (client_name, config_path, server_count, environment) in enumerate(self.discovered_configs, 1):
            if server_count == -1:
                server_info = "(unable to parse)"
            elif server_count == 0:
                server_info = "(no servers configured)"
            elif server_count == 1:
                server_info = "(1 server)"
            else:
                server_info = f"({server_count} servers)"

            # Only uppercase the base client name, not paths in parens
            if "(" in client_name and client_name.endswith(")"):
                base_name, path_part = client_name.split(" (", 1)
                display_name = f"{base_name.upper()} ({path_part}"
            else:
                display_name = client_name.upper()
            print(f"{i:2d}. {display_name}")
            print(f"    Path: {config_path}")
            if environment:
                print(f"    Project: {environment}")
            print(f"    Status: {server_info}")
            print()

    def _run_selection_loop(self) -> None:
        """Run the interactive selection loop."""
        while True:
            print("=" * 80)
            print("Select a configuration file to manage:")
            print("=" * 80)

            config_count = len(self.discovered_configs)
            if config_count == 1:
                print("  [1]    - Select configuration file 1")
            else:
                print(f"  [1-{config_count}]  - Select configuration file by number")
            print("  'r'    - Refresh and re-discover configuration files")
            print("  'q'    - Quit")
            print()

            try:
                choice = input("Enter your choice: ").strip().lower()

                if choice == "q":
                    print("Exiting...")
                    break
                elif choice == "r":
                    print("Refreshing configuration file discovery...")
                    self.discovered_configs.clear()
                    self._discover_configs()
                    if not self.discovered_configs:
                        print("No MCP configuration files found in known locations.")
                        continue
                    self._display_configs()
                elif choice.isdigit():
                    config_num = int(choice)
                    if 1 <= config_num <= len(self.discovered_configs):
                        client_name, config_path, server_count, environment = self.discovered_configs[
                            config_num - 1
                        ]

                        if server_count == -1:
                            warning_msg = (
                                f"\nWarning: Configuration file at {config_path} "
                                "could not be parsed."
                            )
                            print(warning_msg)
                            confirm = (
                                input("Do you want to try managing it anyway? [y/N]: ")
                                .strip()
                                .lower()
                            )
                            if confirm not in ("y", "yes"):
                                continue

                        # Only uppercase the base client name, not paths in parens
                        if "(" in client_name and client_name.endswith(")"):
                            base_name, path_part = client_name.split(" (", 1)
                            display_name = f"{base_name.upper()} ({path_part}"
                        else:
                            display_name = client_name.upper()
                            
                        if environment:
                            print(f"\nOpening {display_name} configuration: {config_path}")
                            print(f"Project: {environment}")
                        else:
                            print(f"\nOpening {display_name} configuration: {config_path}")
                        print("-" * 80)

                        # Launch the individual file manager
                        manager = MCPJsonManager(config_path, environment)
                        manager.run()

                        # After returning from individual manager, refresh discovery
                        print("\nReturning to configuration file selection...")
                        self.discovered_configs.clear()
                        self._discover_configs()
                        if self.discovered_configs:
                            self._display_configs()
                        else:
                            print("No MCP configuration files found in known locations.")
                            break
                    else:
                        config_count = len(self.discovered_configs)
                        print(f"Invalid selection. Please choose 1-{config_count}")
                else:
                    print("Invalid choice. Please enter a number, 'r' to refresh, or 'q' to quit.")

            except (EOFError, KeyboardInterrupt):
                print("\n\nExiting...")
                break
            except ValueError:
                print("Invalid input. Please enter a number, 'r' to refresh, or 'q' to quit.")


def manage_all_mcp_json_files() -> None:
    """Discover and manage all MCP JSON configuration files from known locations."""
    manager = AllMCPJsonManager()
    manager.run()


class WrapMCPJsonManager:
    """Manager for automatically wrapping MCP servers with context protector."""

    def __init__(self, file_path: str, environment: str | None = None) -> None:
        """Initialize the wrap manager with a configuration file path.

        Args:
        ----
            file_path: Path to the MCP JSON configuration file
            environment: Specific environment to target (auto-detected if None)

        """
        self.file_path = pathlib.Path(file_path)
        self.config: MCPUnifiedConfig | None = None
        self.original_json: str = ""
        self.cli_environment = environment
        self.current_environment: str | None = None
        self.servers_to_wrap: list[str] = []
        self.servers_already_wrapped: list[str] = []

    def run(self) -> None:
        """Run the automatic wrapping process."""
        try:
            if not self.file_path.exists():
                error_msg = f"Error: Configuration file does not exist: {self.file_path}"
                print(error_msg, file=sys.stderr)
                sys.exit(1)

            self._load_config()
            self._analyze_servers()

            if not self.servers_to_wrap:
                if self.servers_already_wrapped:
                    print("All servers are already wrapped with context protector.")
                    for server_name in self.servers_already_wrapped:
                        print(f"  ✓ {server_name} (already protected)")
                else:
                    print("No MCP servers found in the configuration file.")
                return

            self._display_analysis()

            if self._confirm_wrapping():
                self._wrap_servers()
                self._save_with_confirmation()
                print("\n✅ Server wrapping completed successfully!")
            else:
                print("Wrapping cancelled.")

        except KeyboardInterrupt:
            print("\n\nWrapping cancelled.")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    def _load_config(self) -> None:
        """Load the MCP JSON configuration file."""
        print(f"Loading MCP configuration from: {self.file_path}")
        
        # Create unified config manager
        self.config = MCPConfigManagerFactory.create_manager(str(self.file_path), self.cli_environment)
        self.original_json = self.file_path.read_text() if self.file_path.exists() else "{}"
        
        # Handle environment selection for multi-environment configs
        environments = self.config.list_environments()
        if environments:
            # Multi-environment config
            if self.cli_environment:
                # CLI environment specified
                self.current_environment = self.cli_environment
                print(f"Using environment: {self.current_environment}")
            else:
                # Interactive selection
                self.current_environment = EnvironmentSelector.select_environment(
                    self.config.schema, self.config.raw_data, interactive=True
                )
                if self.current_environment:
                    self.config.set_environment(self.current_environment)
                    print(f"Selected environment: {self.current_environment}")
        else:
            # Single-environment config
            self.current_environment = None
            
        # Display schema info
        schema_type = self.config.get_schema_type()
        if environments:
            env_info = f" (environment: {self.current_environment})"
        else:
            env_info = ""
        print(f"Detected schema: {schema_type}{env_info}")
        
        servers = self.config.get_servers()
        print(f"Loaded {len(servers)} MCP server(s)")

    def _analyze_servers(self) -> None:
        """Analyze which servers need wrapping."""
        if not self.config:
            return

        if hasattr(self.config, 'get_servers'):
            # New unified config system
            servers = self.config.get_servers()
        else:
            # Legacy MCPJsonConfig
            servers = self.config.mcp_servers
            
        for server_name, server_spec in servers.items():
            if MCPContextProtectorDetector.is_context_protector_configured(server_spec):
                self.servers_already_wrapped.append(server_name)
            else:
                self.servers_to_wrap.append(server_name)

    def _display_analysis(self) -> None:
        """Display the analysis of servers to be wrapped."""
        print("\n" + "=" * 70)
        print("MCP Server Wrapping Analysis")
        print("=" * 70)
        
        # Show schema and environment info
        if self.config:
            if hasattr(self.config, 'get_schema_type'):
                # New unified config system
                schema_type = self.config.get_schema_type()
                if self.current_environment:
                    print(f"Schema: {schema_type} (Environment: {self.current_environment})")
                else:
                    print(f"Schema: {schema_type}")
                print()
            # Legacy system doesn't show schema info

        if self.servers_already_wrapped:
            print(f"\n🛡️  Already Protected ({len(self.servers_already_wrapped)} servers):")
            for server_name in self.servers_already_wrapped:
                print(f"  ✓ {server_name}")

        if self.servers_to_wrap:
            print(f"\n⚠️  Servers to Wrap ({len(self.servers_to_wrap)} servers):")
            
            if hasattr(self.config, 'get_servers'):
                # New unified config system
                servers = self.config.get_servers()
            else:
                # Legacy MCPJsonConfig
                servers = self.config.mcp_servers
                
            for server_name in self.servers_to_wrap:
                server_spec = servers[server_name]
                print(f"  • {server_name}")
                print(f"    Current command: {server_spec.command}")
                if server_spec.args:
                    args_preview = " ".join(server_spec.args)
                    if len(args_preview) > MAX_ARGS_PREVIEW_LENGTH:
                        args_preview = args_preview[:57] + "..."
                    print(f"    Current args: {args_preview}")

    def _confirm_wrapping(self) -> bool:
        """Ask user for confirmation to proceed with wrapping."""
        print("\n" + "=" * 70)

        if len(self.servers_to_wrap) == 1:
            message = f"This will wrap 1 server ({self.servers_to_wrap[0]}) with context protector."
        else:
            message = f"This will wrap {len(self.servers_to_wrap)} servers with context protector."

        print(message)
        print("\nContext protector will:")
        print("  • Add security guardrails to server interactions")
        print("  • Preserve original server functionality")
        print("  • Create a backup of the original configuration")

        while True:
            confirm = input("\nDo you want to proceed with wrapping? [y/N]: ").strip().lower()
            if confirm in ("", "n", "no"):
                return False
            elif confirm in ("y", "yes"):
                return True
            else:
                print("Please enter 'y' for yes or 'n' for no.")

    def _wrap_servers(self) -> None:
        """Wrap the identified servers with context protector."""
        if not self.config:
            return

        print(f"\nWrapping {len(self.servers_to_wrap)} server(s)...")

        if hasattr(self.config, 'get_servers'):
            # New unified config system
            servers = self.config.get_servers()
            updated_servers = servers.copy()
        else:
            # Legacy MCPJsonConfig
            servers = self.config.mcp_servers
            updated_servers = None

        for server_name in self.servers_to_wrap:
            print(f"  🛡️  Wrapping {server_name}...")

            try:
                current_spec = servers[server_name]
                wrapped_spec = current_spec.with_context_protector()
                
                if updated_servers is not None:
                    # New system
                    updated_servers[server_name] = wrapped_spec
                else:
                    # Legacy system
                    self.config.mcp_servers[server_name] = wrapped_spec

                print(f"    ✓ Successfully wrapped {server_name}")
                print(f"    New command: {wrapped_spec.command}")
                if wrapped_spec.args:
                    args_preview = " ".join(wrapped_spec.args)
                    if len(args_preview) > MAX_ARGS_PREVIEW_LENGTH:
                        args_preview = args_preview[:57] + "..."
                    print(f"    New args: {args_preview}")

            except ValueError as e:
                print(f"    ❌ Failed to wrap {server_name}: {e}")
                
        # Update the configuration with wrapped servers (new system only)
        if updated_servers is not None:
            self.config.set_servers(updated_servers)

    def _save_with_confirmation(self) -> bool:
        """Show diff and ask for confirmation before saving."""
        if not self.config:
            return False

        # Generate new JSON
        if hasattr(self.config, 'raw_data'):
            # New unified config system
            new_json = json.dumps(self.config.raw_data, indent=2)
        else:
            # Legacy MCPJsonConfig for backward compatibility
            new_json = json.dumps(self.config.to_dict(), indent=2)

        # Check if there are any changes (there should be since we wrapped servers)
        if new_json.strip() == self.original_json.strip():
            print("No changes detected. This shouldn't happen after wrapping.")
            return False

        # Show the diff
        print("\n" + "=" * 70)
        print("PROPOSED CHANGES")
        print("=" * 70)

        original_lines = self.original_json.splitlines(keepends=True)
        new_lines = new_json.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"{self.file_path} (original)",
            tofile=f"{self.file_path} (wrapped)",
            lineterm="",
        )

        for line in diff:
            if line.startswith("+++") or line.startswith("---"):
                print(f"\033[1m{line}\033[0m", end="")  # Bold
            elif line.startswith("@@"):
                print(f"\033[36m{line}\033[0m", end="")  # Cyan
            elif line.startswith("+"):
                print(f"\033[32m{line}\033[0m", end="")  # Green
            elif line.startswith("-"):
                print(f"\033[31m{line}\033[0m", end="")  # Red
            else:
                print(line, end="")

        print("\n" + "=" * 70)

        # Ask for confirmation
        while True:
            confirm = input("Do you want to save these changes? [Y/n]: ").strip().lower()
            if confirm in ("", "y", "yes"):
                break
            elif confirm in ("n", "no"):
                print("Changes not saved.")
                return False
            else:
                print("Please enter 'y' for yes or 'n' for no.")

        # Create backup
        backup_path = self.file_path.with_suffix(self.file_path.suffix + ".backup")
        backup_path.write_text(self.original_json)
        print(f"Backup saved to: {backup_path}")

        # Save the file
        try:
            if hasattr(self.config, 'save') and callable(getattr(self.config, 'save')):
                self.config.save()
            else:
                # Legacy MCPJsonConfig 
                self.config.save(str(self.file_path))
            print(f"Configuration saved to: {self.file_path}")
            return True
        except Exception as e:
            print(f"Error saving file: {e}")
            return False


def wrap_mcp_json_file(file_path: str, environment: str | None = None) -> None:
    """Automatically wrap MCP servers in a JSON configuration file with context protector.

    Args:
    ----
        file_path: Path to the MCP JSON configuration file
        environment: Specific environment to target (auto-detected if None)

    """
    manager = WrapMCPJsonManager(file_path, environment)
    manager.run()
