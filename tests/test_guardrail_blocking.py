#!/usr/bin/env python3
"""
Tests for guardrail blocking functionality in MCP wrapper.
"""
import json
import os
import tempfile
import pytest
import logging
import subprocess
import io
import time
import asyncio
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from typing import Callable, Awaitable

# Configure path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import our modules
from mcp_config import MCPServerConfig, MCPToolDefinition, MCPParameterDefinition, ParameterType
from mcp_wrapper import MCPWrapperServer
from guardrails import get_provider, GuardrailAlert
from guardrail_providers import (
    AlwaysAlertGuardrailProvider,
    NeverAlertGuardrailProvider
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_guardrail_blocking")

# Path to the simple downstream server script
DOWNSTREAM_SERVER_PATH = Path(__file__).resolve().parent / "simple_downstream_server.py"

async def run_with_guardrail_provider(callback: Callable[[ClientSession], Awaitable[None]], 
                                config_path: str, provider_name: str):
    """
    Run a test with a wrapper that uses the specified guardrail provider.
    
    Args:
        callback: Async function that will be called with the client session
        config_path: Path to the configuration file
        provider_name: Name of the guardrail provider to use
    """
    dir = Path(__file__).resolve().parent
    server_params = StdioServerParameters(
        command="python",
        args=[
            str(Path(__file__).resolve().parent.parent.joinpath("mcp_wrapper.py")),
            "--command", f"python {str(dir.joinpath('simple_downstream_server.py'))}",
            "--config-file", str(config_path),
            "--guardrail-provider", provider_name
        ],
    )

    async with stdio_client(server_params) as (read, write):
        assert read is not None and write is not None
        async with ClientSession(read, write) as session:
            await session.initialize()
            await callback(session)

async def run_with_always_alert_guardrail(callback: Callable[[ClientSession], Awaitable[None]], config_path: str):
    """Run a test with a wrapper that uses the AlwaysAlertGuardrailProvider."""
    await run_with_guardrail_provider(callback, config_path, "Always Alert Provider")

async def run_with_never_alert_guardrail(callback: Callable[[ClientSession], Awaitable[None]], config_path: str):
    """Run a test with a wrapper that uses the NeverAlertGuardrailProvider."""
    await run_with_guardrail_provider(callback, config_path, "Never Alert Provider")

class TestGuardrailBlocking:
    """Tests for guardrail blocking functionality."""
    
    def setup_method(self):
        """Set up test by creating temp config file."""
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.config_path = self.temp_file.name
        logger.info(f"Created temp config file: {self.config_path}")
        
    def teardown_method(self):
        """Clean up after test."""
        os.unlink(self.config_path)
        logger.info(f"Removed temp config file: {self.config_path}")
        
    def run_child_process(self, provider_name):
        """Start a subprocess running the server with the given provider."""
        cmd = [
            sys.executable,
            "-c",
            f"""
import sys
import os
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, "{Path(__file__).resolve().parent.parent}")

# Import required modules
from mcp_wrapper import MCPWrapperServer
from guardrails import get_provider

provider = get_provider("{provider_name}")
assert provider is not None, "Provider {provider_name} not found"

# Create and run the wrapper
async def main():
    wrapper = MCPWrapperServer.wrap_stdio(
        "python {DOWNSTREAM_SERVER_PATH}",
        "{self.config_path}",
        provider
    )
    await wrapper.run()

asyncio.run(main())
"""
        ]
        
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
    
    def test_provider_loading(self):
        """Test that our test providers are available."""
        always_provider = get_provider("Always Alert Provider")
        never_provider = get_provider("Never Alert Provider")
        
        assert always_provider is not None, "Always Alert Provider not found"
        assert never_provider is not None, "Never Alert Provider not found"
        
        assert always_provider.name == "Always Alert Provider"
        assert never_provider.name == "Never Alert Provider"
        
        # Test always provider returns alert
        alert = always_provider.check_server_config(MCPServerConfig())
        assert alert is not None
        assert alert.explanation == "Security risk detected"
        
        # Test never provider returns None
        result = never_provider.check_server_config(MCPServerConfig())
        assert result is None

    def test_guardrail_alert_class(self):
        """Test creating and manipulating guardrail alerts."""
        from guardrails import GuardrailAlert
        
        alert = GuardrailAlert(
            explanation="Test alert", 
            data={"key1": "value1", "key2": 42}
        )
        
        assert alert.explanation == "Test alert"
        assert alert.data == {"key1": "value1", "key2": 42}
        
        # Test with empty data
        alert2 = GuardrailAlert(explanation="Empty data test")
        assert alert2.data == {}
        
    def test_direct_provider_usage(self):
        """Test using providers directly with the MCPWrapperServer."""
        # Create config
        config = MCPServerConfig()
        
        # Test with always alert provider
        always_provider = AlwaysAlertGuardrailProvider("Direct test alert")
        wrapper = MCPWrapperServer(
            config_path=self.config_path,
            guardrail_provider=always_provider
        )
        
        # Verify guardrails flag is set correctly
        assert wrapper.use_guardrails is True
        assert wrapper.guardrail_provider is always_provider
        assert wrapper.guardrail_alert is None  # No alert yet
        
        # Create a server config and trigger an alert check
        wrapper.current_config = MCPServerConfig()
        wrapper.guardrail_alert = wrapper.guardrail_provider.check_server_config(wrapper.current_config)
        
        # Verify alert is set
        assert wrapper.guardrail_alert is not None
        assert wrapper.guardrail_alert.explanation == "Direct test alert"
        
        # Test with never alert provider
        never_provider = NeverAlertGuardrailProvider()
        wrapper = MCPWrapperServer(
            config_path=self.config_path,
            guardrail_provider=never_provider
        )
        
        # Verify guardrails flag is set correctly
        assert wrapper.use_guardrails is True
        assert wrapper.guardrail_provider is never_provider
        
        # Create a server config and trigger an alert check
        wrapper.current_config = MCPServerConfig()
        wrapper.guardrail_alert = wrapper.guardrail_provider.check_server_config(wrapper.current_config)
        
        # Verify no alert is set
        assert wrapper.guardrail_alert is None
    
    def test_approve_server_config_with_guardrail_alert(self):
        """Test that approve_server_config fails when guardrail alert is active."""
        # Create a wrapper with an always-alert provider
        alert_text = "Security risk test alert"
        always_provider = AlwaysAlertGuardrailProvider(alert_text)
        wrapper = MCPWrapperServer(
            config_path=self.config_path,
            guardrail_provider=always_provider
        )
        
        # Create and set a server config
        config = MCPServerConfig()
        tool = MCPToolDefinition(
            name="test_tool",
            description="Test tool",
            parameters=[
                MCPParameterDefinition(
                    name="param1",
                    description="Test param",
                    type=ParameterType.STRING,
                    required=True
                )
            ]
        )
        config.add_tool(tool)
        wrapper.current_config = config
        
        # Trigger guardrail alert
        wrapper.guardrail_alert = wrapper.guardrail_provider.check_server_config(config)
        assert wrapper.guardrail_alert is not None
        assert wrapper.guardrail_alert.explanation == alert_text
        
        # Try to approve the config
        async def test_approval():
            result = await wrapper._handle_approve_config(config.to_json())
            return result
            
        import asyncio
        approval_result = asyncio.run(test_approval())
        approval_json = json.loads(approval_result)
        
        # Verify approval was blocked
        assert approval_json["status"] == "failed"
        assert "guardrail_alert" in approval_json
        assert approval_json["guardrail_alert"]["explanation"] == alert_text
    
    @pytest.mark.asyncio
    async def test_ignore_guardrail_alert_with_exact_match(self):
        """Test that ignore_guardrail_alert works with exact match."""
        async def callback(session):
            # List available tools
            tools = await session.list_tools()
            
            # Tool names should include ignore_guardrail_alert
            tool_names = [t.name for t in tools.tools]
            assert "approve_server_config" in tool_names
            assert "ignore_guardrail_alert" in tool_names
            assert "echo" in tool_names
            
            # Try to use echo - it should be blocked with an alert
            result = await session.call_tool("echo", {"message": "test"})
            assert len(result.content) == 1
            blocked_response = json.loads(result.content[0].text)
            assert blocked_response["status"] == "blocked"
            assert "guardrail_alert" in blocked_response
            
            # Get the alert text
            alert_text = blocked_response["guardrail_alert"]["explanation"]
            
            # Try to ignore the alert with the exact text
            ignore_result = await session.call_tool(
                "ignore_guardrail_alert", 
                {"alert_text": alert_text}
            )
            
            # Check the response
            response_text = ignore_result.content[0].text
            response_json = json.loads(response_text)
            
            # Verify alert was ignored
            assert response_json["status"] == "success"
            
            # Now try the echo tool again - it should work after ignoring alert
            # and approving config
            approval_result = await session.call_tool(
                "approve_server_config", 
                {"config": blocked_response["server_config"]}
            )
            approval_json = json.loads(approval_result.content[0].text)
            assert approval_json["status"] == "success"
            
            # Now echo should work
            echo_result = await session.call_tool("echo", {"message": "test after ignore"})
            echo_json = json.loads(echo_result.content[0].text)
            assert echo_json["status"] == "completed"
            
        await run_with_always_alert_guardrail(callback, self.config_path)
    
    @pytest.mark.asyncio
    async def test_ignore_guardrail_alert_with_mismatch(self):
        """Test that ignore_guardrail_alert fails with text mismatch."""
        async def callback(session):
            # List available tools
            tools = await session.list_tools()
            
            # Tool names should include ignore_guardrail_alert
            tool_names = [t.name for t in tools.tools]
            assert "approve_server_config" in tool_names
            assert "ignore_guardrail_alert" in tool_names
            assert "echo" in tool_names
            
            # Try to use echo - it should be blocked with an alert
            result = await session.call_tool("echo", {"message": "test"})
            assert len(result.content) == 1
            blocked_response = json.loads(result.content[0].text)
            assert blocked_response["status"] == "blocked"
            assert "guardrail_alert" in blocked_response
            
            # Try to ignore the alert with wrong text
            ignore_result = await session.call_tool(
                "ignore_guardrail_alert", 
                {"alert_text": "Wrong alert text"}
            )
            
            # Check the response
            response_text = ignore_result.content[0].text
            response_json = json.loads(response_text)
            
            # Verify alert was not ignored
            assert response_json["status"] == "failed"
            assert "provided_alert" in response_json
            assert response_json["provided_alert"] == "Wrong alert text"
            
            # Try to call echo tool again - should still be blocked
            echo_result = await session.call_tool("echo", {"message": "test after failed ignore"})
            echo_json = json.loads(echo_result.content[0].text)
            assert echo_json["status"] == "blocked"
            assert "guardrail_alert" in echo_json
            
        await run_with_always_alert_guardrail(callback, self.config_path)
    
    @pytest.mark.asyncio
    async def test_tool_blocking_with_always_alert_provider(self):
        """Test that tools are blocked when guardrail alert is active."""
        async def callback(session):
            # Try to use echo - it should be blocked with an alert
            result = await session.call_tool("echo", {"message": "test"})
            assert len(result.content) == 1
            blocked_response = json.loads(result.content[0].text)
            
            # Verify tool was blocked
            assert blocked_response["status"] == "blocked"
            assert "guardrail_alert" in blocked_response
            assert blocked_response["guardrail_alert"]["provider"] == "Always Alert Provider"
            
            # Try approving config without clearing alert - should fail
            approval_result = await session.call_tool(
                "approve_server_config", 
                {"config": blocked_response["server_config"]}
            )
            approval_json = json.loads(approval_result.content[0].text)
            
            # Verify approval was blocked
            assert approval_json["status"] == "failed"
            assert "guardrail_alert" in approval_json
            
            # Now ignore the alert with the correct text
            alert_text = blocked_response["guardrail_alert"]["explanation"]
            ignore_result = await session.call_tool(
                "ignore_guardrail_alert",
                {"alert_text": alert_text}
            )
            ignore_json = json.loads(ignore_result.content[0].text)
            assert ignore_json["status"] == "success"
            
            # Now we should be able to approve the config
            approval_result = await session.call_tool(
                "approve_server_config", 
                {"config": blocked_response["server_config"]}
            )
            approval_json = json.loads(approval_result.content[0].text)
            assert approval_json["status"] == "success"
            
            # Now echo should work
            echo_result = await session.call_tool("echo", {"message": "test after ignore"})
            echo_json = json.loads(echo_result.content[0].text)
            assert echo_json["status"] == "completed"
        
        await run_with_always_alert_guardrail(callback, self.config_path)
        
    @pytest.mark.asyncio
    async def test_tool_with_never_alert_provider(self):
        """Test that tools work normally with a provider that never alerts."""
        async def callback(session):
            # List available tools
            tools = await session.list_tools()
            
            # Tool names should include ignore_guardrail_alert (it's always there when guardrails enabled)
            tool_names = [t.name for t in tools.tools]
            assert "approve_server_config" in tool_names
            assert "ignore_guardrail_alert" in tool_names
            assert "echo" in tool_names
            
            # Tool is still blocked because config is not approved, but there should be no guardrail alert
            result = await session.call_tool("echo", {"message": "test"})
            assert len(result.content) == 1
            blocked_response = json.loads(result.content[0].text)
            assert blocked_response["status"] == "blocked"
            assert "guardrail_alert" not in blocked_response
            
            # Approve config - should work immediately since there's no alert
            approval_result = await session.call_tool(
                "approve_server_config", 
                {"config": blocked_response["server_config"]}
            )
            approval_json = json.loads(approval_result.content[0].text)
            assert approval_json["status"] == "success"
            
            # Now echo should work
            echo_result = await session.call_tool("echo", {"message": "test after approval"})
            echo_json = json.loads(echo_result.content[0].text)
            assert echo_json["status"] == "completed"
        
        await run_with_never_alert_guardrail(callback, self.config_path)

if __name__ == "__main__":
    pytest.main(["-v", __file__])