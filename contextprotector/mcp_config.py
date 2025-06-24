#!/usr/bin/env python3
import json
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
import pathlib
from typing import Any, Dict, List, Optional, Union, TextIO, Literal


class ParameterType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


@dataclass
class MCPToolSpec:
    """Specification for a tool that can be used by a model."""

    name: str
    description: str
    parameters: Dict[str, Any]
    required: List[str]
    output_schema: Optional[Dict[str, Any]] = None

    def model_dump(self) -> Dict[str, Any]:
        """Convert to a dictionary representation."""
        result = {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "required": self.required,
        }
        if self.output_schema is not None:
            result["output_schema"] = self.output_schema
        return result


@dataclass
class MCPParameterDefinition:
    name: str
    description: str
    type: ParameterType
    required: bool = True
    default: Optional[Any] = None
    enum: Optional[List[str]] = None
    items: Optional[Dict[str, Any]] = None  # For array types
    properties: Optional[Dict[str, Any]] = None  # For object types

    def __eq__(self, other):
        if not isinstance(other, MCPParameterDefinition):
            return False
        return (
            self.name == other.name
            and self.description == other.description
            and self.type == other.type
            and self.required == other.required
            and self.default == other.default
            and self.enum == other.enum
            and self.items == other.items
            and self.properties == other.properties
        )


@dataclass
class MCPToolDefinition:
    name: str
    description: str
    parameters: List[MCPParameterDefinition]
    output_schema: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        """
        Generate a string representation of the tool with its parameters.
        Format is compact with parameters on a single line each.
        """
        lines = [f"Tool: {self.name}"]
        lines.append(f"Description: {self.description}")

        if self.parameters:
            lines.append("Parameters:")
            for param in self.parameters:
                required = "(required)" if param.required else "(optional)"
                param_line = f"  - {param.name} ({param.type.value}) {required}: {param.description}"

                if param.enum:
                    param_line += f" [Values: {', '.join(str(v) for v in param.enum)}]"

                if param.default is not None:
                    param_line += f" [Default: {param.default}]"

                lines.append(param_line)
        else:
            lines.append("Parameters: None")

        if self.output_schema is not None:
            lines.append(f"Output Schema: {json.dumps(self.output_schema, indent=2)}")

        return "\n".join(lines)

    def __eq__(self, other):
        if not isinstance(other, MCPToolDefinition):
            return False

        if self.name != other.name or self.description != other.description:
            return False

        if self.output_schema != other.output_schema:
            return False

        if len(self.parameters) != len(other.parameters):
            return False

        self_params = {param.name: param for param in self.parameters}
        other_params = {param.name: param for param in other.parameters}

        if set(self_params.keys()) != set(other_params.keys()):
            return False

        for name, param in self_params.items():
            if param != other_params[name]:
                return False

        return True


@dataclass
class ConfigDiff:
    """Class representing differences between two MCP server configurations."""

    old_instructions: Optional[str] = field(default=None)
    new_instructions: Optional[str] = field(default=None)
    added_tools: Dict[str, MCPToolDefinition] = field(default_factory=dict)
    added_tool_names: List[str] = field(default_factory=list)
    removed_tools: List[str] = field(default_factory=list)
    modified_tools: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def has_differences(self) -> bool:
        """Check if there are any differences."""
        return bool(
            self.old_instructions is not None
            or self.new_instructions is not None
            or self.added_tool_names
            or self.removed_tools
            or self.modified_tools
        )

    def __str__(self) -> str:
        """Generate a human-readable representation of the diff."""
        if not self.has_differences():
            return "No differences found."

        lines = []

        if self.old_instructions is not None or self.new_instructions is not None:
            lines.append("Instructions changed:")
            if self.old_instructions is not None:
                lines.append(f"  Old: {self.old_instructions}")
            if self.new_instructions is not None:
                lines.append(f"  New: {self.new_instructions}")
            lines.append("")

        if self.added_tool_names:
            lines.append("Added tools:")
            for tool_name in self.added_tool_names:
                lines.append(f"  + {tool_name}")
                lines.append("")
                lines.append(str(self.added_tools[tool_name]))
                lines.append("")
            lines.append("")

        if self.removed_tools:
            lines.append("Removed tools:")
            for tool_name in self.removed_tools:
                lines.append(f"  - {tool_name}")
            lines.append("")

        if self.modified_tools:
            lines.append("Modified tools:")
            for tool_name, changes in self.modified_tools.items():
                lines.append(f"  ~ {tool_name}:")

                if "description" in changes:
                    lines.append("    Description changed:")
                    lines.append(f"      - {changes['description']['old']}")
                    lines.append(f"      + {changes['description']['new']}")

                if "added_params" in changes and changes["added_params"]:
                    lines.append("    Added parameters:")
                    for param in changes["added_params"]:
                        lines.append(f"      + {param}")

                if "removed_params" in changes and changes["removed_params"]:
                    lines.append("    Removed parameters:")
                    for param in changes["removed_params"]:
                        lines.append(f"      - {param}")

                if "modified_params" in changes and changes["modified_params"]:
                    lines.append("    Modified parameters:")
                    for param_name, param_changes in changes["modified_params"].items():
                        lines.append(f"      ~ {param_name}:")
                        for field, values in param_changes.items():
                            lines.append(
                                f"        {field}: {values['old']} → {values['new']}"
                            )

        return "\n".join(lines)


