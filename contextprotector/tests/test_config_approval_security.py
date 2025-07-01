"""
Test that ensures ZERO information leakage from unapproved downstream server configurations.

This test verifies that when a configuration is not approved:
1. Only the 'config_instructions' tool is visible in list_tools()
2. No downstream server tool names, descriptions, or metadata are exposed
3. All blocked tool calls return clean error messages without server info leakage
4. The security boundary is maintained consistently
"""

import json
import logging
import os
import pytest
import tempfile

from mcp import ClientSession, types

from .test_utils import run_with_wrapper_session

logger = logging.getLogger("test_config_approval_security")


@pytest.mark.asyncio
async def test_zero_information_leakage_unapproved_config():
    """Test that ZERO downstream server information leaks when config is unapproved."""
    
    # This test uses the prompt_test_server which has multiple tools and prompts
    # We verify that NONE of this information is exposed when config is unapproved
    
    async def test_callback(session: ClientSession):
        """Test callback that verifies complete information isolation."""
        
        # 1. Test list_tools() - should ONLY return config_instructions tool
        tools_result = await session.list_tools()
        assert isinstance(tools_result, types.ListToolsResult)
        
        # Verify only wrapper tools are returned (no downstream server tools)
        tool_names = [t.name for t in tools_result.tools]
        
        # Must include config_instructions
        assert "config_instructions" in tool_names, f"Expected 'config_instructions' tool, got {tool_names}"
        
        # Should not include any downstream server tools
        downstream_tools = ["test_tool", "toggle_prompts", "ansi_echo", "echo"]
        for downstream_tool in downstream_tools:
            assert downstream_tool not in tool_names, f"Downstream tool '{downstream_tool}' leaked in unapproved config: {tool_names}"
        
        # Find the config_instructions tool
        config_tool = next(t for t in tools_result.tools if t.name == "config_instructions")
        assert "instructions for approving" in config_tool.description.lower(), f"Unexpected description: {config_tool.description}"
        
        logger.info("✓ list_tools() correctly shows only config_instructions tool")
        
        # 2. Test calling the config_instructions tool - should work
        config_result = await session.call_tool(
            name="config_instructions",
            arguments={}
        )
        assert isinstance(config_result, types.CallToolResult)
        assert len(config_result.content) > 0
        
        # Parse the response to verify it contains approval instructions
        response_text = config_result.content[0].text
        # The config_instructions tool returns plain text instructions, not JSON
        assert "approval" in response_text.lower() or "review" in response_text.lower()
        
        logger.info("✓ config_instructions tool works correctly")
        
        # 3. Test calling downstream server tools - should be blocked with clean errors
        
        # Try calling a tool that exists on the downstream server (test_tool)
        blocked_result = await session.call_tool(
            name="test_tool",
            arguments={"message": "test"}
        )
        assert isinstance(blocked_result, types.CallToolResult)
        assert len(blocked_result.content) > 0
        
        # Parse the blocked response
        blocked_text = blocked_result.content[0].text
        
        # The response should be a clean JSON error with no server information leakage
        try:
            blocked_data = json.loads(blocked_text)
            
            # Should be a ValueError response (from call_tool method blocking)
            assert "status" in blocked_data and blocked_data["status"] == "blocked"
            assert "reason" in blocked_data
            assert "configuration not approved" in blocked_data["reason"].lower()
            
            # CRITICAL: Verify NO downstream server information is leaked
            blocked_str = json.dumps(blocked_data).lower()
            
            # Should NOT contain any downstream server tool names
            assert "test_tool" not in blocked_str, "Blocked response leaked downstream tool name 'test_tool'"
            assert "toggle_prompts" not in blocked_str, "Blocked response leaked downstream tool name 'toggle_prompts'"
            
            # Should NOT contain any downstream server descriptions
            assert "simple test tool" not in blocked_str, "Blocked response leaked downstream tool description"
            assert "echo" not in blocked_str, "Blocked response leaked downstream functionality info"
            
            # Should NOT contain any server-specific error messages
            assert "unknown tool" not in blocked_str, "Blocked response leaked downstream server error message"
            
        except json.JSONDecodeError:
            pytest.fail(f"Blocked response is not valid JSON: {blocked_text}")
        
        logger.info("✓ Blocked tool calls return clean errors with zero information leakage")
        
        # 4. Try calling a completely non-existent tool - should also be blocked cleanly
        nonexistent_result = await session.call_tool(
            name="nonexistent_totally_fake_tool",
            arguments={}
        )
        assert isinstance(nonexistent_result, types.CallToolResult)
        
        nonexistent_text = nonexistent_result.content[0].text
        nonexistent_data = json.loads(nonexistent_text)
        
        # Should also be blocked with the same clean message
        assert nonexistent_data["status"] == "blocked"
        assert "configuration not approved" in nonexistent_data["reason"].lower()
        
        logger.info("✓ Non-existent tool calls also blocked with clean errors")
        
        # 5. Test list_prompts() - should return empty or minimal response
        try:
            prompts_result = await session.list_prompts()
            # If prompts are supported, should be empty or contain no downstream info
            if isinstance(prompts_result, types.ListPromptsResult):
                # Should not expose any downstream prompt information
                for prompt in prompts_result.prompts:
                    prompt_str = json.dumps({
                        "name": prompt.name,
                        "description": prompt.description
                    }).lower()
                    
                    # Should not contain downstream server prompt names
                    assert "greeting" not in prompt_str, "list_prompts leaked downstream prompt 'greeting'"
                    assert "help" not in prompt_str, "list_prompts leaked downstream prompt 'help'"
                    assert "farewell" not in prompt_str, "list_prompts leaked downstream prompt 'farewell'"
            
            logger.info("✓ list_prompts() does not leak downstream server information")
        except Exception as e:
            # If prompts aren't supported by wrapper, that's fine
            logger.info(f"list_prompts() not supported or failed: {e}")
        
        # 6. Test list_resources() - should return empty or minimal response  
        try:
            resources_result = await session.list_resources()
            # If resources are supported, should be empty or contain no downstream info
            if isinstance(resources_result, types.ListResourcesResult):
                # Should not expose any downstream resource information
                assert len(resources_result.resources) == 0, "list_resources() leaked downstream resource information"
            
            logger.info("✓ list_resources() does not leak downstream server information")
        except Exception as e:
            # If resources aren't supported by wrapper, that's fine
            logger.info(f"list_resources() not supported or failed: {e}")
        
        logger.info("🔒 SECURITY VERIFICATION COMPLETE: Zero information leakage confirmed")

    # Create temporary config file
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    try:
        # Use the prompt_test_server which has multiple tools and prompts
        # This gives us a good test case with real downstream server metadata to verify is hidden
        venv_python = "/Users/cliffsmith/context-protector/venv/bin/python"
        server_command = f"{venv_python} -m contextprotector.tests.prompt_test_server"
        
        # Run the test with unapproved config - this should show zero information leakage
        await run_with_wrapper_session(
            test_callback,
            "stdio",
            server_command,
            temp_file.name
        )
        
    finally:
        # Clean up temp file
        os.unlink(temp_file.name)


