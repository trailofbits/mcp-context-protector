"""
Utility functions for MCP wrapper tests.
"""

import asyncio
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

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
        "--server-config-file",
        config_path,
    ]

    if connection_type == "stdio":
        cmd.extend(["--command", identifier])
    elif connection_type == "http":
        cmd.extend(["--url", identifier])
    elif connection_type == "sse":
        cmd.extend(["--sse-url", identifier])
    else:
        error_msg = f"Invalid connection type: {connection_type}"
        raise ValueError(error_msg)

    # Run the review process
    review_process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=Path(__file__).parent.parent.parent.resolve(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for the review process to start
    await asyncio.sleep(1.5)

    # Send 'y' to approve the configuration
    review_process.stdin.write(b"y\n")
    await review_process.stdin.drain()

    # Wait for the review process to complete
    stdout, stderr = await review_process.communicate()

    # Verify the review process output
    assert review_process.returncode == 0, (
        f"Review process failed with return code {review_process.returncode}: {stderr}"
    )

    # Check for expected output in the review process
    assert b"has been trusted and saved" in stdout, (
        f"Missing expected approval message in output: {stdout}"
    )


def _wrapper_args(
    connection_type: Literal["stdio", "http", "sse"], identifier: str, config_path: str
) -> list[str]:
    # Base arguments
    args = [
        "-m",
        "contextprotector",
        "--server-config-file",
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
        error_msg = f"Invalid connection type: {connection_type}"
        raise ValueError(error_msg)

    return args


async def run_with_wrapper_session(
    callback: Callable[[ClientSession], Awaitable[None]],
    connection_type: Literal["stdio", "http", "sse"],
    identifier: str,
    config_path: str,
) -> None:
    """
    Run a test with a wrapper that connects to the specified downstream server.

    Args:
        callback: Async function to call with the client session
        connection_type: Type of connection ("stdio", "http", or "sse")
        identifier: The command or URL to connect to the downstream server
        config_path: Path to the wrapper config file
    """
    args = _wrapper_args(connection_type, identifier, config_path)

    # Create server parameters
    server_params = StdioServerParameters(
        command="python",
        args=args,
        cwd=Path(__file__).parent.parent.parent.resolve(),
    )

    # Connect to the wrapper
    async with stdio_client(server_params) as (read, write):
        assert read is not None
        assert write is not None
        async with ClientSession(read, write) as session:
            await session.initialize()
            await callback(session)


async def run_with_wrapper_session_visualize_ansi(
    callback: Callable[[ClientSession], Awaitable[None]],
    connection_type: Literal["stdio", "http", "sse"],
    identifier: str,
    config_path: str,
) -> None:
    """
    Run a test with a wrapper that connects to the specified downstream server.

    Args:
        callback: Async function to call with the client session
        connection_type: Type of connection ("stdio", "http", or "sse")
        identifier: The command or URL to connect to the downstream server
        config_path: Path to the wrapper config file
    """
    args = _wrapper_args(connection_type, identifier, config_path)
    args.append("--visualize-ansi-codes")

    # Create server parameters
    server_params = StdioServerParameters(
        command="python",
        args=args,
        cwd=Path(__file__).parent.parent.parent.resolve(),
    )

    # Connect to the wrapper
    async with stdio_client(server_params) as (read, write):
        assert read is not None
        assert write is not None
        async with ClientSession(read, write) as session:
            await session.initialize()
            await callback(session)


async def run_with_simple_downstream_server(
    callback: Callable[[ClientSession], Awaitable[None]], config_path: str | None = None
) -> None:
    """
    Run a test with a wrapper session that connects to the simple downstream server.

    This is a convenience function that wraps the generic run_with_wrapper_session
    to specifically use the simple_downstream_server.py test server.

    Args:
        callback: Async function to call with the client session
        config_path: Optional path to the wrapper config file
    """
    from contextprotector.mcp_config import MCPServerConfig

    config_path = config_path or MCPServerConfig.get_default_config_path()
    parent_dir = Path(__file__).resolve().parent
    command = f"python {parent_dir.joinpath('simple_downstream_server.py')!s}"

    await run_with_wrapper_session(callback, "stdio", command, config_path)


async def run_with_sse_downstream_server(
    callback: Callable[[ClientSession], Awaitable[None]],
    server_port: int,
    config_path: str | None = None,
) -> None:
    """
    Run a test with a wrapper session that connects to an SSE downstream server.

    This is a convenience function that wraps the generic run_with_wrapper_session
    to specifically connect to an SSE server at the given port.

    Args:
        callback: Async function to call with the client session
        server_port: Port number where the SSE server is running
        config_path: Optional path to the wrapper config file
    """
    from contextprotector.mcp_config import MCPServerConfig

    config_path = config_path or MCPServerConfig.get_default_config_path()
    sse_url = f"http://localhost:{server_port}/sse"

    await run_with_wrapper_session(callback, "sse", sse_url, config_path)
