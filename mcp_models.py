#!/usr/bin/env python3
"""
Model classes for MCP tool specifications.
Contains the data structures needed for representing MCP tools and related concepts.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Callable


@dataclass
class MCPToolSpec:
    """Specification for a tool that can be used by a model."""
    name: str
    description: str
    parameters: Dict[str, Any]
    required: List[str]

    def model_dump(self) -> Dict[str, Any]:
        """Convert to a dictionary representation."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "required": self.required,
        }


@dataclass
class MCPToolUse:
    """Represents a request to use a tool."""
    name: str
    parameters: Dict[str, Any]


@dataclass
class MCPToolUseResult:
    """Represents the result of using a tool."""
    result: str


class MCPToolError(Exception):
    """Exception raised when a tool call fails."""
    pass


class MCPClient:
    """Client for connecting to an MCP server."""

    def __init__(self, url: str):
        self.url = url
        self.tool_specs = []
        self.tool_list_callbacks = []

    async def get_tool_specs(self) -> List[MCPToolSpec]:
        """Get tool specifications from the server."""
        return self.tool_specs

    async def use_tool(self, tool_use: MCPToolUse) -> MCPToolUseResult:
        """Use a tool on the server."""
        # This implementation should be overridden by actual clients
        raise NotImplementedError("This method must be implemented by concrete classes")

    def on_tool_list_update(self, callback: Callable) -> None:
        """Register a callback for tool list updates."""
        self.tool_list_callbacks.append(callback)

    async def register_for_notifications(self) -> None:
        """Register for notifications."""
        # This implementation should be overridden by actual clients
        raise NotImplementedError("This method must be implemented by concrete classes")


class MCPServer:
    """Server that handles MCP requests."""

    def __init__(self, handler):
        self.handler = handler