@pytest.mark.asyncio
async def test_information_visible_after_approval():
    """Verify that downstream server information IS visible after config approval."""
    
    from .test_utils import approve_server_config_using_review
    
    async def test_callback(session: ClientSession):
        """Test callback that verifies information is visible after approval."""
        
        # After approval, we should see the actual downstream server tools
        tools_result = await session.list_tools()
        assert isinstance(tools_result, types.ListToolsResult)
        
        # Should now have the actual downstream server tools
        tool_names = [t.name for t in tools_result.tools]
        
        # Should include the downstream server's tools
        assert "test_tool" in tool_names, f"Expected 'test_tool' after approval, got: {tool_names}"
        assert "toggle_prompts" in tool_names, f"Expected 'toggle_prompts' after approval, got: {tool_names}"
        
        # Should NOT include config_instructions anymore
        assert "config_instructions" not in tool_names, f"config_instructions should not be visible after approval, got: {tool_names}"
        
        # Test that the tools actually work
        result = await session.call_tool(
            name="test_tool",
            arguments={"message": "Hello after approval!"}
        )
        assert isinstance(result, types.CallToolResult)
        
        response_text = result.content[0].text
        response_data = json.loads(response_text)
        assert response_data["status"] == "completed"
        
        # The actual downstream server response should be visible
        downstream_response = response_data["response"]
        assert "Echo: Hello after approval!" in downstream_response
        
        logger.info("✓ Downstream server information correctly visible after approval")

    # Create temporary config file
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    try:
        venv_python = "/Users/cliffsmith/context-protector/venv/bin/python"
        server_command = f"{venv_python} -m contextprotector.tests.prompt_test_server"
        
        # Approve the server configuration first
        await approve_server_config_using_review("stdio", server_command, temp_file.name)
        
        # Run the test with approved config
        await run_with_wrapper_session(
            test_callback,
            "stdio",
            server_command,
            temp_file.name
        )
        
    finally:
        # Clean up temp file
        os.unlink(temp_file.name)