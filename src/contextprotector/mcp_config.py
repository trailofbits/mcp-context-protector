"""Classes and data structures that store, parse, and compare MCP server configurations."""

import hashlib
import json
import pathlib
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, TextIO


class ParameterType(str, Enum):
    """Types of MCP tool parameters."""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


class ApprovalStatus(str, Enum):
    """Approval status for an MCP server tracked in the local database."""

    APPROVED = "approved"
    UNAPPROVED = "unapproved"


@dataclass
class MCPToolSpec:
    """Specification for a tool that can be used by a model."""

    name: str
    description: str
    parameters: dict[str, Any]
    required: list[str]
    output_schema: dict[str, Any | None] | None = None

    def model_dump(self) -> dict[str, Any]:
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
    """Logical representation of a tool parameter with equality checking logic."""

    name: str
    description: str
    type: ParameterType
    required: bool = True
    default: Any | None = None
    enum: list[str | None] | None = None
    items: dict[str, Any | None] | None = None  # For array types
    properties: dict[str, Any | None] | None = None  # For object types

    def __hash__(self) -> int:
        """Compute hash based on immutable fields."""
        return hash((self.name, self.type))


@dataclass
class MCPToolDefinition:
    """Definition of all aspects of an MCP tool that are relevant to server pinning."""

    name: str
    description: str
    parameters: list[MCPParameterDefinition]
    output_schema: dict[str, Any | None] | None = None

    def __str__(self) -> str:
        """Generate a string representation of the tool with its parameters.

        Format is compact with parameters on a single line each.
        """
        lines = [f"Tool: {self.name}"]
        lines.append(f"Description: {self.description}")

        if self.parameters:
            lines.append("Parameters:")
            for param in self.parameters:
                required = "(required)" if param.required else "(optional)"
                param_line = (
                    f"  - {param.name} ({param.type.value}) {required}: {param.description}"
                )

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

    def __hash__(self) -> int:
        """Compute hash based on tool name."""
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        """Compare two tool definitions for equality."""
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

        return all(param == other_params[name] for name, param in self_params.items())


@dataclass
class ConfigDiff:
    """Class representing differences between two MCP server configurations."""

    old_instructions: str | None = field(default=None)
    new_instructions: str | None = field(default=None)
    added_tools: dict[str, MCPToolDefinition] = field(default_factory=dict)
    added_tool_names: list[str] = field(default_factory=list)
    removed_tools: list[str] = field(default_factory=list)
    modified_tools: dict[str, dict[str, Any]] = field(default_factory=dict)

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
            lines.extend([f"  - {tool_name}" for tool_name in self.removed_tools])
            lines.append("")

        if self.modified_tools:
            lines.append("Modified tools:")
            for tool_name, changes in self.modified_tools.items():
                lines.append(f"  ~ {tool_name}:")

                if "description" in changes:
                    lines.append("    Description changed:")
                    lines.append(f"      - {changes['description']['old']}")
                    lines.append(f"      + {changes['description']['new']}")

                if changes.get("added_params"):
                    lines.append("    Added parameters:")
                    lines.extend([f"      + {param}" for param in changes["added_params"]])

                if changes.get("removed_params"):
                    lines.append("    Removed parameters:")
                    lines.extend([f"      - {param}" for param in changes["removed_params"]])

                if changes.get("modified_params"):
                    lines.append("    Modified parameters:")
                    for param_name, param_changes in changes["modified_params"].items():
                        lines.append(f"      ~ {param_name}:")
                        for field, values in param_changes.items():
                            lines.append(f"        {field}: {values['old']} → {values['new']}")

        return "\n".join(lines)


