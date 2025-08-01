"""Configuration class for MCPWrapperServer.

This module provides a centralized configuration class that incorporates all
the different parameters and settings that determine how the MCPWrapperServer
object is constructed and configured.
"""

import argparse
from dataclasses import dataclass, field
from typing import Literal

from .guardrails import GuardrailProvider


@dataclass
class MCPWrapperConfig:
    """Configuration for MCPWrapperServer instances.

    This class centralizes all the configuration parameters that control
    how the wrapper server behaves and connects to downstream servers.
    """

    # Connection configuration
    connection_type: Literal["stdio", "http", "sse"]

    # Connection-specific parameters (exactly one should be set)
    command: str | None = None  # For stdio connections
    url: str | None = None  # For http/sse connections

    # File paths
    config_path: str | None = None
    quarantine_path: str | None = None

    # Optional components
    guardrail_provider: GuardrailProvider | None = None

    # Behavior flags
    visualize_ansi_codes: bool = False

    # Internal state (computed properties)
    use_guardrails: bool = field(init=False)
    server_identifier: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate configuration and compute derived properties."""
        self._validate_connection_config()

        # Set default paths if not provided
        if self.config_path is None:
            from .mcp_config import MCPConfigDatabase

            self.config_path = MCPConfigDatabase.get_default_config_path()

        if self.quarantine_path is None:
            from .quarantine import ToolResponseQuarantine

            self.quarantine_path = ToolResponseQuarantine.get_default_db_path()

        self.use_guardrails = self.guardrail_provider is not None
        self.server_identifier = self._compute_server_identifier()

    def _validate_connection_config(self) -> None:
        """Validate that connection configuration is consistent."""
        if self.connection_type == "stdio":
            if self.command is None:
                msg = "command must be provided for stdio connections"
                raise ValueError(msg)
            if self.url is not None:
                msg = "url should not be provided for stdio connections"
                raise ValueError(msg)
        elif self.connection_type in ("http", "sse"):
            if self.url is None:
                msg = f"url must be provided for {self.connection_type} connections"
                raise ValueError(msg)
            if self.command is not None:
                msg = f"command should not be provided for {self.connection_type} connections"
                raise ValueError(msg)
        else:
            msg = f"Invalid connection_type: {self.connection_type}"
            raise ValueError(msg)

    def _compute_server_identifier(self) -> str:
        """Compute the server identifier based on connection type and parameters."""
        if self.connection_type == "stdio":
            return self.command
        return self.url

    @classmethod
    def from_args(
        cls,
        args: argparse.Namespace,
        guardrail_provider: GuardrailProvider | None = None,
    ) -> "MCPWrapperConfig":
        """Create configuration from parsed CLI arguments.

        Args:
        ----
            args: Parsed command line arguments containing connection and config info
            guardrail_provider: Optional guardrail provider object to use

        Returns:
        -------
            MCPWrapperConfig instance based on the provided arguments

        Raises:
        ------
            ValueError: If no valid connection type is found in args

        """
        # Determine connection type and create base config
        config = None
        if hasattr(args, "command") and args.command:
            config = cls.for_stdio(args.command)
        elif hasattr(args, "url") and args.url:
            config = cls.for_http(args.url)
        elif hasattr(args, "sse_url") and args.sse_url:
            config = cls.for_sse(args.sse_url)

        if config is None:
            msg = (
                "No valid connection type found in arguments. "
                "Must provide command, url, or sse_url."
            )
            raise ValueError(msg)

        # Set additional properties from args
        if hasattr(args, "server_config_file") and args.server_config_file:
            config.config_path = args.server_config_file
        if hasattr(args, "quarantine_path") and args.quarantine_path:
            config.quarantine_path = args.quarantine_path
        if hasattr(args, "visualize_ansi_codes"):
            config.visualize_ansi_codes = args.visualize_ansi_codes

        config.guardrail_provider = guardrail_provider

        return config

    @classmethod
    def for_stdio(cls, command: str) -> "MCPWrapperConfig":
        """Create configuration for stdio connection.

        Args:
        ----
            command: The command to run as a child process

        Returns:
        -------
            MCPWrapperConfig instance for stdio connection

        """
        return cls(
            connection_type="stdio",
            command=command,
        )

    @classmethod
    def for_http(cls, url: str) -> "MCPWrapperConfig":
        """Create configuration for HTTP connection.

        Args:
        ----
            url: The URL to connect to for a remote MCP server

        Returns:
        -------
            MCPWrapperConfig instance for HTTP connection

        """
        return cls(
            connection_type="http",
            url=url,
        )

    @classmethod
    def for_sse(cls, url: str) -> "MCPWrapperConfig":
        """Create configuration for SSE connection.

        Args:
        ----
            url: The URL to connect to for a remote MCP server

        Returns:
        -------
            MCPWrapperConfig instance for SSE connection

        """
        return cls(
            connection_type="sse",
            url=url,
        )

    def to_dict(self) -> dict[str, any]:
        """Convert configuration to dictionary representation.

        Returns
        -------
            Dictionary representation of the configuration

        """
        return {
            "connection_type": self.connection_type,
            "command": self.command,
            "url": self.url,
            "config_path": self.config_path,
            "quarantine_path": self.quarantine_path,
            "guardrail_provider": self.guardrail_provider.name if self.guardrail_provider else None,
            "visualize_ansi_codes": self.visualize_ansi_codes,
            "use_guardrails": self.use_guardrails,
            "server_identifier": self.server_identifier,
        }

    def __str__(self) -> str:
        """Create string representation of the configuration."""
        lines = [
            "MCPWrapperConfig:",
            f"  Connection: {self.connection_type}",
            f"  Server: {self.server_identifier}",
        ]

        if self.config_path:
            lines.append(f"  Config Path: {self.config_path}")

        if self.guardrail_provider:
            lines.append(f"  Guardrail Provider: {self.guardrail_provider.name}")

        if self.quarantine_path:
            lines.append(f"  Quarantine Path: {self.quarantine_path}")

        if self.visualize_ansi_codes:
            lines.append("  ANSI Visualization: Enabled")

        return "\n".join(lines)
