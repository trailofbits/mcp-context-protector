"""Context Protector main entry point.

This module provides the command-line interface for the Context Protector,
which wraps MCP servers to provide security guardrails and configuration management.
"""

import argparse
import asyncio
import logging
import sys

from .approval_cli import list_unapproved_configs, review_server_config
from .guardrails import GuardrailProvider, get_provider, get_provider_names
from .mcp_json_cli import manage_all_mcp_json_files, manage_mcp_json_file, wrap_mcp_json_file
from .mcp_wrapper import MCPWrapperServer
from .quarantine_cli import review_quarantine
from .wrapper_config import MCPWrapperConfig

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

    # Check if we're in MCP JSON file management mode
    if args.manage_mcp_json_file:
        manage_mcp_json_file(args.manage_mcp_json_file)
        return

    # Check if we're in manage all MCP JSON files mode
    if args.manage_all_mcp_json:
        manage_all_mcp_json_files()
        return

    # Check if we're in wrap MCP JSON file mode
    if args.wrap_mcp_json:
        wrap_mcp_json_file(args.wrap_mcp_json, args.environment)
        return

    # Check if we're in server review mode
    if args.review_server:
        await _launch_review(args, guardrail_provider)
        return

    # Normal operation mode (not review)
    # Create wrapper configuration from args
    try:
        config = MCPWrapperConfig.from_args(args, guardrail_provider)
        wrapper = MCPWrapperServer.from_config(config)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        await wrapper.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
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
        "--command-args",
        nargs="+",
        help=(
            "Start a wrapped server over the stdio transport using "
            "the specified command arguments (space-separated). "
            "Supports arguments with dashes (e.g. docker run --rm -i)"
        ),
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
            "(must be used with --command, --command-args, --url or --sse-url)"
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
    source_group.add_argument(
        "--manage-mcp-json-file",
        help="Interactively manage an MCP JSON configuration file",
    )
    source_group.add_argument(
        "--manage-all-mcp-json",
        action="store_true",
        help="Find and manage all MCP JSON configuration files from known locations",
    )
    source_group.add_argument(
        "--wrap-mcp-json",
        metavar="CONFIG_FILE",
        help="Wrap all MCP servers in the specified JSON config file with context-protector",
    )
    source_group.add_argument(
        "--environment",
        "-e",
        metavar="ENV",
        help="Select specific environment/profile for multi-environment configs",
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

    # Handle --command-args specially to support arguments with dashes
    if "--command-args" in sys.argv:
        # Use parse_known_args to get known args and let unknown args be part of command
        args, unknown_args = parser.parse_known_args()

        if args.command_args:
            # Combine the explicitly parsed command_args with any unknown args
            all_command_args = args.command_args + unknown_args
            args.command_args = all_command_args
        elif unknown_args:
            # If we have unknown args but no command_args, this is an error
            parser.error(f"unrecognized arguments: {' '.join(unknown_args)}")
    else:
        # Normal parsing when --command-args is not used
        args = parser.parse_args()

    # Validate that --command and --command-args are mutually exclusive
    if args.command and args.command_args:
        parser.error("--command and --command-args are mutually exclusive")

    # If --command-args is provided, convert it to a --command string
    if args.command_args:
        args.command = " ".join(args.command_args)

    return args


def main() -> None:
    """Launch async main function."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
