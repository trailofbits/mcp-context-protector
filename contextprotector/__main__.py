import argparse
import asyncio
import logging
import sys
from .guardrails import get_provider, get_provider_names
from .mcp_wrapper import MCPWrapperServer, review_server_config
from .quarantine_cli import review_quarantine

logger = logging.getLogger("mcp_wrapper")

async def main_async():
    parser = argparse.ArgumentParser()

    # Create mutually exclusive group for command, URL, list-guardrail-providers, and review-quarantine
    source_group = parser.add_argument_group()
    source_group.add_argument("--command", help="Start a wrapped server over the stdio transport using the specified command")
    source_group.add_argument(
        "--url", help="Connect to a remote MCP server over streamable HTTP at the specified URL"
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
        help="Review and approve server configuration before starting",
    )
    source_group.add_argument(
        "--review-quarantine",
        action="store_true",
        help="Review and manage quarantined tool responses",
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

    # Add quarantine-id argument
    parser.add_argument(
        "--quarantine-id",
        help="The ID of a specific quarantined response to review",
    )

    # Add quarantine-path argument
    parser.add_argument(
        "--quarantine-path",
        help="The path to the quarantine database file",
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

    # Check if we're in quarantine review mode
    if args.review_quarantine:
        await review_quarantine(args.quarantine_path, args.quarantine_id)
        return

    # Check if we're in server review mode
    if args.review_server:
        # For review mode, we need either command or url
        if args.command:
            await review_server_config(
                "stdio", args.command, args.config_file, guardrail_provider, args.quarantine_path
            )
        elif args.url:
            await review_server_config(
                "http", args.url, args.config_file, guardrail_provider, args.quarantine_path
            )
        elif args.sse_url:
            await review_server_config(
                "sse", args.sse_url, args.config_file, guardrail_provider, args.quarantine_path
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
            args.quarantine_path,
        )
    elif args.url:
        wrapper = MCPWrapperServer.wrap_streamable_http(
            args.url,
            args.config_file,
            guardrail_provider,
            args.visualize_ansi_codes,
            args.quarantine_path,
        )
    elif args.sse_url:
        wrapper = MCPWrapperServer.wrap_http(
            args.sse_url,
            args.config_file,
            guardrail_provider,
            args.visualize_ansi_codes,
            args.quarantine_path,
        )
    else:
        # This should never happen due to the validation above
        # But we'll keep it as a fallback error message
        print(
            "Error: Either --command, --url, --sse-url, or --list-guardrail-providers must be provided",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        await wrapper.run()
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        await wrapper.stop_child_process()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
