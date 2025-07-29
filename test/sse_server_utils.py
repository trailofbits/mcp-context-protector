"""
Shared utilities for managing SSE test servers.

This module provides common functionality for starting and stopping SSE servers
in test environments, eliminating code duplication across test files.
"""

import asyncio
import logging
import subprocess
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import psutil
import pytest
import pytest_asyncio


class SSEServerManager:
    """Manages the lifecycle of an SSE server process for testing."""

    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.port: int | None = None
        self.pid: int | None = None

    def get_ports_by_pid(self, pid: int) -> list[int]:
        """
        Finds and returns a list of ports opened by a process ID.

        Args:
            pid: The process ID.

        Returns:
            A list of port numbers or an empty list if no ports are found.
        """
        try:
            process = psutil.Process(pid)
            connections = process.net_connections()
            ports = []
            for conn in connections:
                if conn.status == "LISTEN":
                    ports.append(conn.laddr.port)
            return ports
        except psutil.NoSuchProcess:
            logging.warning("Process with PID %d not found.", pid)
            return []
        except psutil.AccessDenied:
            logging.warning("Access denied to process with PID %d.", pid)
            return []

    async def start_server(self) -> subprocess.Popen:
        """Start the SSE downstream server in a separate process."""
        # Get the path to the server script
        server_script = str(Path(__file__).resolve().parent.joinpath("simple_sse_server.py"))

        # Start the server process
        self.process = await asyncio.create_subprocess_exec(
            sys.executable,
            server_script,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Get the PID directly from the process object
        self.pid = self.process.pid
        logging.warning("SSE Server started with PID: %d", self.pid)

        # Give the server time to start
        await asyncio.sleep(1.0)

        # Find which port the server is listening on
        max_attempts = 5
        for attempt in range(max_attempts):
            ports = self.get_ports_by_pid(self.pid)
            if ports:
                self.port = ports[0]  # Use the first port found
                logging.warning("SSE Server is listening on port: %d", self.port)
                break

            logging.warning(
                "Attempt %d/%d: No ports found for PID %d, waiting...", attempt + 1, max_attempts, self.pid
            )
            await asyncio.sleep(1.0)

        assert self.port is not None, "Could not determine port for SSE server"
        return self.process

    async def stop_server(self) -> None:
        """Stop the SSE downstream server process."""
        if self.process:
            self.process.terminate()
            await asyncio.sleep(0.5)

            # Make sure it's really gone
            if self.process.returncode is None:
                self.process.kill()

            self.process = None
            self.port = None
            self.pid = None


# Global instance for backward compatibility with existing tests
_global_manager = SSEServerManager()

# Global variables for backward compatibility
SERVER_PROCESS = None
SERVER_PORT = None
SERVER_PID = None


def get_ports_by_pid(pid: int) -> list[int]:
    """Global function for backward compatibility."""
    return _global_manager.get_ports_by_pid(pid)


async def start_sse_server() -> subprocess.Popen:
    """Global function for backward compatibility."""
    global SERVER_PROCESS, SERVER_PORT, SERVER_PID

    process = await _global_manager.start_server()
    SERVER_PROCESS = _global_manager.process
    SERVER_PORT = _global_manager.port
    SERVER_PID = _global_manager.pid

    return process


async def stop_sse_server() -> None:
    """Global function for backward compatibility."""
    global SERVER_PROCESS, SERVER_PORT, SERVER_PID

    await _global_manager.stop_server()
    SERVER_PROCESS = None
    SERVER_PORT = None
    SERVER_PID = None


@pytest_asyncio.fixture
async def sse_server_fixture() -> AsyncGenerator[subprocess.Popen, None]:
    """Fixture to manage the SSE server lifecycle."""
    process = await start_sse_server()
    yield process
    await stop_sse_server()


@pytest_asyncio.fixture
async def sse_server() -> AsyncGenerator[subprocess.Popen, None]:
    """Alternative fixture name for backward compatibility."""
    process = await start_sse_server()
    yield process
    await stop_sse_server()
