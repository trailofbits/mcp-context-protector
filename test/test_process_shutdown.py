"""Tests for proper child process shutdown handling.

This test suite verifies that child processes are properly terminated
when the wrapper process receives signals or encounters errors.
"""

import asyncio
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import psutil
import pytest


class TestProcessShutdown:
    """Test proper shutdown of child processes under various conditions."""

    @pytest.mark.asyncio()
    async def test_sigterm_causes_child_termination(self) -> None:
        """Test that SIGTERM to wrapper terminates child process."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            # Start wrapper process
            wrapper_process = await self._start_wrapper_process(config_file.name)

            # Give wrapper time to start child
            await asyncio.sleep(1.0)

            # Find child processes
            child_pids = self._get_child_processes(wrapper_process.pid)
            assert len(child_pids) > 0, "No child processes found"

            # Send SIGTERM to wrapper
            wrapper_process.send_signal(signal.SIGTERM)

            # Wait for wrapper to shut down
            try:
                await asyncio.wait_for(wrapper_process.wait(), timeout=5.0)
            except TimeoutError:
                wrapper_process.kill()
                await wrapper_process.wait()
                pytest.fail("Wrapper did not shut down within timeout")

            # Verify child processes are terminated
            await asyncio.sleep(0.5)  # Brief delay for cleanup
            for pid in child_pids:
                assert not self._is_process_running(pid), f"Child process {pid} still running"

        finally:
            Path(config_file.name).unlink(missing_ok=True)

    @pytest.mark.asyncio()
    async def test_wrapper_exception_terminates_children(self) -> None:
        """Test that wrapper exceptions don't leave orphaned child processes."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            # Start wrapper with invalid downstream server to trigger error
            wrapper_process = await self._start_wrapper_process_with_invalid_command(
                config_file.name
            )

            # Wait for wrapper to fail
            try:
                return_code = await asyncio.wait_for(wrapper_process.wait(), timeout=10.0)
                assert return_code != 0, "Expected wrapper to fail with non-zero exit code"
            except TimeoutError:
                wrapper_process.kill()
                await wrapper_process.wait()
                pytest.fail("Wrapper did not exit within timeout")

            # Verify no orphaned processes remain
            await asyncio.sleep(0.5)
            child_pids = self._get_child_processes(wrapper_process.pid)
            for pid in child_pids:
                assert not self._is_process_running(pid), (
                    f"Child process {pid} still running after wrapper exit"
                )

        finally:
            Path(config_file.name).unlink(missing_ok=True)

    @pytest.mark.asyncio()
    async def test_graceful_shutdown_via_stdin_closure(self) -> None:
        """Test that closing stdin causes graceful shutdown."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            # Start wrapper process
            wrapper_process = await self._start_wrapper_process(config_file.name)

            # Give wrapper time to start child
            await asyncio.sleep(1.0)

            # Find child processes
            child_pids = self._get_child_processes(wrapper_process.pid)
            assert len(child_pids) > 0, "No child processes found"

            # Close stdin to simulate client disconnection
            wrapper_process.stdin.close()

            # Wait for wrapper to shut down gracefully
            try:
                await asyncio.wait_for(wrapper_process.wait(), timeout=10.0)
                # Return code might be 0 (graceful) or non-zero (error), both acceptable
            except TimeoutError:
                wrapper_process.kill()
                await wrapper_process.wait()
                pytest.fail("Wrapper did not shut down within timeout")

            # Verify child processes are terminated
            await asyncio.sleep(0.5)
            for pid in child_pids:
                assert not self._is_process_running(pid), f"Child process {pid} still running"

        finally:
            Path(config_file.name).unlink(missing_ok=True)

    @pytest.mark.asyncio()
    async def test_wrapper_connection_error_cleanup(self) -> None:
        """Test cleanup when wrapper fails to connect to downstream server."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            # Start wrapper with non-existent command
            wrapper_process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "contextprotector",
                "--command",
                "nonexistent_command_12345",
                "--server-config-file",
                config_file.name,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=Path(__file__).parent.parent.resolve(),
            )

            # Wait for wrapper to fail
            try:
                return_code = await asyncio.wait_for(wrapper_process.wait(), timeout=5.0)
                assert return_code != 0, "Expected wrapper to fail"
            except TimeoutError:
                wrapper_process.kill()
                await wrapper_process.wait()
                pytest.fail("Wrapper did not exit within timeout")

            # Should not have left any orphaned processes
            await asyncio.sleep(0.5)
            child_pids = self._get_child_processes(wrapper_process.pid)
            for pid in child_pids:
                assert not self._is_process_running(pid), f"Orphaned process {pid} found"

        finally:
            Path(config_file.name).unlink(missing_ok=True)

    # Helper methods

    async def _start_wrapper_process(self, config_path: str) -> Any:
        """Start a wrapper process with a simple downstream server."""
        downstream_server = Path(__file__).parent / "simple_downstream_server.py"

        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "contextprotector",
            "--command",
            f"python {downstream_server}",
            "--server-config-file",
            config_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=Path(__file__).parent.parent.resolve(),
        )

    async def _start_wrapper_process_with_invalid_command(self, config_path: str) -> Any:
        """Start a wrapper process with an invalid downstream server command."""
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "contextprotector",
            "--command",
            "python /nonexistent/invalid_server.py",
            "--server-config-file",
            config_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=Path(__file__).parent.parent.resolve(),
        )

    def _get_child_processes(self, parent_pid: int) -> list[int]:
        """Get list of child process PIDs for a given parent PID."""
        try:
            parent = psutil.Process(parent_pid)
            children = parent.children(recursive=True)
            return [child.pid for child in children]
        except psutil.NoSuchProcess:
            return []

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is still running."""
        try:
            return psutil.pid_exists(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False


class TestProcessCleanupIntegration:
    """Integration tests for process cleanup in real scenarios."""

    @pytest.mark.asyncio()
    async def test_rapid_wrapper_restart_no_port_conflicts(self) -> None:
        """Test that rapid wrapper restarts don't leave processes that conflict."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            for i in range(3):  # Test multiple rapid starts/stops
                wrapper_process = await self._start_wrapper_process(config_file.name)

                # Give wrapper minimal time to start
                await asyncio.sleep(0.5)

                # Get child PIDs
                child_pids = self._get_child_processes(wrapper_process.pid)

                # Stop wrapper
                wrapper_process.terminate()
                await asyncio.wait_for(wrapper_process.wait(), timeout=3.0)

                # Verify cleanup before next iteration
                await asyncio.sleep(0.5)
                for pid in child_pids:
                    assert not self._is_process_running(pid), (
                        f"Iteration {i}: Child {pid} not cleaned up"
                    )

        finally:
            Path(config_file.name).unlink(missing_ok=True)

    # Helper methods
    async def _start_wrapper_process(self, config_path: str, command: str | None = None) -> Any:
        """Start a wrapper process."""
        if command is None:
            downstream_server = Path(__file__).parent / "simple_downstream_server.py"
            command = f"python {downstream_server}"

        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "contextprotector",
            "--command",
            command,
            "--server-config-file",
            config_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=Path(__file__).parent.parent.resolve(),
        )

    def _get_child_processes(self, parent_pid: int) -> list[int]:
        """Get list of child process PIDs for a given parent PID."""
        try:
            parent = psutil.Process(parent_pid)
            children = parent.children(recursive=True)
            return [child.pid for child in children]
        except psutil.NoSuchProcess:
            return []

    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is still running."""
        try:
            return psutil.pid_exists(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
