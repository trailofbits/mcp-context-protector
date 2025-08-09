"""CLI interface for reviewing and managing server approval configurations."""

import logging
from typing import Literal

from .guardrails import GuardrailProvider
from .mcp_config import ApprovalStatus, MCPConfigDatabase
from .mcp_wrapper import MCPWrapperServer, make_ansi_escape_codes_visible
from .wrapper_config import MCPWrapperConfig

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("approval_cli")


async def review_server_config(
    connection_type: Literal["stdio", "http", "sse"],
    identifier: str,
    config_path: str | None = None,
    guardrail_provider: GuardrailProvider | None = None,
    quarantine_path: str | None = None,
) -> None:
    """Review and approve server configuration for the given connection.

    This function connects to the downstream server, retrieves its configuration,
    and prompts the user to approve it. If approved, the configuration is saved
    as trusted in the config database.

    Args:
    ----
        connection_type: Type of connection ("stdio", "http", or "sse")
        identifier: The server identifier (command for stdio, URL for http/sse)
        config_path: Optional path to the config database file
        guardrail_provider: Optional guardrail provider for security checks
        quarantine_path: Optional path to quarantine database

    """
    # Create configuration and wrapper
    if connection_type == "stdio":
        config = MCPWrapperConfig.for_stdio(identifier)
    elif connection_type == "http":
        config = MCPWrapperConfig.for_http(identifier)
    elif connection_type == "sse":
        config = MCPWrapperConfig.for_sse(identifier)

    # Set additional configuration properties
    if config_path:
        config.config_path = config_path
    if quarantine_path:
        config.quarantine_path = quarantine_path
    config.guardrail_provider = guardrail_provider

    wrapper = MCPWrapperServer.from_config(config)

    try:
        await wrapper.connect()

        if wrapper.config_approved:
            print(f"\nServer configuration for {identifier} is already trusted.")
            return

        print(f"\nServer configuration for {identifier} is not trusted or has changed.")

        _display_server_config(wrapper)

        response = (
            input("Do you want to trust this server configuration? (yes/no): ").strip().lower()
        )
        if response in ("yes", "y"):
            _approve_server_config(wrapper)
            print(f"\nThe server configuration for {identifier} has been trusted and saved.")
        else:
            print(f"\nThe server configuration for {identifier} has NOT been trusted.")
    finally:
        await wrapper.stop_child_process()


async def list_unapproved_configs(config_path: str | None = None) -> None:
    """List and provide a menu for reviewing unapproved server configurations.

    Args:
    ----
        config_path: Optional path to the configuration database file.
                    If None, uses the default path.

    """
    config_db = MCPConfigDatabase(config_path if config_path else None)

    unapproved_servers = config_db.list_unapproved_servers()

    if not unapproved_servers:
        print("No unapproved server configurations found.")
        return

    print(f"\nFound {len(unapproved_servers)} unapproved server configuration(s):\n")

    for i, server in enumerate(unapproved_servers, 1):
        print(f"{i}. [{server['type'].upper()}] {server['identifier']}")
        if server["has_config"]:
            print("   Status: Configuration available for review")
        else:
            print("   Status: No configuration data available")
        print()

    # Interactive menu
    while True:
        try:
            print("Options:")
            print(f"  [1-{len(unapproved_servers)}] Review and approve a specific server")
            print("  [a] Approve all servers")
            print("  [q] Quit")

            choice = input("\nEnter your choice: ").strip().lower()

            if choice == "q":
                break
            if choice == "a":
                # Approve all servers
                confirm = (
                    input("Are you sure you want to approve ALL unapproved servers? (yes/no): ")
                    .strip()
                    .lower()
                )
                if confirm in ("yes", "y"):
                    approved_count = 0
                    for server in unapproved_servers:
                        success = config_db.approve_server_config(
                            server["type"], server["identifier"]
                        )
                        if success:
                            approved_count += 1
                            print(f"✓ Approved: [{server['type'].upper()}] {server['identifier']}")
                        else:
                            print(
                                f"✗ Failed to approve: [{server['type'].upper()}] "
                                f"{server['identifier']}"
                            )
                    print(
                        f"\nApproved {approved_count} out of {len(unapproved_servers)} "
                        f"server configurations."
                    )
                    break
                print("Bulk approval cancelled.")
                continue
            index = _int_or_none(choice)
            if isinstance(index, int) and 1 <= index <= len(unapproved_servers):
                server = unapproved_servers[index - 1]
                print(f"\nReviewing: [{server['type'].upper()}] {server['identifier']}")

                # Call the existing review function
                await review_server_config(server["type"], server["identifier"], config_path)

                # Refresh the list and continue
                unapproved_servers = config_db.list_unapproved_servers()
                if not unapproved_servers:
                    print("\n✓ All server configurations have been reviewed!")
                    break
                print(f"\n{len(unapproved_servers)} unapproved configuration(s) remaining.")
            else:
                print("Invalid selection. Please try again.")
        except KeyboardInterrupt:
            print("\n\nExiting...")
            break


def _display_server_config(wrapper: MCPWrapperServer) -> None:
    """Display server configuration details for review.

    Args:
    ----
        wrapper: The wrapper server instance
        guardrail_provider: Optional guardrail provider

    """
    print(
        f"\nServer configuration for {wrapper.get_server_identifier()} "
        "is not trusted or has changed."
    )

    if wrapper.saved_config:
        print("\nPrevious configuration found. Checking for changes...")

        diff = wrapper.saved_config.compare(wrapper.current_config)
        if diff.has_differences():
            print("\n===== CONFIGURATION DIFFERENCES =====")
            print(make_ansi_escape_codes_visible(str(diff)))
            print("====================================\n")
        else:
            print("No differences found (configs are identical)")
    else:
        print("\nThis appears to be a new server.")

    print("\n===== TOOL LIST =====")
    for tool_spec in wrapper.tool_specs:
        print(f"• {tool_spec.name}: {make_ansi_escape_codes_visible(tool_spec.description)}")
    print("=====================\n")

    guardrail_alert = None
    if wrapper.guardrail_provider is not None:
        guardrail_alert = wrapper.guardrail_provider.check_server_config(wrapper.current_config)

        if guardrail_alert:
            print("\n==== GUARDRAIL CHECK: ALERT ====")
            print(f"Provider: {wrapper.guardrail_provider.name}")
            print(f"Alert: {guardrail_alert.explanation}")
            print("==================================\n")


def _approve_server_config(wrapper: MCPWrapperServer) -> None:
    """Approve the server configuration.

    Args:
    ----
        wrapper: The wrapper server instance

    """
    # First approve instructions
    wrapper.config_db.approve_instructions(
        wrapper.connection_type,
        wrapper.get_server_identifier(),
        wrapper.current_config.instructions,
    )

    # Then approve each tool individually
    for tool in wrapper.current_config.tools:
        wrapper.config_db.approve_tool(
            wrapper.connection_type,
            wrapper.get_server_identifier(),
            tool.name,
            tool,
        )

    # Finally set the server as approved
    wrapper.config_db.save_server_config(
        wrapper.connection_type,
        wrapper.get_server_identifier(),
        wrapper.current_config,
        ApprovalStatus.APPROVED,
    )


def _int_or_none(s: str) -> int | None:
    """Convert string to int or return None if conversion fails.

    Args:
    ----
        s: String to convert

    Returns:
    -------
        Integer value or None

    """
    try:
        return int(s)
    except ValueError:
        return None