@dataclass
class MCPServerConfig:
    """Class representing an MCP server configuration."""

    tools: List[MCPToolDefinition] = field(default_factory=list)
    instructions: str = field(default="")

    @classmethod
    def get_default_config_path(cls) -> str:
        """
        Get the default config path (~/.context-protector/config).

        Returns:
            The default config path as a string
        """
        home_dir = pathlib.Path.home()
        data_dir = home_dir / ".context-protector"

        data_dir.mkdir(exist_ok=True)

        return str(data_dir / "config")
    
    def add_tool(self, tool: Union[MCPToolDefinition, Dict[str, Any]]) -> None:
        """Add a tool to the server configuration.

        Args:
            tool: Either a MCPToolDefinition object or a dictionary with tool properties
        """
        if isinstance(tool, dict):
            parameters = []
            for param_data in tool.get("parameters", []):
                if isinstance(param_data, dict):
                    param = MCPParameterDefinition(
                        name=param_data.get("name", ""),
                        description=param_data.get("description", ""),
                        type=ParameterType(param_data.get("type", "string")),
                        required=param_data.get("required", True),
                    )
                    parameters.append(param)

            tool_obj = MCPToolDefinition(
                name=tool.get("name", ""),
                description=tool.get("description", ""),
                parameters=parameters,
            )
            self.tools.append(tool_obj)
        else:
            # It's already an MCPToolDefinition
            self.tools.append(tool)

    def remove_tool(self, tool_name: str) -> None:
        """Remove a tool from the server configuration by name."""
        self.tools = [tool for tool in self.tools if tool.name != tool_name]

    def get_tool(self, tool_name: str) -> Optional[MCPToolDefinition]:
        """Get a tool from the server configuration by name."""
        for tool in self.tools:
            if tool.name == tool_name:
                return tool
        return None

    def to_json(
        self, path: str = None, fp: TextIO = None, indent: int = 2
    ) -> Optional[str]:
        """
        Serialize the configuration to JSON.

        Args:
            path: Optional file path to write the JSON to
            fp: Optional file-like object to write the JSON to
            indent: Number of spaces for indentation (default: 2)

        Returns:
            JSON string if neither path nor fp is provided, None otherwise
        """
        config_dict = self.to_dict()
        json_str = json.dumps(config_dict, indent=indent)

        if path:
            with open(path, "w") as f:
                f.write(json_str)
            return None
        elif fp:
            fp.write(json_str)
            return None
        else:
            return json_str

    @classmethod
    def from_json(
        cls, json_str: str = None, path: str = None, fp: TextIO = None
    ) -> "MCPServerConfig":
        """
        Deserialize the configuration from JSON.

        Args:
            json_str: JSON string to parse
            path: Optional file path to read the JSON from
            fp: Optional file-like object to read the JSON from

        Returns:
            MCPServerConfig instance

        Raises:
            ValueError: If no source is provided or multiple sources are provided
        """
        if sum(x is not None for x in (json_str, path, fp)) != 1:
            raise ValueError("Exactly one of json_str, path, or fp must be provided")

        data = None
        if path:
            try:
                with open(path, "r") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.decoder.JSONDecodeError):
                pass
        elif fp:
            data = json.load(fp)
        else:
            data = json.loads(json_str)
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the server configuration to a dictionary."""
        return {
            "instructions": self.instructions,
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": [
                        {
                            "name": param.name,
                            "description": param.description,
                            "type": param.type.value,
                            "required": param.required,
                            **(
                                {"default": param.default}
                                if param.default is not None
                                else {}
                            ),
                            **({"enum": param.enum} if param.enum is not None else {}),
                            **(
                                {"items": param.items}
                                if param.items is not None
                                else {}
                            ),
                            **(
                                {"properties": param.properties}
                                if param.properties is not None
                                else {}
                            ),
                        }
                        for param in tool.parameters
                    ],
                }
                for tool in self.tools
            ],
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MCPServerConfig":
        """Create a server configuration from a dictionary."""
        config = cls()

        if data is None:
            return config

        config.instructions = data.get("instructions", "")

        for tool_data in data.get("tools", {}):
            parameters = []

            for param_data in tool_data.get("parameters", []):
                param = MCPParameterDefinition(
                    name=param_data["name"],
                    description=param_data["description"],
                    type=ParameterType(param_data["type"]),
                    required=param_data.get("required", True),
                    default=param_data.get("default"),
                    enum=param_data.get("enum"),
                    items=param_data.get("items"),
                    properties=param_data.get("properties"),
                )
                parameters.append(param)

            tool = MCPToolDefinition(
                name=tool_data["name"],
                description=tool_data["description"],
                parameters=parameters,
            )

            config.add_tool(tool)

        return config

    def __eq__(self, other) -> bool:
        """Compare two server configurations semantically."""
        if not isinstance(other, MCPServerConfig):
            return False

        if self.instructions != other.instructions:
            return False

        if len(self.tools) != len(other.tools):
            return False

        self_tools = {tool.name: tool for tool in self.tools}
        other_tools = {tool.name: tool for tool in other.tools}

        if set(self_tools.keys()) != set(other_tools.keys()):
            return False

        for name, tool in self_tools.items():
            if tool != other_tools[name]:
                return False

        return True

    def compare(self, other: "MCPServerConfig") -> ConfigDiff:
        """Compare two server configurations and return the differences."""
        diff = ConfigDiff()

        if self.instructions != other.instructions:
            diff.old_instructions = self.instructions
            diff.new_instructions = other.instructions

        self_tools = {tool.name: tool for tool in self.tools}
        other_tools = {tool.name: tool for tool in other.tools}

        self_tool_names = set(self_tools.keys())
        other_tool_names = set(other_tools.keys())

        diff.added_tool_names = list(other_tool_names - self_tool_names)
        diff.added_tools = {
            name: tool
            for (name, tool) in other_tools.items()
            if name in diff.added_tool_names
        }
        diff.removed_tools = list(self_tool_names - other_tool_names)

        common_tool_names = self_tool_names.intersection(other_tool_names)

        for tool_name in common_tool_names:
            self_tool = self_tools[tool_name]
            other_tool = other_tools[tool_name]

            if self_tool == other_tool:
                continue

            tool_changes = {}

            if self_tool.description != other_tool.description:
                tool_changes["description"] = {
                    "old": self_tool.description,
                    "new": other_tool.description,
                }

            self_params = {param.name: param for param in self_tool.parameters}
            other_params = {param.name: param for param in other_tool.parameters}

            self_param_names = set(self_params.keys())
            other_param_names = set(other_params.keys())

            added_params = list(other_param_names - self_param_names)
            removed_params = list(self_param_names - other_param_names)

            if added_params:
                tool_changes["added_params"] = added_params

            if removed_params:
                tool_changes["removed_params"] = removed_params

            # Find modified parameters
            common_param_names = self_param_names.intersection(other_param_names)
            modified_params = {}

            for param_name in common_param_names:
                self_param = self_params[param_name]
                other_param = other_params[param_name]

                if self_param == other_param:
                    continue

                param_changes = {}

                attrs = [
                    "description",
                    "type",
                    "required",
                    "default",
                    "enum",
                    "items",
                    "properties"
                ]

                # Check for parameter changes
                for attr_name in attrs:
                    self_val = getattr(self_param, attr_name, None)
                    other_val = getattr(other_param, attr_name, None)
                    
                    if self_val != other_val:
                        param_changes[attr_name] = {
                            "old": self_val,
                            "new": other_val,
                        }

                if param_changes:
                    modified_params[param_name] = param_changes

            if modified_params:
                tool_changes["modified_params"] = modified_params

            if tool_changes:
                diff.modified_tools[tool_name] = tool_changes

        return diff


@dataclass
class MCPServerEntry:
    """Class representing a server entry in the config database."""

    type: Literal["stdio", "http"]
    identifier: str  # URL for SSE servers, command for stdio servers
    config: Optional[Dict[str, Any]] = None  # Serialized MCPServerConfig

    @staticmethod
    def create_key(server_type: str, identifier: str) -> str:
        """Create a unique key for a server entry."""
        return f"{server_type}:{identifier}"

    @property
    def key(self) -> str:
        """Get the unique key for this server entry."""
        return self.create_key(self.type, self.identifier)


class MCPConfigDatabase:
    """
    Class for managing multiple server configurations in a single file.

    This database stores server configurations indexed by their type and identifier.
    It provides thread-safe access to the configuration file to prevent race conditions.
    """

    _file_lock = threading.RLock()  # Class-level lock for file operations

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the config database.

        Args:
            config_path: Path to the config file. If None, uses the default path.
        """
        self.config_path = config_path or self.get_default_config_path()
        self.servers = {}  # Dict[str, MCPServerEntry]
        self._load()

    @staticmethod
    def get_default_config_path() -> str:
        """
        Get the default config database path (~/.context-protector/servers.json).

        Returns:
            The default config path as a string
        """
        home_dir = pathlib.Path.home()
        data_dir = home_dir / ".context-protector"

        data_dir.mkdir(exist_ok=True)

        return str(data_dir / "servers.json")

    def _load(self) -> None:
        """Load server configurations from the config file."""
        with MCPConfigDatabase._file_lock:
            try:
                if os.path.exists(self.config_path):
                    with open(self.config_path, "r") as f:
                        data = json.load(f)
                        for server_data in data.get("servers", []):
                            entry = MCPServerEntry(
                                type=server_data.get("type"),
                                identifier=server_data.get("identifier"),
                                config=server_data.get("config"),
                            )
                            self.servers[entry.key] = entry
            except (json.JSONDecodeError, FileNotFoundError, ValueError):
                # If the file doesn't exist or is invalid, start with an empty database
                self.servers = {}

    def _save(self) -> None:
        """Save server configurations to the config file."""
        with MCPConfigDatabase._file_lock:
            data = {
                "servers": [
                    {
                        "type": entry.type,
                        "identifier": entry.identifier,
                        "config": entry.config,
                    }
                    for entry in self.servers.values()
                ]
            }

            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

            # Write to a temporary file first, then rename
            temp_path = f"{self.config_path}.tmp"
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2)

            # Atomically replace the old file with the new one
            os.replace(temp_path, self.config_path)

    def get_server_config(
        self, server_type: str, identifier: str
    ) -> Optional[MCPServerConfig]:
        """
        Get a server configuration by type and identifier.

        Args:
            server_type: The server type ('stdio' or 'sse')
            identifier: The server identifier (command or URL)

        Returns:
            The server configuration, or None if not found
        """
        key = MCPServerEntry.create_key(server_type, identifier)
        entry = self.servers.get(key)

        if entry and entry.config:
            return MCPServerConfig.from_dict(entry.config)

        return None

    def save_server_config(
        self, server_type: str, identifier: str, config: MCPServerConfig
    ) -> None:
        """
        Save a server configuration to the database.

        Args:
            server_type: The server type ('stdio' or 'sse')
            identifier: The server identifier (command or URL)
            config: The server configuration
        """
        # Reload the database first to avoid overwriting other changes
        self._load()

        key = MCPServerEntry.create_key(server_type, identifier)
        self.servers[key] = MCPServerEntry(
            type=server_type, identifier=identifier, config=config.to_dict()
        )

        self._save()

    def remove_server_config(self, server_type: str, identifier: str) -> bool:
        """
        Remove a server configuration from the database.

        Args:
            server_type: The server type ('stdio' or 'sse')
            identifier: The server identifier (command or URL)

        Returns:
            True if the server was removed, False if it wasn't found
        """
        # Reload the database first to avoid overwriting other changes
        self._load()

        key = MCPServerEntry.create_key(server_type, identifier)
        if key in self.servers:
            del self.servers[key]
            self._save()
            return True

        return False

    def list_servers(self) -> List[Dict[str, Any]]:
        """
        List all server entries in the database.

        Returns:
            A list of server entries
        """
        return [
            {
                "type": entry.type,
                "identifier": entry.identifier,
                "has_config": entry.config is not None,
            }
            for entry in self.servers.values()
        ]
