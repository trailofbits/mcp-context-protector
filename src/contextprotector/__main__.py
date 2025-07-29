"""Context Protector main entry point.

This module provides the command-line interface for the Context Protector,
which wraps MCP servers to provide security guardrails and configuration management.
"""

import argparse
import asyncio
import logging
import sys

from .guardrails import GuardrailProvider, get_provider, get_provider_names
from .mcp_wrapper import MCPWrapperServer, review_server_config
from .quarantine_cli import review_quarantine

logger = logging.getLogger("mcp_wrapper")


def _list_guardrails() -> None:
    """List available guardrail providers."""
    provider_names = get_provider_names()
    if provider_names:
        print("Available guardrail providers:")
        for provider in provider_names:
            print(f"  - {provider}")
    else:
        print("No guardrail providers found.")

def _load_guardrail_provider(args: argparse.Namespace) -> GuardrailProvider | None:
    if not args.guardrail_provider:
        return None

    provider_names = get_provider_names()
    if args.guardrail_provider not in provider_names:
        print(
            f"Error: Unknown guardrail provider '{args.guardrail_provider}'",
            file=sys.stderr,
        )
        print("Available providers: " + ", ".join(provider_names), file=sys.stderr)
        sys.exit(1)

    # Get the provider object
    guardrail_provider = get_provider(args.guardrail_provider)
    if not guardrail_provider:
        print(
            f"Error: Failed to initialize guardrail provider '{args.guardrail_provider}'",
            file=sys.stderr,
        )
        sys.exit(1)

    logger.info("Using guardrail provider: %s", guardrail_provider.name)
    return guardrail_provider

async def _launch_review(
        args: argparse.Namespace, guardrail_provider: GuardrailProvider | None
    ) -> None:
    # For review mode, we need either command or url
    if args.command:
        await review_server_config(
            "stdio",
            args.command,
            args.server_config_file,
            guardrail_provider,
            args.quarantine_path,
        )
    elif args.url:
        await review_server_config(
            "http",
            args.url,
            args.server_config_file,
            guardrail_provider,
            args.quarantine_path,
        )
    elif args.sse_url:
        await review_server_config(
            "sse",
            args.sse_url,
            args.server_config_file,
            guardrail_provider,
            args.quarantine_path,
        )
async def main_async() -> None:
    """Launch the wrapped server or review process specified in arguments."""
    args = _parse_args()

    # Check if we should just list guardrail providers and exit
    if args.list_guardrail_providers:
        _list_guardrails()
        return

    # Get guardrail provider object if specified
    guardrail_provider = _load_guardrail_provider(args)

    # Check if we're in quarantine review mode
    if args.review_quarantine:
        await review_quarantine(args.quarantine_path, args.quarantine_id)
        return

    if args.review_all_servers:
        await list_unapproved_configs(args.server_config_file)
        return

    # Check if we're in server review mode
    if args.review_server:
        await _launch_review(args, guardrail_provider)
        return

    # Normal operation mode (not review)
    # Determine which source was provided and create appropriate wrapper
    if args.command:
        wrapper = MCPWrapperServer.wrap_stdio(
            args.command,
            args.server_config_file,
            guardrail_provider,
            args.visualize_ansi_codes,
            args.quarantine_path,
        )
    elif args.url:
        wrapper = MCPWrapperServer.wrap_streamable_http(
            args.url,
            args.server_config_file,
            guardrail_provider,
            args.visualize_ansi_codes,
            args.quarantine_path,
        )
    elif args.sse_url:
        wrapper = MCPWrapperServer.wrap_http(
            args.sse_url,
            args.server_config_file,
            guardrail_provider,
            args.visualize_ansi_codes,
            args.quarantine_path,
        )
    else:
        # This should never happen due to the validation above
        # But we'll keep it as a fallback error message
        print(
            "Error: Either --command, --url, --sse-url, or "
            "--list-guardrail-providers must be provided",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        await wrapper.run()
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        await wrapper.stop_child_process()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    # Create mutually exclusive group for command, URL, list-guardrail-providers,
    # and review-quarantine
    source_group = parser.add_argument_group()
    source_group.add_argument(
        "--command",
        help="Start a wrapped server over the stdio transport using the specified command",
    )
    source_group.add_argument(
        "--url",
        help="Connect to a remote MCP server over streamable HTTP at the specified URL",
    )
    source_group.add_argument(
        "--sse-url", help="Connect to a remote MCP server over SSE at the specified URL"
    )
    source_group.add_argument(
        "--list-guardrail-providers",
        action="store_true",
        help="List available guardrail providers and exit",
    )
    source_group.add_argument(
        "--review-server",
        action="store_true",
        help=(
            "Review and approve changes to a specific server configuration "
            "(must be used with --command, --url or --sse-url)"
        ),
    )
    source_group.add_argument(
        "--review-quarantine",
        action="store_true",
        help="Review quarantined tool responses",
    )
    source_group.add_argument(
        "--review-all-servers",
        action="store_true",
        help="Review all unapproved server configurations",
    )

    # Add config file argument with new name
    parser.add_argument(
        "--server-config-file",
        help=(
            "The path to the server config database file "
            "(default: ~/.mcp-context-protector/servers.json)"
        ),
        default="",
    )

    # Add guardrail provider argument
    parser.add_argument(
        "--guardrail-provider",
        help="The guardrail provider to use for checking server configurations",
    )

    # Add ANSI escape code visualization argument
    parser.add_argument(
        "--visualize-ansi-codes",
        action="store_true",
        help="Make ANSI escape codes visible by replacing escape characters with 'ESC'",
    )

    # Add quarantine-id argument
    parser.add_argument(
        "--quarantine-id",
        help="The ID of a specific quarantined response to review",
    )

    # Add quarantine-path argument
    parser.add_argument(
        "--quarantine-path",
        help=(
            "The path to the quarantine database file "
            "(default: ~/.mcp-context-protector/quarantine.json)"
        ),
    )

    return parser.parse_args()

async def list_unapproved_configs(config_path: str | None = None) -> None: # noqa: C901 PLR0912 PLR0915
    """List and provide a menu for reviewing unapproved server configurations.

    Args:
    ----
        config_path: Optional path to the configuration database file.
                    If None, uses the default path.

    """
    from .mcp_config import MCPConfigDatabase
    from .mcp_wrapper import review_server_config

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
                server = unapproved_servers[index]
                print(f"\nReviewing: [{server['type'].upper()}] {server['identifier']}")

                # Call the existing review function
                await review_server_config(
                    server["type"], server["identifier"], config_path
                )

                # Refresh the list and continue
                unapproved_servers = config_db.list_unapproved_servers()
                if not unapproved_servers:
                    print("\n✓ All server configurations have been reviewed!")
                    break
                print(
                    f"\n{len(unapproved_servers)} unapproved configuration(s) remaining."
                )
            else:
                print("Invalid selection. Please try again.")
        except KeyboardInterrupt:
            print("\n\nExiting...")
            break


def _int_or_none(s: str) -> int | None:
    try:
        return int(s)
    except ValueError:
        return None

def main() -> None:
    """Launch async main function."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
