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
    url: str | None = None      # For http/sse connections

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
        # Determine connection type and identifier from args
        if hasattr(args, "command") and args.command:
            return cls.for_stdio(
                command=args.command,
                config_path=getattr(args, "server_config_file", None) or None,
                guardrail_provider=guardrail_provider,
                visualize_ansi_codes=getattr(args, "visualize_ansi_codes", False),
                quarantine_path=getattr(args, "quarantine_path", None),
            )
        if hasattr(args, "url") and args.url:
            return cls.for_http(
                url=args.url,
                config_path=getattr(args, "server_config_file", None) or None,
                guardrail_provider=guardrail_provider,
                visualize_ansi_codes=getattr(args, "visualize_ansi_codes", False),
                quarantine_path=getattr(args, "quarantine_path", None),
            )
        if hasattr(args, "sse_url") and args.sse_url:
            return cls.for_sse(
                url=args.sse_url,
                config_path=getattr(args, "server_config_file", None) or None,
                guardrail_provider=guardrail_provider,
                visualize_ansi_codes=getattr(args, "visualize_ansi_codes", False),
                quarantine_path=getattr(args, "quarantine_path", None),
            )
        msg = "No valid connection type found in arguments. Must provide command, url, or sse_url."
        raise ValueError(msg)

    @classmethod
    def for_stdio(
        cls,
        command: str,
        config_path: str | None = None,
        guardrail_provider: GuardrailProvider | None = None,
        visualize_ansi_codes: bool = False,
        quarantine_path: str | None = None,
    ) -> "MCPWrapperConfig":
        """Create configuration for stdio connection.

        Args:
        ----
            command: The command to run as a child process
            config_path: Optional path to the wrapper config file
            guardrail_provider: Optional guardrail provider object to use
            visualize_ansi_codes: Whether to make ANSI escape codes visible in tool outputs
            quarantine_path: Optional path to the quarantine database file

        Returns:
        -------
            MCPWrapperConfig instance for stdio connection

        """
        return cls(
            connection_type="stdio",
            command=command,
            config_path=config_path,
            guardrail_provider=guardrail_provider,
            visualize_ansi_codes=visualize_ansi_codes,
            quarantine_path=quarantine_path,
        )

    @classmethod
    def for_http(
        cls,
        url: str,
        config_path: str | None = None,
        guardrail_provider: GuardrailProvider | None = None,
        visualize_ansi_codes: bool = False,
        quarantine_path: str | None = None,
    ) -> "MCPWrapperConfig":
        """Create configuration for HTTP connection.

        Args:
        ----
            url: The URL to connect to for a remote MCP server
            config_path: Optional path to the wrapper config file
            guardrail_provider: Optional guardrail provider object to use
            visualize_ansi_codes: Whether to make ANSI escape codes visible in tool outputs
            quarantine_path: Optional path to the quarantine database file

        Returns:
        -------
            MCPWrapperConfig instance for HTTP connection

        """
        return cls(
            connection_type="http",
            url=url,
            config_path=config_path,
            guardrail_provider=guardrail_provider,
            visualize_ansi_codes=visualize_ansi_codes,
            quarantine_path=quarantine_path,
        )

    @classmethod
    def for_sse(
        cls,
        url: str,
        config_path: str | None = None,
        guardrail_provider: GuardrailProvider | None = None,
        visualize_ansi_codes: bool = False,
        quarantine_path: str | None = None,
    ) -> "MCPWrapperConfig":
        """Create configuration for SSE connection.

        Args:
        ----
            url: The URL to connect to for a remote MCP server
            config_path: Optional path to the wrapper config file
            guardrail_provider: Optional guardrail provider object to use
            visualize_ansi_codes: Whether to make ANSI escape codes visible in tool outputs
            quarantine_path: Optional path to the quarantine database file

        Returns:
        -------
            MCPWrapperConfig instance for SSE connection

        """
        return cls(
            connection_type="sse",
            url=url,
            config_path=config_path,
            guardrail_provider=guardrail_provider,
            visualize_ansi_codes=visualize_ansi_codes,
            quarantine_path=quarantine_path,
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
