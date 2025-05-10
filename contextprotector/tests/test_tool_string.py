#!/usr/bin/env python3
"""
Test for the MCPToolDefinition.__str__ method.
"""

from ..mcp_config import MCPToolDefinition, MCPParameterDefinition, ParameterType


def test_tool_str():
    """Test that the string representation of a tool is formatted correctly."""
    # Create a tool with some parameters
    tool = MCPToolDefinition(
        name="test_tool",
        description="A test tool for testing the __str__ method",
        parameters=[
            MCPParameterDefinition(
                name="required_param",
                description="A required parameter",
                type=ParameterType.STRING,
                required=True,
            ),
            MCPParameterDefinition(
                name="optional_param",
                description="An optional parameter",
                type=ParameterType.NUMBER,
                required=False,
                default=42,
            ),
            MCPParameterDefinition(
                name="enum_param",
                description="A parameter with enum values",
                type=ParameterType.STRING,
                required=True,
                enum=["value1", "value2", "value3"],
            ),
        ],
    )

    # Get the string representation
    tool_str = str(tool)

    # Check that it contains all the expected information
    assert "Tool: test_tool" in tool_str
    assert "Description: A test tool for testing the __str__ method" in tool_str
    assert "Parameters:" in tool_str
    assert "required_param (string) (required): A required parameter" in tool_str
    assert (
        "optional_param (number) (optional): An optional parameter [Default: 42]"
        in tool_str
    )
    assert (
        "enum_param (string) (required): A parameter with enum values [Values: value1, value2, value3]"
        in tool_str
    )

    # Test a tool with no parameters
    empty_tool = MCPToolDefinition(
        name="empty_tool",
        description="A tool with no parameters",
        parameters=[],
    )

    empty_tool_str = str(empty_tool)

    assert "Tool: empty_tool" in empty_tool_str
    assert "Description: A tool with no parameters" in empty_tool_str
    assert "Parameters: None" in empty_tool_str


if __name__ == "__main__":
    # This allows the test to be run as a standalone script
    # and still use the proper import paths
    import sys
    import os

    # Add parent directory to path so imports work correctly
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from ..mcp_config import MCPToolDefinition, MCPParameterDefinition, ParameterType

    # Run the test
    test_tool_str()
    print("All tests passed!")
