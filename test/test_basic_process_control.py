"""Basic tests for process control and cleanup.

This module tests that child processes are properly managed
when the wrapper process is terminated.
"""

import contextlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil
import pytest


class TestBasicProcessControl:
    """Test basic process startup and termination."""

    def test_wrapper_starts_and_can_be_terminated(self) -> None:
        """Test that wrapper starts successfully and can be terminated."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            # Start wrapper process using regular subprocess
            downstream_server = Path(__file__).parent / "simple_downstream_server.py"
            wrapper_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "contextprotector",
                    "--command",
                    f"python {downstream_server}",
                    "--server-config-file",
                    config_file.name,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=Path(__file__).parent.parent.resolve(),
            )

            # Give wrapper time to start
            time.sleep(2.0)

            # Check wrapper is running
            assert wrapper_process.poll() is None, "Wrapper exited unexpectedly"

            # Get child processes
            child_pids = self._get_child_processes(wrapper_process.pid)
            assert len(child_pids) > 0, "No child processes found"

            # Terminate wrapper
            wrapper_process.terminate()

            # Wait for wrapper to exit
            try:
                wrapper_process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                wrapper_process.kill()
                wrapper_process.wait()

            # Give time for cleanup
            time.sleep(1.0)

            # Check child processes are cleaned up
            remaining_children = []
            for pid in child_pids:
                if self._is_process_running(pid):
                    remaining_children.append(pid)
                    # Clean up for test hygiene
                    try:
                        import os
                        import signal

                        os.kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        pass

            assert len(remaining_children) == 0, (
                f"Child processes not cleaned up: {remaining_children}"
            )

        finally:
            Path(config_file.name).unlink(missing_ok=True)

    def test_wrapper_with_invalid_command_exits_cleanly(self) -> None:
        """Test wrapper with invalid command exits without orphans."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            # Start wrapper with invalid command
            wrapper_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "contextprotector",
                    "--command",
                    "nonexistent_command_12345",
                    "--server-config-file",
                    config_file.name,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=Path(__file__).parent.parent.resolve(),
            )

            # Wait for wrapper to exit (should fail quickly)
            return_code = wrapper_process.wait(timeout=10.0)

            # Should have exited with error
            assert return_code != 0, "Expected wrapper to exit with error code"

            # Should not have left any child processes
            child_pids = self._get_child_processes(wrapper_process.pid)

            # Clean up any orphans
            for pid in child_pids:
                if self._is_process_running(pid):
                    try:
                        import os
                        import signal

                        os.kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        pass

            assert len(child_pids) == 0, f"Unexpected child processes: {child_pids}"

        finally:
            Path(config_file.name).unlink(missing_ok=True)

    def test_wrapper_terminate_cleans_up_children(self) -> None:
        """Test that SIGTERM allows wrapper to clean up child processes gracefully."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            # Start wrapper process
            downstream_server = Path(__file__).parent / "simple_downstream_server.py"
            wrapper_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "contextprotector",
                    "--command",
                    f"python {downstream_server}",
                    "--server-config-file",
                    config_file.name,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=Path(__file__).parent.parent.resolve(),
            )

            # Give wrapper time to start
            time.sleep(2.0)

            # Check wrapper is running
            assert wrapper_process.poll() is None, "Wrapper exited unexpectedly"

            # Get child processes
            child_pids = self._get_child_processes(wrapper_process.pid)
            assert len(child_pids) > 0, "No child processes found"

            # Send SIGTERM (graceful termination)
            wrapper_process.terminate()

            # Wait for wrapper to exit
            wrapper_process.wait(timeout=5.0)

            # Check child cleanup with polling
            cleanup_complete = False
            for _ in range(30):  # 3 seconds of polling
                remaining = [pid for pid in child_pids if self._is_process_running(pid)]
                if not remaining:
                    cleanup_complete = True
                    break
                time.sleep(0.1)

            # Clean up any remaining processes for test hygiene
            final_remaining = [pid for pid in child_pids if self._is_process_running(pid)]
            for pid in final_remaining:
                try:
                    import os
                    import signal as sig

                    os.kill(pid, sig.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass

            assert cleanup_complete, f"Child processes not cleaned up: {final_remaining}"

        finally:
            Path(config_file.name).unlink(missing_ok=True)

    def test_rapid_start_stop_cycles(self) -> None:
        """Test rapid start/stop cycles don't leave orphans."""
        for cycle in range(3):
            config_file = tempfile.NamedTemporaryFile(delete=False)
            config_file.close()

            try:
                # Start wrapper
                downstream_server = Path(__file__).parent / "simple_downstream_server.py"
                wrapper_process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "contextprotector",
                        "--command",
                        f"python {downstream_server}",
                        "--server-config-file",
                        config_file.name,
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=Path(__file__).parent.parent.resolve(),
                )

                # Brief startup time
                time.sleep(1.0)

                # Get children and terminate quickly
                child_pids = self._get_child_processes(wrapper_process.pid)
                wrapper_process.terminate()
                wrapper_process.wait(timeout=5.0)

                # Allow cleanup time
                time.sleep(0.5)

                # Verify cleanup
                remaining = [pid for pid in child_pids if self._is_process_running(pid)]

                # Force cleanup for test hygiene
                for pid in remaining:
                    try:
                        import os
                        import signal

                        os.kill(pid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        pass

                assert len(remaining) == 0, f"Cycle {cycle}: orphaned processes {remaining}"

            finally:
                Path(config_file.name).unlink(missing_ok=True)

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


class TestClientDisconnection:
    """Test client disconnection scenarios."""

    def _get_child_processes(self, parent_pid: int) -> list[int]:
        """Get list of child process PIDs."""
        try:
            import psutil

            parent = psutil.Process(parent_pid)
            children = parent.children(recursive=True)
            return [child.pid for child in children]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []

    def _is_process_running(self, pid: int) -> bool:
        """Check if process is still running."""
        try:
            import psutil

            return psutil.pid_exists(pid)
        except ImportError:
            try:
                import os

                os.kill(pid, 0)
                return True
            except (ProcessLookupError, OSError):
                return False

    def test_wrapper_shuts_down_on_stdin_eof(self) -> None:
        """Test that wrapper shuts down gracefully when stdin receives EOF."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            # Start wrapper
            downstream_server = Path(__file__).parent / "simple_downstream_server.py"
            wrapper_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "contextprotector",
                    "--command",
                    f"python {downstream_server}",
                    "--server-config-file",
                    config_file.name,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=Path(__file__).parent.parent.resolve(),
            )

            # Wait for startup
            time.sleep(2.0)
            assert wrapper_process.poll() is None, "Wrapper exited during startup"

            # Get child processes before disconnection
            child_pids = self._get_child_processes(wrapper_process.pid)
            assert len(child_pids) > 0, "No child processes found"

            # Send EOF by closing stdin
            wrapper_process.stdin.close()

            # Wrapper should exit gracefully within reasonable time
            return_code = wrapper_process.wait(timeout=10.0)

            # Should exit cleanly (not from signal)
            assert return_code == 0, f"Expected clean exit, got {return_code}"

            # Child processes should be cleaned up
            time.sleep(1.0)  # Brief delay for cleanup
            remaining_children = [pid for pid in child_pids if self._is_process_running(pid)]

            if remaining_children:
                # Clean up any remaining processes
                for pid in remaining_children:
                    with contextlib.suppress(ProcessLookupError, OSError):
                        import os
                        import signal

                        os.kill(pid, signal.SIGKILL)

                pytest.fail(f"Child processes not cleaned up: {remaining_children}")

        finally:
            Path(config_file.name).unlink(missing_ok=True)

    def test_wrapper_shuts_down_on_client_disconnect_with_messages(self) -> None:
        """Test wrapper shutdown when client disconnects after sending messages."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            # Start wrapper
            downstream_server = Path(__file__).parent / "simple_downstream_server.py"
            wrapper_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "contextprotector",
                    "--command",
                    f"python {downstream_server}",
                    "--server-config-file",
                    config_file.name,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=Path(__file__).parent.parent.resolve(),
                text=True,
                bufsize=0,
            )

            # Wait for startup
            time.sleep(2.0)
            assert wrapper_process.poll() is None, "Wrapper exited during startup"

            # Get child processes before disconnection
            child_pids = self._get_child_processes(wrapper_process.pid)
            assert len(child_pids) > 0, "No child processes found"

            # Send initialize message to establish connection
            init_msg = {
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": 1,
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                },
            }

            wrapper_process.stdin.write(json.dumps(init_msg) + "\n")
            wrapper_process.stdin.flush()

            # Brief delay to let initialization complete
            time.sleep(1.0)

            # Now close stdin to simulate client disconnection
            wrapper_process.stdin.close()

            # Wrapper should exit gracefully
            return_code = wrapper_process.wait(timeout=10.0)
            assert return_code == 0, f"Expected clean exit, got {return_code}"

            # Child processes should be cleaned up
            time.sleep(1.0)
            remaining_children = [pid for pid in child_pids if self._is_process_running(pid)]

            if remaining_children:
                # Clean up any remaining processes
                for pid in remaining_children:
                    with contextlib.suppress(ProcessLookupError, OSError):
                        import os
                        import signal

                        os.kill(pid, signal.SIGKILL)

                pytest.fail(f"Child processes not cleaned up: {remaining_children}")

        finally:
            Path(config_file.name).unlink(missing_ok=True)

    def test_wrapper_handles_stdout_write_failure_gracefully(self) -> None:
        """Test wrapper handles stdout write failures gracefully when client disconnects."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            # Start wrapper
            downstream_server = Path(__file__).parent / "simple_downstream_server.py"
            wrapper_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "contextprotector",
                    "--command",
                    f"python {downstream_server}",
                    "--server-config-file",
                    config_file.name,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=Path(__file__).parent.parent.resolve(),
                text=True,
                bufsize=0,
            )

            # Wait for startup
            time.sleep(2.0)
            assert wrapper_process.poll() is None, "Wrapper exited during startup"

            # Get child processes before disconnection
            child_pids = self._get_child_processes(wrapper_process.pid)
            assert len(child_pids) > 0, "No child processes found"

            # Send initialize message to establish connection
            init_msg = {
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": 1,
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                },
            }

            wrapper_process.stdin.write(json.dumps(init_msg) + "\n")
            wrapper_process.stdin.flush()

            # Give time for initialization
            time.sleep(1.0)

            # Send a tools/list request that will generate a response
            tools_msg = {"jsonrpc": "2.0", "method": "tools/list", "id": 2, "params": {}}

            wrapper_process.stdin.write(json.dumps(tools_msg) + "\n")
            wrapper_process.stdin.flush()

            # Immediately close stdout pipe to simulate client disconnection
            # This should cause the wrapper's write to fail
            wrapper_process.stdout.close()

            # Also close stdin to signal disconnection
            wrapper_process.stdin.close()

            # Wrapper should exit within reasonable time despite the stdout write failure
            return_code = wrapper_process.wait(timeout=10.0)

            # Currently, the wrapper exits with error code when stdout write fails
            # This is expected behavior - writing to closed pipe causes I/O error
            # The important thing is that it exits promptly and cleans up children
            assert return_code != 0, f"Expected non-zero exit (I/O error), got {return_code}"

            # Child processes should be cleaned up
            time.sleep(1.0)  # Brief delay for cleanup
            remaining_children = [pid for pid in child_pids if self._is_process_running(pid)]

            if remaining_children:
                # Clean up any remaining processes
                for pid in remaining_children:
                    with contextlib.suppress(ProcessLookupError, OSError):
                        import os
                        import signal

                        os.kill(pid, signal.SIGKILL)

                pytest.fail(f"Child processes not cleaned up: {remaining_children}")

        finally:
            Path(config_file.name).unlink(missing_ok=True)


class TestSignalDelivery:
    """Test signal delivery without asyncio complications."""

    def test_sigterm_delivered_to_wrapper(self) -> None:
        """Test that SIGTERM is properly delivered to wrapper process."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()

        try:
            # Start wrapper
            downstream_server = Path(__file__).parent / "simple_downstream_server.py"
            wrapper_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "contextprotector",
                    "--command",
                    f"python {downstream_server}",
                    "--server-config-file",
                    config_file.name,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=Path(__file__).parent.parent.resolve(),
            )

            # Wait for startup
            time.sleep(2.0)
            assert wrapper_process.poll() is None, "Wrapper exited during startup"

            # Send SIGTERM
            import os
            import signal

            os.kill(wrapper_process.pid, signal.SIGTERM)

            # Wrapper should exit within reasonable time
            try:
                wrapper_process.wait(timeout=5.0)
                # Any return code is fine as long as it exits
            except subprocess.TimeoutExpired:
                # If it doesn't respond to SIGTERM, kill it
                wrapper_process.kill()
                wrapper_process.wait()
                pytest.fail("Wrapper did not respond to SIGTERM within timeout")

        finally:
            Path(config_file.name).unlink(missing_ok=True)
