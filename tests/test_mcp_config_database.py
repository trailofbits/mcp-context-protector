"""
Tests for the MCPConfigDatabase class.
"""
import os
import tempfile
import json
import pytest
from pathlib import Path

from ..mcp_config import (
    MCPServerConfig, 
    MCPToolDefinition, 
    MCPParameterDefinition, 
    ParameterType, 
    MCPConfigDatabase
)


def test_config_database_save_load():
    """Test saving and loading configurations from the database."""
    # Create a temporary file for the config database
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        config_path = temp_file.name
    
    try:
        # Create a test config database
        db = MCPConfigDatabase(config_path)
        
        # Create a sample tool config
        echo_config = MCPServerConfig()
        echo_config.instructions = "This is a test server for echoing messages."
        
        # Add a parameter for the echo tool
        echo_param = MCPParameterDefinition(
            name="message",
            description="The message to echo back",
            type=ParameterType.STRING,
            required=True
        )
        
        # Add an echo tool
        echo_tool = MCPToolDefinition(
            name="echo",
            description="Echoes back the input message",
            parameters=[echo_param]
        )
        
        echo_config.add_tool(echo_tool)
        
        # Add a calculator tool
        calc_config = MCPServerConfig()
        calc_config.instructions = "This is a calculator server for performing arithmetic operations."
        
        # Add parameters for the calculator tool
        a_param = MCPParameterDefinition(
            name="a",
            description="First number",
            type=ParameterType.NUMBER,
            required=True
        )
        
        b_param = MCPParameterDefinition(
            name="b",
            description="Second number",
            type=ParameterType.NUMBER,
            required=True
        )
        
        op_param = MCPParameterDefinition(
            name="operation",
            description="Operation to perform",
            type=ParameterType.STRING,
            required=True,
            enum=["add", "subtract", "multiply", "divide"]
        )
        
        # Add the calculator tool
        calc_tool = MCPToolDefinition(
            name="calculator",
            description="Performs basic arithmetic operations",
            parameters=[a_param, b_param, op_param]
        )
        
        calc_config.add_tool(calc_tool)
        
        # Save configurations to the database
        stdio_command = "python /path/to/stdio_server.py"
        sse_url = "http://localhost:8080/sse"
        
        db.save_server_config("stdio", stdio_command, echo_config)
        db.save_server_config("sse", sse_url, calc_config)
        
        # Create a new database instance to load from disk
        db2 = MCPConfigDatabase(config_path)
        
        # Check if configurations were saved and loaded correctly
        echo_loaded = db2.get_server_config("stdio", stdio_command)
        calc_loaded = db2.get_server_config("sse", sse_url)
        
        # Verify the echo config
        assert echo_loaded is not None
        assert len(echo_loaded.tools) == 1
        assert echo_loaded.tools[0].name == "echo"
        assert len(echo_loaded.tools[0].parameters) == 1
        assert echo_loaded.tools[0].parameters[0].name == "message"
        assert echo_loaded.instructions == "This is a test server for echoing messages."
        
        # Verify the calculator config
        assert calc_loaded is not None
        assert len(calc_loaded.tools) == 1
        assert calc_loaded.tools[0].name == "calculator"
        assert len(calc_loaded.tools[0].parameters) == 3
        assert calc_loaded.instructions == "This is a calculator server for performing arithmetic operations."
        
        # Check tool listing
        servers = db2.list_servers()
        assert len(servers) == 2
        
        # Find the stdio server
        stdio_server = next((s for s in servers if s['type'] == 'stdio'), None)
        assert stdio_server is not None
        assert stdio_server['identifier'] == stdio_command
        assert stdio_server['has_config'] is True
        
        # Find the sse server
        sse_server = next((s for s in servers if s['type'] == 'sse'), None)
        assert sse_server is not None
        assert sse_server['identifier'] == sse_url
        assert sse_server['has_config'] is True
        
    finally:
        # Clean up
        if os.path.exists(config_path):
            os.unlink(config_path)

def test_config_database_removes_server():
    """Test removing a server configuration from the database."""
    # Create a temporary file for the config database
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        config_path = temp_file.name
    
    try:
        # Create a test config database
        db = MCPConfigDatabase(config_path)
        
        # Create a sample config
        config = MCPServerConfig()
        tool = MCPToolDefinition(
            name="test",
            description="Test tool",
            parameters=[]
        )
        config.add_tool(tool)
        
        # Save configuration
        server1 = "server1"
        server2 = "server2"
        db.save_server_config("stdio", server1, config)
        db.save_server_config("stdio", server2, config)
        
        # Verify both servers exist
        servers = db.list_servers()
        assert len(servers) == 2
        
        # Remove one server
        result = db.remove_server_config("stdio", server1)
        assert result is True
        
        # Verify only one server remains
        servers = db.list_servers()
        assert len(servers) == 1
        assert servers[0]['identifier'] == server2
        
        # Try to remove a non-existent server
        result = db.remove_server_config("stdio", "non_existent")
        assert result is False
        
    finally:
        # Clean up
        if os.path.exists(config_path):
            os.unlink(config_path)

def test_config_database_file_structure():
    """Test the structure of the config database file."""
    # Create a temporary file for the config database
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        config_path = temp_file.name
    
    try:
        # Create a test config database
        db = MCPConfigDatabase(config_path)
        
        # Create a sample config
        config = MCPServerConfig()
        tool = MCPToolDefinition(
            name="test",
            description="Test tool",
            parameters=[]
        )
        config.add_tool(tool)
        
        # Save configuration
        server_id = "test_server"
        db.save_server_config("stdio", server_id, config)
        
        # Read the file directly to check its structure
        with open(config_path, 'r') as f:
            data = json.load(f)
        
        # Verify the structure
        assert "servers" in data
        assert isinstance(data["servers"], list)
        assert len(data["servers"]) == 1
        
        server = data["servers"][0]
        assert "type" in server
        assert server["type"] == "stdio"
        assert "identifier" in server
        assert server["identifier"] == server_id
        assert "config" in server
        assert "tools" in server["config"]
        
    finally:
        # Clean up
        if os.path.exists(config_path):
            os.unlink(config_path)


def test_config_instructions_comparison():
    """Test that changes in instructions are detected in configuration comparison."""
    # Create two configs with the same tools but different instructions
    config1 = MCPServerConfig()
    config1.instructions = "Original instructions"
    
    tool = MCPToolDefinition(
        name="test",
        description="Test tool",
        parameters=[]
    )
    config1.add_tool(tool)
    
    # Clone the config but change the instructions
    config2 = MCPServerConfig()
    config2.instructions = "New instructions"
    config2.add_tool(tool)  # Same tool
    
    # Compare the configs
    diff = config1.compare(config2)
    
    # Verify the difference is detected
    assert diff.has_differences()
    assert diff.new_instructions == "New instructions"
    
    # No tool differences
    assert not diff.added_tools
    assert not diff.removed_tools
    assert not diff.modified_tools
    
    # Verify equality operator
    assert config1 != config2
    
    # Make instructions match and verify configs are now equal
    config2.instructions = "Original instructions"
    assert config1 == config2


def test_config_database_default_path():
    """Test that the default config path is in the expected location."""
    # Get the default path
    default_path = MCPConfigDatabase.get_default_config_path()
    
    # Check that it's in the .context-protector directory
    expected_dir = Path.home() / ".context-protector"
    assert Path(default_path).parent == expected_dir
    
    # Check the filename
    assert Path(default_path).name == "servers.json"