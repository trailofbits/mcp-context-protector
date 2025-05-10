import argparse
import asyncio
import logging
import sys
from contextprotector.guardrails import get_provider, get_provider_names
from contextprotector.mcp_wrapper import MCPWrapperServer, review_server_config

logger = logging.getLogger("mcp_wrapper")

async def main():
    parser = argparse.ArgumentParser(description="MCP Wrapper Server")

    # Create mutually exclusive group for command, URL, and list-guardrail-providers
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--command", help="The command to run as a child process")
    source_group.add_argument(
        "--url", help="The URL to connect to for a remote MCP server"
    )
    source_group.add_argument(
        "--list-guardrail-providers",
        action="store_true",
        help="List available guardrail providers and exit",
    )

    # Add config file argument with new name
    parser.add_argument(
        "--config-file", help="The path to the wrapper config file", default=""
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

    # Add review mode flag
    parser.add_argument(
        "--review",
        action="store_true",
        help="Review and approve server configuration before starting",
    )

    args = parser.parse_args()

    # Check if we should just list guardrail providers and exit
    if args.list_guardrail_providers:
        provider_names = get_provider_names()
        if provider_names:
            print("Available guardrail providers:")
            for provider in provider_names:
                print(f"  - {provider}")
        else:
            print("No guardrail providers found.")
        return

    # Validate that we have either command or URL for non-list operations
    if not args.list_guardrail_providers and not args.command and not args.url:
        print("Error: Either --command or --url must be provided", file=sys.stderr)
        sys.exit(1)

    # Get guardrail provider object if specified
    guardrail_provider = None
    if args.guardrail_provider:
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

        logger.info(f"Using guardrail provider: {guardrail_provider.name}")

    # Check if we're in review mode
    if args.review:
        # For review mode, we need either command or url
        if args.command:
            await review_server_config(
                "stdio", args.command, args.config_file, guardrail_provider
            )
        elif args.url:
            await review_server_config(
                "http", args.url, args.config_file, guardrail_provider
            )
        return

    # Normal operation mode (not review)
    # Determine which source was provided and create appropriate wrapper
    if args.command:
        wrapper = MCPWrapperServer.wrap_stdio(
            args.command,
            args.config_file,
            guardrail_provider,
            args.visualize_ansi_codes,
        )
    elif args.url:
        wrapper = MCPWrapperServer.wrap_http(
            args.url, args.config_file, guardrail_provider, args.visualize_ansi_codes
        )
    else:
        # This should never happen due to the validation above
        # But we'll keep it as a fallback error message
        print(
            "Error: Either --command, --url, or --list-guardrail-providers must be provided",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        await wrapper.run()
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        await wrapper.stop_child_process()


if __name__ == "__main__":
    asyncio.run(main())