@dataclass
class MCPServerConfig:
    """Class representing an MCP server configuration."""

    tools: list[MCPToolDefinition] = field(default_factory=list)
    instructions: str = field(default="")

    @classmethod
    def get_default_config_path(cls) -> str:
        """Get the default config path (~/.mcp-context-protector/config).

        Returns
        -------
            The default config path as a string

        """
        home_dir = pathlib.Path.home()
        data_dir = home_dir / ".mcp-context-protector"

        data_dir.mkdir(exist_ok=True)

        return str(data_dir / "config")

    def add_tool(self, tool: MCPToolDefinition | dict[str, Any]) -> None:
        """Add a tool to the server configuration.

        Args:
        ----
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

    def get_tool(self, tool_name: str) -> MCPToolDefinition | None:
        """Get a tool from the server configuration by name."""
        for tool in self.tools:
            if tool.name == tool_name:
                return tool
        return None

    def to_json(
        self, path: str | None = None, fp: TextIO | None = None, indent: int = 2
    ) -> str | None:
        """Serialize the configuration to JSON.

        Args:
        ----
            path: Optional file path to write the JSON to
            fp: Optional file-like object to write the JSON to
            indent: Number of spaces for indentation (default: 2)

        Returns:
        -------
            JSON string if neither path nor fp is provided, None otherwise

        """
        config_dict = self.to_dict()
        json_str = json.dumps(config_dict, indent=indent)

        if path:
            with pathlib.Path(path).open("w") as f:
                f.write(json_str)
            return None
        if fp:
            fp.write(json_str)
            return None
        return json_str

    @classmethod
    def from_json(
        cls, json_str: str | None = None, path: str | None = None, fp: TextIO | None = None
    ) -> "MCPServerConfig":
        """Deserialize the configuration from JSON.

        Args:
        ----
            json_str: JSON string to parse
            path: Optional file path to read the JSON from
            fp: Optional file-like object to read the JSON from

        Returns:
        -------
            MCPServerConfig instance

        Raises:
        ------
            ValueError: If no source is provided or multiple sources are provided

        """
        if sum(x is not None for x in (json_str, path, fp)) != 1:
            msg = "Exactly one of json_str, path, or fp must be provided"
            raise ValueError(msg)

        data = None
        if path:
            try:
                with pathlib.Path(path).open("r") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.decoder.JSONDecodeError):
                pass
        elif fp:
            data = json.load(fp)
        elif json_str is not None:
            data = json.loads(json_str)
        if data is not None:
            return cls.from_dict(data)
        else:
            # Return empty config if no data was loaded
            return cls(instructions="", tools=[])

    def to_dict(self) -> dict[str, Any]:
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
                            **({"default": param.default} if param.default is not None else {}),
                            **({"enum": param.enum} if param.enum is not None else {}),
                            **({"items": param.items} if param.items is not None else {}),
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
    def from_dict(cls, data: dict[str, Any | None] | None) -> "MCPServerConfig":
        """Create a server configuration from a dictionary."""
        config = cls()

        if data is None:
            return config

        instructions = data.get("instructions")
        if instructions and isinstance(instructions, str):
            config.instructions = instructions

        tools = data.get("tools", [])
        if not isinstance(tools, list):
            tools = []

        for tool_data in tools:
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

    '''def __hash__(self) -> int:
        """Compute hash based on server name."""
        return hash(self.server_name) if self.server_name else hash(id(self))'''

    def __eq__(self, other: object) -> bool:
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

        return all(tool == other_tools[name] for name, tool in self_tools.items())

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
            name: tool for (name, tool) in other_tools.items() if name in diff.added_tool_names
        }
        diff.removed_tools = list(self_tool_names - other_tool_names)

        common_tool_names = self_tool_names.intersection(other_tool_names)

        for tool_name in common_tool_names:
            self_tool = self_tools[tool_name]
            other_tool = other_tools[tool_name]

            if self_tool == other_tool:
                continue

            tool_changes: dict[str, Any] = {}

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
                    "properties",
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

    type: Literal["stdio", "http", "sse"]
    identifier: str  # URL for HTTP/SSE servers, command for stdio servers
    config: dict[str, Any | None] | None = None  # Serialized MCPServerConfig
    approval_status: ApprovalStatus = ApprovalStatus.UNAPPROVED
    approved_tools: dict[str, str] = field(default_factory=dict)  # tool_name -> tool_signature_hash
    approved_instructions_hash: str | None = None  # Hash of approved instructions

    @staticmethod
    def create_key(server_type: str, identifier: str) -> str:
        """Create a unique key for a server entry."""
        return f"{server_type}:{identifier}"

    @property
    def key(self) -> str:
        """Get the unique key for this server entry."""
        return self.create_key(self.type, self.identifier)

    def is_tool_approved(self, tool_name: str, tool_definition: MCPToolDefinition) -> bool:
        """Check if a specific tool is approved."""
        if tool_name not in self.approved_tools:
            return False

        current_hash = self._hash_tool_definition(tool_definition)
        return self.approved_tools[tool_name] == current_hash

    def are_instructions_approved(self, instructions: str) -> bool:
        """Check if the current instructions are approved."""
        if self.approved_instructions_hash is None:
            return False

        current_hash = self._hash_instructions(instructions)
        return self.approved_instructions_hash == current_hash

    def approve_tool(self, tool_name: str, tool_definition: MCPToolDefinition) -> None:
        """Approve a specific tool."""
        tool_hash = self._hash_tool_definition(tool_definition)
        self.approved_tools[tool_name] = tool_hash

    def approve_instructions(self, instructions: str) -> None:
        """Approve the server instructions."""
        self.approved_instructions_hash = self._hash_instructions(instructions)

    def remove_tool_approval(self, tool_name: str) -> None:
        """Remove approval for a specific tool."""
        self.approved_tools.pop(tool_name, None)

    @staticmethod
    def _hash_tool_definition(tool_definition: MCPToolDefinition) -> str:
        """Create a hash of a tool definition for comparison."""
        # Create a normalized representation of the tool
        tool_dict = {
            "name": tool_definition.name,
            "description": tool_definition.description,
            "parameters": sorted(
                [
                    {
                        "name": p.name,
                        "description": p.description,
                        "type": p.type.value,
                        "required": p.required,
                        "default": p.default,
                        "enum": p.enum,
                        "items": p.items,
                        "properties": p.properties,
                    }
                    for p in tool_definition.parameters
                ],
                key=lambda x: str(x["name"]),  # type: ignore[index]
            ),
            "output_schema": tool_definition.output_schema,
        }

        # Convert to JSON and hash
        json_str = json.dumps(tool_dict, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_instructions(instructions: str | None) -> str:
        """Create a hash of server instructions."""
        # Handle None instructions (empty string)
        if instructions is None:
            instructions = ""
        return hashlib.sha256(instructions.encode("utf-8")).hexdigest()


class MCPConfigDatabase:
    """Class for managing multiple server configurations in a single file.

    This database stores server configurations indexed by their type and identifier.
    It provides thread-safe access to the configuration file to prevent race conditions.
    """

    _file_lock = threading.RLock()  # Class-level lock for file operations

    def __init__(self, config_path: str | None = None) -> None:
        """Initialize the config database.

        Args:
        ----
            config_path: Path to the config file. If None, uses the default path.

        """
        self.config_path = config_path or self.get_default_config_path()
        self.servers: dict[str, MCPServerEntry] = {}
        self._load()

    @staticmethod
    def get_default_config_path() -> str:
        """Get the default config database path (~/.mcp-context-protector/servers.json).

        Returns
        -------
            The default config path as a string

        """
        home_dir = pathlib.Path.home()
        data_dir = home_dir / ".mcp-context-protector"

        data_dir.mkdir(exist_ok=True)

        return str(data_dir / "servers.json")

    def _load(self) -> None:
        """Load server configurations from the config file."""
        with MCPConfigDatabase._file_lock:
            try:
                if pathlib.Path(self.config_path).exists():
                    with pathlib.Path(self.config_path).open("r") as f:
                        data = json.load(f)
                        for server_data in data.get("servers", []):
                            approval_status_str = server_data.get(
                                "approval_status", ApprovalStatus.UNAPPROVED.value
                            )
                            try:
                                approval_status = ApprovalStatus(approval_status_str)
                            except ValueError:
                                approval_status = ApprovalStatus.UNAPPROVED

                            entry = MCPServerEntry(
                                type=server_data.get("type"),
                                identifier=server_data.get("identifier"),
                                config=server_data.get("config"),
                                approval_status=approval_status,
                                approved_tools=server_data.get("approved_tools", {}),
                                approved_instructions_hash=server_data.get(
                                    "approved_instructions_hash"
                                ),
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
                        "approval_status": entry.approval_status.value,
                        "approved_tools": entry.approved_tools,
                        "approved_instructions_hash": entry.approved_instructions_hash,
                    }
                    for entry in self.servers.values()
                ]
            }

            pathlib.Path(self.config_path).parent.mkdir(parents=True, exist_ok=True)

            # Write to a temporary file first, then rename
            temp_path = f"{self.config_path}.tmp"
            with pathlib.Path(temp_path).open("w") as f:
                json.dump(data, f, indent=2)

            # Atomically replace the old file with the new one
            pathlib.Path(temp_path).replace(self.config_path)

    def get_server_config(self, server_type: str, identifier: str) -> MCPServerConfig | None:
        """Get a server configuration by type and identifier.

        Args:
        ----
            server_type: The server type ('stdio', 'http', or 'sse')
            identifier: The server identifier (command or URL)

        Returns:
        -------
            The server configuration, or None if not found

        """
        key = MCPServerEntry.create_key(server_type, identifier)
        entry = self.servers.get(key)

        if entry and entry.config:
            return MCPServerConfig.from_dict(entry.config)

        return None

    def save_server_config(
        self,
        server_type: Literal["stdio", "http", "sse"],
        identifier: str,
        config: MCPServerConfig,
        approval_status: ApprovalStatus = ApprovalStatus.APPROVED,
    ) -> None:
        """Save a server configuration to the database.

        Args:
        ----
            server_type: The server type ('stdio', 'http', or 'sse')
            identifier: The server identifier (command or URL)
            config: The server configuration
            approval_status: The approval status for the configuration

        """
        # Reload the database first to avoid overwriting other changes
        self._load()

        key = MCPServerEntry.create_key(server_type, identifier)

        # Preserve existing granular approvals if updating an existing entry
        existing_entry = self.servers.get(key)
        if existing_entry:
            self.servers[key] = MCPServerEntry(
                type=server_type,
                identifier=identifier,
                config=config.to_dict(),
                approval_status=approval_status,
                approved_tools=existing_entry.approved_tools,
                approved_instructions_hash=existing_entry.approved_instructions_hash,
            )
        else:
            self.servers[key] = MCPServerEntry(
                type=server_type,
                identifier=identifier,
                config=config.to_dict(),
                approval_status=approval_status,
            )

        self._save()

    def remove_server_config(self, server_type: str, identifier: str) -> bool:
        """Remove a server configuration from the database.

        Args:
        ----
            server_type: The server type ('stdio', 'http', or 'sse')
            identifier: The server identifier (command or URL)

        Returns:
        -------
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

    def list_servers(self) -> list[dict[str, Any]]:
        """List all server entries in the database.

        Returns
        -------
            A list of server entries

        """
        return [
            {
                "type": entry.type,
                "identifier": entry.identifier,
                "has_config": entry.config is not None,
                "approval_status": entry.approval_status.value,
            }
            for entry in self.servers.values()
        ]

    def save_unapproved_config(
        self, server_type: Literal["stdio", "http", "sse"], identifier: str, config: MCPServerConfig
    ) -> None:
        """Save an unapproved server configuration to the database.

        This is called when the wrapper encounters a new server configuration
        that hasn't been approved yet.

        Args:
        ----
            server_type: The server type ('stdio', 'http', or 'sse')
            identifier: The server identifier (command or URL)
            config: The server configuration

        """
        self.save_server_config(server_type, identifier, config, ApprovalStatus.UNAPPROVED)

    def approve_server_config(self, server_type: str, identifier: str) -> bool:
        """Mark a server configuration as approved.

        Args:
        ----
            server_type: The server type ('stdio', 'http', or 'sse')
            identifier: The server identifier (command or URL)

        Returns:
        -------
            True if the server was found and approved, False otherwise

        """
        # Reload the database first to avoid overwriting other changes
        self._load()

        key = MCPServerEntry.create_key(server_type, identifier)
        if key in self.servers:
            self.servers[key].approval_status = ApprovalStatus.APPROVED
            self._save()
            return True

        return False

    def list_unapproved_servers(self) -> list[dict[str, Any]]:
        """List all unapproved server entries in the database.

        Returns
        -------
            A list of unapproved server entries

        """
        return [
            {
                "type": entry.type,
                "identifier": entry.identifier,
                "has_config": entry.config is not None,
                "approval_status": entry.approval_status.value,
            }
            for entry in self.servers.values()
            if entry.approval_status == ApprovalStatus.UNAPPROVED
        ]

    def is_server_approved(self, server_type: str, identifier: str) -> bool:
        """Check if a server configuration is approved.

        Args:
        ----
            server_type: The server type ('stdio', 'http', or 'sse')
            identifier: The server identifier (command or URL)

        Returns:
        -------
            True if the server is approved, False otherwise

        """
        key = MCPServerEntry.create_key(server_type, identifier)
        if key in self.servers:
            return self.servers[key].approval_status == ApprovalStatus.APPROVED
        return False

    def approve_tool(
        self, server_type: str, identifier: str, tool_name: str, tool_definition: MCPToolDefinition
    ) -> bool:
        """Approve a specific tool for a server.

        Args:
        ----
            server_type: The server type ('stdio', 'http', or 'sse')
            identifier: The server identifier (command or URL)
            tool_name: The name of the tool to approve
            tool_definition: The tool definition to approve

        Returns:
        -------
            True if the tool was approved, False if server not found

        """
        self._load()

        key = MCPServerEntry.create_key(server_type, identifier)
        if key in self.servers:
            self.servers[key].approve_tool(tool_name, tool_definition)
            self._save()
            return True
        return False

    def approve_instructions(self, server_type: str, identifier: str, instructions: str) -> bool:
        """Approve the instructions for a server.

        Args:
        ----
            server_type: The server type ('stdio', 'http', or 'sse')
            identifier: The server identifier (command or URL)
            instructions: The instructions to approve

        Returns:
        -------
            True if the instructions were approved, False if server not found

        """
        self._load()

        key = MCPServerEntry.create_key(server_type, identifier)
        if key in self.servers:
            # Handle None instructions
            instructions = instructions or ""
            self.servers[key].approve_instructions(instructions)
            self._save()
            return True
        return False

    def is_tool_approved(
        self, server_type: str, identifier: str, tool_name: str, tool_definition: MCPToolDefinition
    ) -> bool:
        """Check if a specific tool is approved for a server.

        Args:
        ----
            server_type: The server type ('stdio', 'http', or 'sse')
            identifier: The server identifier (command or URL)
            tool_name: The name of the tool to check
            tool_definition: The tool definition to check

        Returns:
        -------
            True if the tool is approved, False otherwise

        """
        key = MCPServerEntry.create_key(server_type, identifier)
        if key in self.servers:
            return self.servers[key].is_tool_approved(tool_name, tool_definition)
        return False

    def are_instructions_approved(
        self, server_type: str, identifier: str, instructions: str
    ) -> bool:
        """Check if the instructions are approved for a server.

        Args:
        ----
            server_type: The server type ('stdio', 'http', or 'sse')
            identifier: The server identifier (command or URL)
            instructions: The instructions to check

        Returns:
        -------
            True if the instructions are approved, False otherwise

        """
        key = MCPServerEntry.create_key(server_type, identifier)
        if key in self.servers:
            # Handle None instructions
            instructions = instructions or ""
            return self.servers[key].are_instructions_approved(instructions)
        return False

    def get_server_approval_status(
        self, server_type: str, identifier: str, config: MCPServerConfig
    ) -> dict[str, Any]:
        """Get detailed approval status for a server and its components.

        Args:
        ----
            server_type: The server type ('stdio', 'http', or 'sse')
            identifier: The server identifier (command or URL)
            config: The current server configuration

        Returns:
        -------
            Dict with approval status details

        """
        key = MCPServerEntry.create_key(server_type, identifier)

        result: dict[Any, Any] = {
            "server_approved": False,
            "instructions_approved": False,
            "tools": {},
            "is_new_server": key not in self.servers,
        }

        if key not in self.servers:
            # New server - nothing is approved
            for tool in config.tools:
                result["tools"][tool.name] = False
            return result

        entry = self.servers[key]
        result["server_approved"] = entry.approval_status == ApprovalStatus.APPROVED
        result["instructions_approved"] = entry.are_instructions_approved(config.instructions)

        # Check each tool
        for tool in config.tools:
            result["tools"][tool.name] = entry.is_tool_approved(tool.name, tool)

        return result
