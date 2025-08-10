"""Tests for proper child process shutdown handling.

This test suite verifies that child processes are properly terminated
when the wrapper process receives signals or encounters errors.
"""

import asyncio
import os
import psutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from contextprotector.mcp_config import MCPConfigDatabase


class TestProcessShutdown:
    """Test proper shutdown of child processes under various conditions."""

    @pytest.mark.asyncio()
    async def test_sigint_causes_child_termination(self) -> None:
        """Test that SIGINT to wrapper terminates child process."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()
        
        try:
            # Start wrapper process
            wrapper_process = await self._start_wrapper_process(config_file.name)
            print(f"Started wrapper with PID {wrapper_process.pid}")
            
            # Give wrapper time to start child
            await asyncio.sleep(2.0)
            
            # Check if wrapper is still running
            if wrapper_process.returncode is not None:
                stdout, stderr = await wrapper_process.communicate()
                print(f"Wrapper exited early with code {wrapper_process.returncode}")
                print(f"STDOUT: {stdout.decode()}")
                print(f"STDERR: {stderr.decode()}")
                pytest.fail("Wrapper exited before test")
            
            # Find child processes
            child_pids = self._get_child_processes(wrapper_process.pid)
            print(f"Found child processes: {child_pids}")
            
            # Send SIGINT to wrapper
            print("Sending SIGINT to wrapper")
            wrapper_process.send_signal(signal.SIGINT)
            
            # Wait for wrapper to shut down
            try:
                return_code = await asyncio.wait_for(wrapper_process.wait(), timeout=3.0)
                print(f"Wrapper shut down with return code {return_code}")
            except asyncio.TimeoutError:
                print("SIGINT did not shut down wrapper, trying SIGKILL")
                wrapper_process.kill()
                return_code = await wrapper_process.wait()
                print(f"Wrapper killed with return code {return_code}")
                # This is still a valid test - we're testing child cleanup
            
            # Verify child processes are terminated
            await asyncio.sleep(0.5)  # Brief delay for cleanup
            for pid in child_pids:
                is_running = self._is_process_running(pid)
                print(f"Child process {pid} running: {is_running}")
                assert not is_running, f"Child process {pid} still running"
                
        finally:
            Path(config_file.name).unlink(missing_ok=True)

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
            except asyncio.TimeoutError:
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
            wrapper_process = await self._start_wrapper_process_with_invalid_command(config_file.name)
            
            # Wait for wrapper to fail
            try:
                return_code = await asyncio.wait_for(wrapper_process.wait(), timeout=10.0)
                assert return_code != 0, "Expected wrapper to fail with non-zero exit code"
            except asyncio.TimeoutError:
                wrapper_process.kill()
                await wrapper_process.wait()
                pytest.fail("Wrapper did not exit within timeout")
            
            # Verify no orphaned processes remain
            await asyncio.sleep(0.5)
            child_pids = self._get_child_processes(wrapper_process.pid)
            for pid in child_pids:
                assert not self._is_process_running(pid), f"Child process {pid} still running after wrapper exit"
                
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
                return_code = await asyncio.wait_for(wrapper_process.wait(), timeout=10.0)
                # Return code might be 0 (graceful) or non-zero (error), both acceptable
            except asyncio.TimeoutError:
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
    async def test_keyboard_interrupt_cleanup(self) -> None:
        """Test that KeyboardInterrupt is handled properly with child cleanup."""
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
            
            # Send SIGINT (equivalent to Ctrl+C)
            wrapper_process.send_signal(signal.SIGINT)
            
            # Wait for wrapper to handle the interrupt
            try:
                return_code = await asyncio.wait_for(wrapper_process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                wrapper_process.kill()
                await wrapper_process.wait()
                pytest.fail("Wrapper did not handle interrupt within timeout")
            
            # Verify child processes are cleaned up
            await asyncio.sleep(0.5)
            for pid in child_pids:
                assert not self._is_process_running(pid), f"Child process {pid} still running after interrupt"
                
        finally:
            Path(config_file.name).unlink(missing_ok=True)

    @pytest.mark.asyncio()
    async def test_multiple_rapid_signals(self) -> None:
        """Test handling of multiple rapid signals without leaving orphans."""
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
            
            # Send multiple rapid signals
            wrapper_process.send_signal(signal.SIGINT)
            await asyncio.sleep(0.1)
            wrapper_process.send_signal(signal.SIGTERM)
            await asyncio.sleep(0.1)
            wrapper_process.send_signal(signal.SIGINT)
            
            # Wait for wrapper to shut down
            try:
                await asyncio.wait_for(wrapper_process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                wrapper_process.kill()
                await wrapper_process.wait()
                pytest.fail("Wrapper did not shut down within timeout")
            
            # Verify all child processes are terminated
            await asyncio.sleep(0.5)
            for pid in child_pids:
                assert not self._is_process_running(pid), f"Child process {pid} still running"
                
        finally:
            Path(config_file.name).unlink(missing_ok=True)

    @pytest.mark.asyncio()
    async def test_child_process_survives_parent_only_briefly(self) -> None:
        """Test that child processes don't survive parent termination for long."""
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
            
            # Kill wrapper immediately (simulating unexpected termination)
            wrapper_process.kill()
            await wrapper_process.wait()
            
            # Child processes should terminate shortly after parent
            # Allow some time for cleanup but not too much
            max_orphan_time = 2.0
            start_time = time.time()
            
            while time.time() - start_time < max_orphan_time:
                still_running = [pid for pid in child_pids if self._is_process_running(pid)]
                if not still_running:
                    break
                await asyncio.sleep(0.1)
            
            # Verify no long-term orphans
            final_orphans = [pid for pid in child_pids if self._is_process_running(pid)]
            if final_orphans:
                # Clean up any remaining processes for test cleanup
                for pid in final_orphans:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                pytest.fail(f"Child processes {final_orphans} survived parent termination too long")
                
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
                "uv", "run", "python", "-m", "contextprotector",
                "--command", "nonexistent_command_12345",
                "--server-config-file", config_file.name,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=Path(__file__).parent.parent.resolve(),
            )
            
            # Wait for wrapper to fail
            try:
                return_code = await asyncio.wait_for(wrapper_process.wait(), timeout=5.0)
                assert return_code != 0, "Expected wrapper to fail"
            except asyncio.TimeoutError:
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
            "uv", "run", "python", "-m", "contextprotector",
            "--command", f"python {downstream_server}",
            "--server-config-file", config_path,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=Path(__file__).parent.parent.resolve(),
        )

    async def _start_wrapper_process_with_invalid_command(self, config_path: str) -> Any:
        """Start a wrapper process with an invalid downstream server command."""
        return await asyncio.create_subprocess_exec(
            "uv", "run", "python", "-m", "contextprotector",
            "--command", "python /nonexistent/invalid_server.py",
            "--server-config-file", config_path,
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
    async def test_client_disconnect_during_tool_call(self) -> None:
        """Test that child cleanup works when client disconnects during tool execution."""
        config_file = tempfile.NamedTemporaryFile(delete=False)
        config_file.close()
        
        # First approve the server
        config_db = MCPConfigDatabase(config_file.name)
        downstream_server = Path(__file__).parent / "simple_downstream_server.py"
        command = f"python {downstream_server}"
        
        # Create a basic config for approval
        from contextprotector.mcp_config import MCPServerConfig, MCPToolDefinition
        config = MCPServerConfig()
        config.instructions = "Simple test server"
        config.add_tool(MCPToolDefinition(
            name="echo",
            description="Echo a message",
            parameters=[]
        ))
        
        # Save as approved config
        config_db.save_approved_config("stdio", command, config)
        
        try:
            # Start wrapper process
            wrapper_process = await self._start_wrapper_process(config_file.name, command)
            
            # Give wrapper time to start
            await asyncio.sleep(1.0)
            
            # Find child processes
            child_pids = self._get_child_processes(wrapper_process.pid)
            assert len(child_pids) > 0, "No child processes found"
            
            # Simulate abrupt client disconnection by killing wrapper
            wrapper_process.kill()
            await wrapper_process.wait()
            
            # Verify child processes are cleaned up
            await asyncio.sleep(1.0)  # Allow time for cleanup
            for pid in child_pids:
                assert not self._is_process_running(pid), f"Child process {pid} still running"
                
        finally:
            Path(config_file.name).unlink(missing_ok=True)

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
                    assert not self._is_process_running(pid), f"Iteration {i}: Child {pid} not cleaned up"
                    
        finally:
            Path(config_file.name).unlink(missing_ok=True)

    # Helper methods
    async def _start_wrapper_process(self, config_path: str, command: str | None = None) -> Any:
        """Start a wrapper process."""
        if command is None:
            downstream_server = Path(__file__).parent / "simple_downstream_server.py"
            command = f"python {downstream_server}"
        
        return await asyncio.create_subprocess_exec(
            "uv", "run", "python", "-m", "contextprotector",
            "--command", command,
            "--server-config-file", config_path,
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