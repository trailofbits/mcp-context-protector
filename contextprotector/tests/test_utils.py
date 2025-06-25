#!/usr/bin/env python3
"""
Utility functions for MCP wrapper tests.
"""

import sys
import asyncio
import subprocess
from pathlib import Path
from typing import Callable, Awaitable, Literal, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def approve_server_config_using_review(
    connection_type: Literal["stdio", "http", "sse"],
    identifier: str,
    config_path: str,
) -> None:
    """
    Run the --review-server process to approve a server configuration.

    Args:
        connection_type: Type of connection ("stdio", "http", or "sse")
        identifier: The command or URL to connect to
        config_path: Path to configuration file
    """
    # Prepare the command based on connection type
    cmd = [
        sys.executable,
        "-m",
        "contextprotector",
        "--review-server",
        "--config-file",
        config_path
    ]
    
    if connection_type == "stdio":
        cmd.extend(["--command", identifier])
    elif connection_type == "http":
        cmd.extend(["--url", identifier])
    elif connection_type == "sse":
        cmd.extend(["--sse-url", identifier])
    else:
        raise ValueError(f"Invalid connection type: {connection_type}")

    # Run the review process
    review_process = subprocess.Popen(
        cmd,
        cwd=Path(__file__).parent.parent.parent.resolve(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Wait for the review process to start
    await asyncio.sleep(1.5)

    # Send 'y' to approve the configuration
    review_process.stdin.write("y\n")
    review_process.stdin.flush()

    # Wait for the review process to complete
    stdout, stderr = review_process.communicate(timeout=5)

    # Verify the review process output
    assert review_process.returncode == 0, f"Review process failed with return code {review_process.returncode}: {stderr}"

    # Check for expected output in the review process
    assert "has been trusted and saved" in stdout, f"Missing expected approval message in output: {stdout}"


async def run_with_wrapper_session(
    callback: Callable[[ClientSession], Awaitable[None]],
    connection_type: Literal["stdio", "http", "sse"],
    identifier: str,
    config_path: str,
    visualize_ansi: bool = False,
    guardrail_provider: Optional[str] = None,
):
    """
    Run a test with a wrapper that connects to the specified downstream server.

    Args:
        callback: Async function to call with the client session
        connection_type: Type of connection ("stdio", "http", or "sse")
        identifier: The command or URL to connect to the downstream server
        config_path: Path to the wrapper config file
        visualize_ansi: Whether to visualize ANSI escape codes
        guardrail_provider: Optional guardrail provider to use
    """
    # Base arguments
    args = [
        "-m",
        "contextprotector",
        "--config-file",
        str(config_path),
    ]
    
    # Add connection type specific args
    if connection_type == "stdio":
        args.extend(["--command", identifier])
    elif connection_type == "http":
        args.extend(["--url", identifier])
    elif connection_type == "sse":
        args.extend(["--sse-url", identifier])
    else:
        raise ValueError(f"Invalid connection type: {connection_type}")
    
    # Add optional args
    if visualize_ansi:
        args.append("--visualize-ansi-codes")
    
    if guardrail_provider:
        args.extend(["--guardrail-provider", guardrail_provider])
    
    # Create server parameters
    server_params = StdioServerParameters(
        command="python",
        args=args,
        cwd=Path(__file__).parent.parent.parent.resolve(),
    )
    
    # Connect to the wrapper
    async with stdio_client(server_params) as (read, write):
        assert read is not None and write is not None
        async with ClientSession(read, write) as session:
            await session.initialize()
            await callback(session)
