"""Simplified tests for child process cleanup.

Tests that verify child processes are properly terminated when
the wrapper process exits under various conditions.
"""

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import psutil
import pytest


class TestProcessCleanupSimple:
    """Simplified tests for child process cleanup."""

    @pytest.mark.asyncio()
    async def test_wrapper_exit_cleans_up_children(self) -> None:
        """Test that wrapper process exit results in child cleanup."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            # Start wrapper process
            downstream_server = Path(__file__).parent / "simple_downstream_server.py"
            wrapper_process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "contextprotector",
                "--command",
                f"python {downstream_server}",
                "--server-config-file",
                config_file.name,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=Path(__file__).parent.parent.resolve(),
            )

            # Give wrapper time to start and spawn children
            await asyncio.sleep(2.0)

            # Record child processes
            child_pids = self._get_child_processes(wrapper_process.pid)

            # Terminate wrapper (simulating various exit conditions)
            wrapper_process.terminate()

            # Wait for wrapper to exit
            try:
                await asyncio.wait_for(wrapper_process.wait(), timeout=5.0)
            except TimeoutError:
                wrapper_process.kill()
                await wrapper_process.wait()

            # Give time for cleanup
            await asyncio.sleep(1.0)

            # Check that child processes are gone
            remaining_children = [pid for pid in child_pids if self._is_process_running(pid)]

            # Clean up any remaining processes before assertion
            for pid in remaining_children:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)

            assert (
                len(remaining_children) == 0
            ), f"Child processes {remaining_children} not cleaned up"

        finally:
            Path(config_file.name).unlink(missing_ok=True)

    @pytest.mark.asyncio()
    async def test_wrapper_with_invalid_command_no_orphans(self) -> None:
        """Test that wrapper failure doesn't leave orphan processes."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            # Start wrapper with invalid command
            wrapper_process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "contextprotector",
                "--command",
                "nonexistent_command_xyz",
                "--server-config-file",
                config_file.name,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=Path(__file__).parent.parent.resolve(),
            )

            # Wait for wrapper to fail
            await asyncio.wait_for(wrapper_process.wait(), timeout=10.0)

            # Should not have spawned any long-lived processes
            child_pids = self._get_child_processes(wrapper_process.pid)

            # Clean up any orphans and fail if they exist
            for pid in child_pids:
                if self._is_process_running(pid):
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)

            assert (
                len(child_pids) == 0
            ), f"Unexpected child processes {child_pids} after wrapper failure"

        finally:
            Path(config_file.name).unlink(missing_ok=True)

    @pytest.mark.asyncio()
    async def test_multiple_wrapper_instances_no_conflicts(self) -> None:
        """Test that multiple wrapper instances can start/stop without conflicts."""
        config_files = []

        try:
            for i in range(3):
                config_file = tempfile.NamedTemporaryFile(delete=False)
                config_file.close()
                config_files.append(config_file.name)

                # Start wrapper
                downstream_server = Path(__file__).parent / "simple_downstream_server.py"
                wrapper_process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "contextprotector",
                    "--command",
                    f"python {downstream_server}",
                    "--server-config-file",
                    config_file.name,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=Path(__file__).parent.parent.resolve(),
                )

                # Give it a moment to start
                await asyncio.sleep(1.0)

                # Stop wrapper
                wrapper_process.terminate()
                await asyncio.wait_for(wrapper_process.wait(), timeout=5.0)

                # Give time for cleanup
                await asyncio.sleep(0.5)

                # Check for orphans
                child_pids = self._get_child_processes(wrapper_process.pid)
                for pid in child_pids:
                    if self._is_process_running(pid):
                        with contextlib.suppress(ProcessLookupError):
                            os.kill(pid, signal.SIGKILL)

                assert len(child_pids) == 0, f"Instance {i}: orphaned processes {child_pids}"

        finally:
            for config_file in config_files:
                Path(config_file).unlink(missing_ok=True)

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
