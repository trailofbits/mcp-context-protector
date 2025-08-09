"""Core wrapper functionality for mcp-context-protector."""

import asyncio
import json
import logging
import re
from typing import Any, Literal

from mcp import ClientSession, types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.shared.exceptions import McpError
from mcp.shared.session import RequestResponder
from pydantic import AnyUrl

# ContentBlock import removed - using types.Content instead
# Import guardrail types for type hints
from .guardrail_types import GuardrailAlert, GuardrailProvider, ToolResponse
from .mcp_config import (
    MCPConfigDatabase,
    MCPParameterDefinition,
    MCPServerConfig,
    MCPToolDefinition,
    MCPToolSpec,
    ParameterType,
)

# Import quarantine functionality
from .quarantine import ToolResponseQuarantine
from .wrapper_config import MCPWrapperConfig

logger = logging.getLogger("mcp_wrapper")


class ChildServerNotConnectedError(ConnectionError):
    """Raised when the child MCP server is not connected."""

    def __init__(self) -> None:
        """Initialize error message."""
        super().__init__("Child MCP server not connected")


class MCPWrapperServer:
    """MCP wrapper server with security features.

    Provides server pinning, automatic blocking of changed tools, invocation of the enabled
    guardrail provider, and quarantining of tool responses.
    """

    @classmethod
    def from_config(cls, config: MCPWrapperConfig) -> "MCPWrapperServer":
        """Create a wrapper server from a configuration object.

        Args:
        ----
            config: MCPWrapperConfig object containing all configuration parameters

        Returns:
        -------
            An instance of MCPWrapperServer configured according to the config

        """
        # Import here to avoid circular imports

        instance = cls(
            config_path=config.config_path,
            guardrail_provider=config.guardrail_provider,
            quarantine_path=config.quarantine_path,
        )

        # Set connection-specific attributes
        instance.connection_type = config.connection_type

        if config.connection_type == "stdio" and config.command is not None:
            instance.child_command = config.command
        elif config.url is not None:  # http or sse
            instance.server_url = AnyUrl(config.url)
        else:
            raise ValueError

        instance.visualize_ansi_codes = config.visualize_ansi_codes

        return instance

    def __init__(
        self,
        config_path: str | None = None,
        guardrail_provider: GuardrailProvider | None = None,
        quarantine_path: str | None = None,
    ) -> None:
        """Initialize the wrapper server with common attributes.

        Use from_config class method instead of calling this directly.

        Args:
        ----
            config_path: Optional path to the wrapper config file
            guardrail_provider: Optional guardrail provider object to use for checking configs
            quarantine_path: Optional path to the quarantine database file

        """
        self.child_command: str | None = None
        self.server_url: AnyUrl | None = None
        self.connection_type: Literal["stdio", "http", "sse"] = "stdio"
        # Will be set after determining connection details
        self.server_identifier: str | None = None
        self.child_process: Any = None
        self.client_context: Any = None
        self.streams: Any = None
        self.session: ClientSession | None = None
        self.initialize_result: Any = None
        self.tool_specs: list[Any] = []
        self.config_approved = False
        self.config_db = MCPConfigDatabase(config_path)
        # Will be loaded after server_identifier is set
        self.saved_config: MCPServerConfig | None = None
        self.current_config = MCPServerConfig()
        self.server: Server = Server("mcp_wrapper")
        self.guardrail_provider = guardrail_provider
        self.use_guardrails = guardrail_provider is not None
        self.visualize_ansi_codes = False
        self.server_session: Any = None  # Track the server session for sending notifications
        self.quarantine = ToolResponseQuarantine(quarantine_path) if self.use_guardrails else None
        self.tasks: set[asyncio.Task[Any]] = set()
        self._setup_handlers()

    async def _get_resource_mime_type(self, uri: str) -> str:
        """Get the original mime type for a resource from the resource list."""
        if not self.session:
            return "text/plain"
        try:
            resources_result = await self.session.list_resources()
            if resources_result and resources_result.resources:
                for resource in resources_result.resources:
                    if resource.uri == uri:
                        return resource.mimeType or "text/plain"
        except McpError:
            pass
        return "text/plain"

    def _setup_handlers(self) -> None:
        """Set up MCP server handlers."""
        self._setup_notification_handlers()

        @self.server.list_prompts()
        async def list_prompts() -> list[types.Prompt]:
            """Return prompts from the downstream server.

            Return an empty list if server config is not approved.

            When config isn't approved, we don't reveal any prompts to clients.
            """
            if self.session is None:
                raise ChildServerNotConnectedError

            if not self.config_approved:
                logger.warning("Blocking list_prompts - server configuration not approved")
                return []

            try:
                downstream_prompts = await self.session.list_prompts()
                if downstream_prompts and downstream_prompts.prompts:
                    logger.info(
                        "Returning %d prompts to upstream client", len(downstream_prompts.prompts)
                    )
                    return downstream_prompts.prompts
                logger.info("No prompts available from downstream server")
            except McpError as e:
                logger.warning("Error getting prompts from downstream server: %s", e)
            return []

        @self.server.list_resources()
        async def list_resources() -> list[types.Resource]:
            """Return resources from the downstream server.

            Unlike prompts and tools, resources are always available regardless of config approval.
            """
            if self.session is None:
                raise ChildServerNotConnectedError

            try:
                downstream_resources = await self.session.list_resources()
                if downstream_resources and downstream_resources.resources:
                    logger.info(
                        "Returning %d resources to upstream client",
                        len(downstream_resources.resources),
                    )
                    return downstream_resources.resources
                logger.info("No resources available from downstream server")
            except McpError as e:
                logger.warning("Error getting resources from downstream server: %s", e)
            return []

        @self.server.read_resource()
        async def read_resource(name: AnyUrl) -> str | bytes:
            """Handle resource content requests - proxy directly to downstream server.

            Resources are always accessible regardless of server config approval status.

            Args:
            ----
                name: The name/id of the resource

            Returns:
            -------
                The resource content from the downstream server

            """
            logger.info("Proxying resource request: %s", name)

            if not self.session:
                raise ChildServerNotConnectedError

            try:
                # Directly proxy the resource request to the downstream server
                result = await self.session.read_resource(name)

                # Extract the raw content from the first content item
                if result.contents:
                    content_item = result.contents[0]
                    if isinstance(content_item, types.BlobResourceContents):
                        # For binary data, decode base64 blob to bytes
                        import base64

                        return base64.b64decode(content_item.blob)
                    elif isinstance(content_item, types.TextResourceContents):
                        # For text data, return the text as string
                        return content_item.text

                # Fallback - return empty string if no content
                logger.warning("No content found in resource response for %s", name)
                return ""

            except McpError as e:
                logger.exception("Error fetching resource %s from downstream server", name)
                error_msg = f"Error fetching resource from downstream server: {e!s}"
                raise ConnectionError(error_msg) from e

        @self.server.list_tools()
        async def list_tools() -> list[types.Tool]:
            """Return tool specs based on granular approval status."""
            wrapper_tools = []

            # Add context-protector-block if server/instructions not fully approved
            if not self.config_approved or (
                hasattr(self, "approval_status")
                and not self.approval_status.get("instructions_approved", False)
            ):
                # Count blocked tools
                total_tools = 0
                blocked_new_tools = 0
                blocked_changed_tools = 0
                if hasattr(self, "approval_status"):
                    tools_status = self.approval_status.get("tools", {})
                    total_tools = len(tools_status)
                    blocked_tools = sum(1 for approved in tools_status.values() if not approved)
                    if self.approval_status.get("is_new_server", False):
                        blocked_new_tools = blocked_tools
                    else:
                        blocked_changed_tools = blocked_tools

                description = (
                    f"Get information about blocked server configuration. "
                    f"{total_tools} tools blocked"
                )
                if blocked_new_tools > 0:
                    description += f" ({blocked_new_tools} new tools)"
                if blocked_changed_tools > 0:
                    description += f" ({blocked_changed_tools} changed tools)"

                wrapper_tools.append(
                    types.Tool(
                        name="context-protector-block",
                        description=description,
                        inputSchema={"type": "object", "properties": {}, "required": []},
                    )
                )

            # Add quarantine_release tool if quarantine is enabled
            if self.use_guardrails and self.quarantine:
                wrapper_tools.append(
                    types.Tool(
                        name="quarantine_release",
                        description="Release a quarantined tool response for review",
                        inputSchema={
                            "type": "object",
                            "required": ["uuid"],
                            "properties": {
                                "uuid": {
                                    "type": "string",
                                    "description": (
                                        "UUID of the quarantined tool response to release"
                                    ),
                                }
                            },
                        },
                    )
                )

            # If config is not approved at all, return only wrapper tools
            if not self.config_approved:
                logger.info("Config not approved - returning only wrapper tools")
                return wrapper_tools

            # Config is approved (at least partially) - return approved downstream tools
            all_tools = wrapper_tools.copy()

            for spec in self.tool_specs:
                # Check if this specific tool is approved
                if hasattr(self, "approval_status") and self.approval_status.get("tools", {}).get(
                    spec.name, False
                ):
                    tool_kwargs = {
                        "name": spec.name,
                        "description": spec.description,
                        "inputSchema": self._convert_parameters_to_schema(
                            spec.parameters, spec.required
                        ),
                    }

                    # Add outputSchema if present
                    if spec.output_schema is not None:
                        tool_kwargs["outputSchema"] = spec.output_schema

                    tool = types.Tool(**tool_kwargs)
                    all_tools.append(tool)

            return all_tools

        @self.server.get_prompt()
        async def get_prompt(name: str, arguments: dict) -> types.GetPromptResult:
            """Handle prompt dispatch requests - proxy to downstream server if config is approved.

            If the server config isn't approved, return an empty message list.
            """
            if self.session is None:
                raise ChildServerNotConnectedError

            logger.info(
                "Prompt dispatch with name %s and config_approved %s", name, self.config_approved
            )

            if not self.config_approved:
                logger.warning("Blocking prompt '%s' - server configuration not approved", name)

                return types.GetPromptResult(
                    description="Server configuration not approved",
                    messages=[],  # Empty message list
                )

            try:
                result = await self.session.get_prompt(name, arguments)

                # Extract the text content from the result
                text_parts = []
                for content in result.messages:
                    if content.content:
                        if self.visualize_ansi_codes:
                            processed_content = make_ansi_escape_codes_visible(content.content)
                            if not isinstance(processed_content, str):
                                content.content = processed_content
                        text_parts.append(content.content)

                return types.GetPromptResult(
                    description=result.description,
                    messages=[
                        types.PromptMessage(role="user", content=text) for text in text_parts
                    ],
                )

            except McpError as e:
                logger.exception("Error from downstream server during prompt dispatch")
                error_msg = f"Error from downstream server: {e!s}"
                raise ConnectionError(error_msg) from e

        @self.server.call_tool()
        async def call_tool(
            name: str, arguments: dict
        ) -> types.CallToolResult | list[types.TextContent]:
            """Handle tool use requests.

            Either approve config, proxy to downstream server, handle quarantine release, or block
            if server config not approved.
            """
            logger.info("Tool call with name %s and config_approved %s", name, self.config_approved)

            # Handle wrapper tools
            if name == "context-protector-block":
                return await self._handle_context_protector_block()

            if name == "quarantine_release" and self.use_guardrails and self.quarantine:
                return await self._handle_quarantine_release(arguments)

            if not self.session:
                raise ChildServerNotConnectedError

            # Check if this specific tool is approved using granular approval system
            if not hasattr(self, "approval_status"):
                logger.warning("Blocking tool '%s' - approval status not initialized", name)
                blocked_response = {
                    "status": "blocked",
                    "reason": "Server approval status not initialized. Try reconnecting.",
                }
                error_json = json.dumps(blocked_response)
                error_json = json.dumps(blocked_response)
                raise ValueError(error_json)

            # Check if server is completely new or instructions changed
            if self.approval_status.get("is_new_server", False):
                logger.warning("Blocking tool '%s' - new server not approved", name)
                blocked_response = {
                    "status": "blocked",
                    "reason": (
                        "Server configuration not approved. Use the "
                        "'context-protector-block' tool for approval instructions."
                    ),
                }
                error_json = json.dumps(blocked_response)
                error_json = json.dumps(blocked_response)
                raise ValueError(error_json)

            # Check instructions approval - but differentiate between never-approved
            # and changed instructions
            if not self.approval_status.get("instructions_approved", False):
                if self.approval_status.get("server_approved", False):
                    # Server was previously approved but instructions changed
                    logger.warning("Blocking tool '%s' - server instructions have changed", name)
                    blocked_response = {
                        "status": "blocked",
                        "reason": (
                            "Server instructions have changed and need re-approval. "
                            "Use the 'context-protector-block' tool for approval instructions."
                        ),
                    }
                else:
                    # Server was never approved
                    logger.warning("Blocking tool '%s' - server not approved", name)
                    blocked_response = {
                        "status": "blocked",
                        "reason": (
                            "Server configuration not approved. Use the "
                            "'context-protector-block' tool for approval instructions."
                        ),
                    }
                error_json = json.dumps(blocked_response)
                error_json = json.dumps(blocked_response)
                raise ValueError(error_json)

            # Check if this specific tool is approved
            # Only block if the tool exists in our config but is not approved
            # If the tool doesn't exist in our config, let the downstream server handle it
            tools_dict = self.approval_status.get("tools", {})
            if name in tools_dict and not tools_dict[name]:
                logger.warning("Blocking tool '%s' - tool not approved", name)
                blocked_response = {
                    "status": "blocked",
                    "reason": (
                        f"Tool '{name}' is not approved. Use the "
                        "'context-protector-block' tool for approval instructions."
                    ),
                }
                error_json = json.dumps(blocked_response)
                error_json = json.dumps(blocked_response)
                raise ValueError(error_json)

            # Tool is approved, proxy the call
            try:
                tool_result = await self._proxy_tool_to_downstream(name, arguments)

                # If tool_result is a dict with structured content, handle it properly
                if isinstance(tool_result, dict) and "structured_content" in tool_result:
                    # Check if we have non-text content that needs to be preserved
                    has_non_text_content = False
                    if tool_result.get("content_list"):
                        has_non_text_content = any(
                            c.type != "text" for c in tool_result["content_list"]
                        )

                    if has_non_text_content:
                        # Use the preserved content list to maintain resource links
                        content = tool_result["content_list"]
                    else:
                        # Fallback to wrapped text response for backward compatibility
                        wrapped_response = {
                            "status": "completed",
                            "response": tool_result["text"],
                        }
                        json_response = json.dumps(wrapped_response)
                        content = [types.TextContent(type="text", text=json_response)]

                    # Return with all content types preserved
                    # Due to a bug/compatibility issue with CallToolResult when structured content
                    # is present, we return the content list directly instead of wrapping it in
                    # a CallToolResult
                    return content if isinstance(content, list) else [content]
                # Legacy text-only response (backward compatibility)
                # TODO: do we need this?
                wrapped_response = {"status": "completed", "response": tool_result}
                json_response = json.dumps(wrapped_response)
                return [types.TextContent(type="text", text=json_response)]

            except McpError as e:
                logger.exception("Error from child MCP server")
                error_msg = f"Error from child MCP server: {e!s}"
                raise ConnectionError(error_msg) from e

    async def _handle_context_protector_block(self) -> list[types.TextContent]:
        """Handle the context-protector-block tool call.

        Returns
        -------
            Information about blocked tools and instructions for approving the server configuration

        """
        # Count blocked tools and categorize them
        total_tools = 0
        blocked_tools = 0
        blocked_new_tools = 0
        blocked_changed_tools = 0

        if hasattr(self, "approval_status"):
            tools_status = self.approval_status.get("tools", {})
            total_tools = len(tools_status)
            blocked_tools = sum(1 for approved in tools_status.values() if not approved)

            if self.approval_status.get("is_new_server", False):
                blocked_new_tools = blocked_tools
            else:
                blocked_changed_tools = blocked_tools

        instructions = f"""
mcp-context-protector status:

{blocked_tools} out of {total_tools} tools are currently blocked
"""

        if blocked_new_tools > 0:
            instructions += (
                f"- {blocked_new_tools} tools blocked because they are from a new server\n"
            )
        if blocked_changed_tools > 0:
            instructions += (
                f"- {blocked_changed_tools} tools blocked because their configuration has changed\n"
            )

        instructions += """

To approve this server configuration, run the wrapper in review mode:

mcp-context-protector.sh --list-server stdio "your-server-command"

The review process will show you the server's capabilities and tools, and ask if you want to
trust them.
Once approved, you can use all the server's tools through this wrapper.

Note: This tool is only available when tools are blocked due to security restrictions.
"""

        return [types.TextContent(type="text", text=instructions.strip())]

    async def _handle_quarantine_release(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent]:
        """Handle the quarantine_release tool call.

        Args:
        ----
            arguments: The tool arguments containing the UUID of the quarantined response

        Returns:
        -------
            The original tool response if found and available for release

        Raises:
        ------
            ValueError: If the UUID is invalid or not found, or if the response
                is not available for release

        """
        if "uuid" not in arguments:
            msg = "Missing required parameter 'uuid' for quarantine_release tool"
            raise ValueError(msg)

        if self.quarantine is None:
            msg = "Quarantine not initialized"
            raise ValueError(msg)  # TODO: better exception

        response_id = arguments["uuid"]
        logger.info("Processing quarantine_release request for UUID: %s", response_id)

        quarantined_response = self.quarantine.get_response(response_id)

        if not quarantined_response:
            error_msg = f"No quarantined response found with UUID: {response_id}"
            raise ValueError(error_msg)

        if quarantined_response.released:
            original_tool_info = {
                "tool_name": quarantined_response.tool_name,
                "tool_input": quarantined_response.tool_input,
                "tool_output": quarantined_response.tool_output,
                "quarantine_reason": quarantined_response.reason,
                "quarantine_id": quarantined_response.id,
            }

            self.quarantine.delete_response(response_id)
            logger.info("Released response %s from quarantine and deleted it", response_id)

            json_response = json.dumps(original_tool_info)
            wrapped_response = {"status": "completed", "response": json_response}
            final_response = json.dumps(wrapped_response)
            return [types.TextContent(type="text", text=final_response)]
        error = (
            f"Response {response_id} is not marked for release. "
            "Please use the CLI to review and release it first: "
            f"mcp-context-protector.sh --review-quarantine --quarantine-id {response_id}"
        )
        return [types.TextContent(type="text", text=error)]

    async def _proxy_tool_to_downstream(self, name: str, arguments: dict) -> str | dict[str, Any]:
        """Proxy a tool call to the downstream server using MCP client."""
        if not self.session:
            raise ChildServerNotConnectedError

        try:
            logger.info("Forwarding tool call to downstream: %s with args %s", name, arguments)
            result = await self.session.call_tool(name, arguments)

            # Extract content, structured content, and preserve all content types
            response_text = ""
            structured_content: dict[str, Any] = {}
            processed_content: list[
                types.TextContent | types.ImageContent | types.EmbeddedResource
            ] = []

            if result and len(result.content) > 0:
                # Process all content types, preserving non-text content like EmbeddedResource
                text_parts = []
                for content in result.content:
                    if content.type == "text" and content.text:
                        # Apply ANSI escape code processing if enabled
                        processed_text = self._make_ansi_escape_codes_visible(content.text)
                        text_parts.append(processed_text)
                        # Create processed text content for the response
                        processed_content.append(
                            types.TextContent(type="text", text=processed_text)
                        )
                    else:
                        # Preserve non-text content (EmbeddedResource, ImageContent, etc.)
                        processed_content.append(content)

                if text_parts:
                    response_text = " ".join(text_parts)
            else:
                # No content from downstream, use default text
                response_text = f"Tool call to '{name}' succeeded but returned no content"
                processed_content = [types.TextContent(type="text", text=response_text)]

            # Extract structured content if present
            if (
                result
                and hasattr(result, "structuredContent")
                and result.structuredContent is not None
            ):
                structured_content = result.structuredContent

            # Scan the tool response with guardrail provider if configured
            if self.use_guardrails and self.guardrail_provider is not None:
                guardrail_alert = self._scan_tool_response(name, arguments, response_text)
                if guardrail_alert:
                    # Log the alert but don't block the response yet
                    logger.exception(
                        "Guardrail alert triggered for tool '%s': %s",
                        name,
                        guardrail_alert.explanation,
                    )
                    # Store in quarantine for future reference
                    # (when quarantine system is integrated)
                    quarantine_id = None
                    if self.quarantine:
                        quarantine_id = self.quarantine.quarantine_response(
                            tool_name=name,
                            tool_input=arguments,
                            tool_output=response_text,
                            reason=guardrail_alert.explanation,
                        )

                    return self._guardrail_tool_response(
                        name, arguments, response_text, guardrail_alert, quarantine_id
                    )

            # Return both text and structured content, preserving all content types
            return self._create_tool_response(response_text, structured_content, processed_content)

        except McpError as e:
            logger.exception("Error calling downstream tool '%s'", name)
            error_msg = f"Error calling downstream tool: {e!s}"
            raise ConnectionError(error_msg) from e

    def _create_tool_response(
        self,
        response_text: str,
        structured_content: dict[str, Any | None],
        content_list: list[Any],  # TODO: figure out mypy's inability to find ContentBlock
    ) -> dict[str, Any]:
        """Create a tool response dict with text, structured content, and all content types."""
        return {
            "text": response_text,
            "structured_content": structured_content,
            "content_list": content_list,
        }

    def _guardrail_tool_response(
        self,
        tool_name: str,
        arguments: dict,
        _response_text: str,
        guardrail_alert: GuardrailAlert,
        quarantine_id: str | None,
    ) -> str:
        """Generate the response message sent to the client.

        When a tool response is blocked by a guardrail.
        """
        return f"""
        This tool call was quarantined because it appears to contain a prompt injection attack.

        Tool name: {tool_name}
        Arguments: {json.dumps(arguments, indent=2)}
        Alert explanation: {guardrail_alert.explanation}

        To review this response and release it from the quarantine, run contextprotector with the
        arguments `--review-quarantine{
            " --quarantine-id " + quarantine_id if quarantine_id else ""
        }`.
        """

    def _convert_parameters_to_schema(self, parameters: dict, required: list[str]) -> dict:
        """Convert parameters format to JSON Schema for MCP Tool."""
        properties = {}

        for param_name, param_info in parameters.items():
            param_schema = param_info.get("schema", {})
            properties[param_name] = {
                "type": param_schema.get("type", "string"),
                "description": param_info.get("description", ""),
            }

            # Add any enum values if present
            if "enum" in param_schema:
                properties[param_name]["enum"] = param_schema["enum"]

        return {"type": "object", "required": required, "properties": properties}

    def _convert_mcp_tools_to_specs(self, tools: list[types.Tool]) -> list[MCPToolSpec]:
        """Convert MCP tool definitions to internal tool specs.

        Args:
        ----
            tools: list of MCP tool definitions

        Returns:
        -------
            List of MCPToolSpec objects

        """
        tool_specs = []

        for tool in tools:
            parameters = {}
            required = []

            # Extract properties and required fields from schema
            if tool.inputSchema and "properties" in tool.inputSchema:
                for prop_name, prop_details in tool.inputSchema["properties"].items():
                    parameters[prop_name] = {
                        "description": prop_details.get("description", ""),
                        "schema": {"type": prop_details.get("type", "string")},
                    }

                    if "enum" in prop_details:
                        parameters[prop_name]["schema"]["enum"] = prop_details["enum"]

            if tool.inputSchema and "required" in tool.inputSchema:
                required = tool.inputSchema["required"]

            # Extract output schema if present
            output_schema = None
            if hasattr(tool, "outputSchema") and tool.outputSchema is not None:
                output_schema = tool.outputSchema

            tool_spec = MCPToolSpec(
                name=tool.name,
                description=tool.description or "",
                parameters=parameters,
                required=required,
                output_schema=output_schema,
            )

            tool_specs.append(tool_spec)

        return tool_specs

    async def _handle_tool_updates(self, tools: list[types.Tool]) -> None:
        """Handle tool update notifications from the downstream server.

        Args:
        ----
            tools: Updated list of tools from the downstream server

        """
        self.tool_specs = self._convert_mcp_tools_to_specs(tools)

        old_config = self.current_config
        self.current_config = self._create_server_config()

        # Re-evaluate approval status with the new config
        self.approval_status = self.config_db.get_server_approval_status(
            self.connection_type, self.get_server_identifier(), self.current_config
        )

        # Log the configuration changes if any
        if old_config != self.current_config:
            diff = old_config.compare(self.current_config)
            if diff.has_differences():
                logger.warning("Configuration differences detected: %s", diff)

                # Update the database with new unapproved config
                self.config_db.save_unapproved_config(
                    self.connection_type, self.get_server_identifier(), self.current_config
                )

        # Update config_approved based on the new granular status
        if self.approval_status.get("is_new_server", False) or not self.approval_status.get(
            "instructions_approved", False
        ):
            self.config_approved = False
        else:
            # Check if we have any approved tools
            approved_tool_count = sum(
                1 for approved in self.approval_status["tools"].values() if approved
            )
            self.config_approved = approved_tool_count > 0

        logger.info("Tool update processed - approval status: %s", self.config_approved)
        if hasattr(self, "approval_status"):
            approved_tools = [
                name for name, approved in self.approval_status["tools"].items() if approved
            ]
            logger.info("Approved tools: %s", approved_tools)

    async def _forward_notification_to_upstream(
        self, method: str, params: dict[str, Any] | None = None
    ) -> None:
        """Forward a notification to the upstream client.

        Args:
        ----
            method: The notification method (e.g., "notifications/progress")
            params: Optional notification parameters

        """
        if not self.server_session:
            logger.warning("No server session available to forward notification")
            return

        try:
            notification: Any
            # Create appropriate notification type based on method
            if method == "notifications/progress":
                notification = types.ProgressNotification(
                    method=method, params=params if params else None
                )
            elif method == "notifications/tools/list_changed":
                notification = types.ToolListChangedNotification(method=method)
            elif method == "notifications/prompts/list_changed":
                notification = types.PromptListChangedNotification(method=method)
            elif method == "notifications/resources/list_changed":
                notification = types.ResourceListChangedNotification(method=method)
            elif method == "notifications/resources/updated":
                notification = types.ResourceUpdatedNotification(
                    method=method, params=params if params else None
                )
            elif method == "notifications/cancelled":
                notification = types.CancelledNotification(
                    method=method, params=params if params else None
                )
            elif method == "notifications/initialized":
                notification = types.InitializedNotification(method=method)
            elif method == "notifications/message":
                notification = types.LoggingMessageNotification(
                    method=method, params=params if params else None
                )
            else:
                # Fallback for any other valid notifications
                notification = types.JSONRPCNotification(
                    jsonrpc="2.0", method=method, params=params
                )

            await self.server_session.send_notification(notification)
            logger.info("Forwarded %s to upstream client", method)
        except McpError as e:
            logger.warning("Failed to forward %s notification: %s", method, e)

    async def _handle_client_message(
        self,
        message: (
            RequestResponder[types.ServerRequest, types.ClientResult]
            | types.ServerNotification
            | Exception
        ),
    ) -> None:
        """Message handler for the ClientSession to process notifications.

        Args:
        ----
            message: The message from the server, can be a notification or other message type

        """
        if isinstance(message, types.ServerNotification):
            spec_compliant_notifications = {
                "notifications/tools/list_changed",
                "notifications/prompts/list_changed",
                "notifications/resources/list_changed",
                "notifications/progress",
                "notifications/message",
                "notifications/resources/updated",
                "notifications/cancelled",
                "notifications/initialized",
            }

            method = message.root.method
            params = message.root.params
            task: asyncio.Task[Any] | None = None

            if method == "notifications/tools/list_changed":
                self.config_approved = False
                logger.info("Tool list changed - invalidating config approval")
                # Schedule tool update as a separate task to avoid deadlock with message handler
                self._task = asyncio.create_task(self.update_tools_and_notify())
                await self._forward_notification_to_upstream(
                    method, params.model_dump() if params else None
                )
            elif method == "notifications/prompts/list_changed":
                # Prompt changes do NOT affect the config approval status
                logger.info(
                    "Received notification that prompts have changed "
                    "(not affecting approval status)"
                )
                # Simply forward the notification - no caching needed for prompts
                await self._forward_notification_to_upstream(
                    method, params.model_dump() if params else None
                )
            elif method == "notifications/resources/list_changed":
                # Resource changes do NOT affect the config approval status
                logger.info(
                    "Received notification that resources have changed "
                    "(not affecting approval status)"
                )
                # Simply forward the notification - no caching needed for resources
                await self._forward_notification_to_upstream(
                    method, params.model_dump() if params else None
                )
            elif method in spec_compliant_notifications:
                # Forward other specification-compliant notifications to upstream client
                logger.info("Forwarding notification to upstream client: %s", method)
                await self._forward_notification_to_upstream(
                    method, params.model_dump() if params else None
                )
            else:
                # Discard non-specification notifications
                logger.info("Discarding non-specification notification: %s", method)

            if task is not None:
                task.add_done_callback(self.tasks.discard)
                self.tasks.add(task)
        else:
            logger.info("Received non-notification message: %s", type(message))

    async def update_tools(self) -> None:
        """Update tools from the downstream server."""
        if self.session is None:
            raise ChildServerNotConnectedError
        try:
            downstream_tools = await self.session.list_tools()

            if not downstream_tools.tools:
                msg = "No tools received from downstream server"
                raise ValueError(msg)
            logger.info("Received %d tools after update notification", len(downstream_tools.tools))

            await self._handle_tool_updates(downstream_tools.tools)
        except McpError as e:
            logger.warning("Error handling tool update notification: %s", e)

    async def update_tools_and_notify(self) -> None:
        """Update tools from the downstream server and send a notification to the client."""
        await self.update_tools()
        await self._forward_notification_to_upstream("notifications/tools/list_changed", None)

    async def connect(self) -> None:
        """Initialize the connection to the downstream server."""
        if self.connection_type == "stdio":
            await self._connect_via_stdio()
        elif self.connection_type == "http":
            await self._connect_via_streamable_http()
        elif self.connection_type == "sse":
            await self._connect_via_http()
        await self._initialize_config()

    async def _initialize_config(self) -> None:
        """Complete setup after connecting to a downstream server."""
        if self.session is None:
            raise ChildServerNotConnectedError

        self.initialize_result = await self.session.initialize()

        downstream_tools = await self.session.list_tools()
        if not downstream_tools.tools:
            msg = "No tools received from downstream server during initialization"
            raise ValueError(msg)

        self.tool_specs = self._convert_mcp_tools_to_specs(downstream_tools.tools)

        try:
            downstream_prompts = await self.session.list_prompts()
            if downstream_prompts and downstream_prompts.prompts:
                logger.info(
                    "Received %d prompts during initialization", len(downstream_prompts.prompts)
                )
        except McpError as e:
            logger.info("Downstream server does not support prompts: %s", e)

        try:
            downstream_resources = await self.session.list_resources()
            if downstream_resources and downstream_resources.resources:
                logger.info(
                    "Received %d resources during initialization",
                    len(downstream_resources.resources),
                )
        except McpError as e:
            logger.info("Downstream server does not support resources: %s", e)

        self.current_config = self._create_server_config()

        # Get granular approval status using the new system
        self.approval_status = self.config_db.get_server_approval_status(
            self.connection_type, self.get_server_identifier(), self.current_config
        )

        if self.approval_status["is_new_server"]:
            logger.info("New server detected - saving as unapproved")
            # Save the config as unapproved for later review
            self.config_db.save_unapproved_config(
                self.connection_type, self.get_server_identifier(), self.current_config
            )
            self.config_approved = False
        elif not self.approval_status["instructions_approved"]:
            logger.info("Server instructions have changed - server blocked until re-approval")
            # Save the updated config as unapproved
            self.config_db.save_unapproved_config(
                self.connection_type, self.get_server_identifier(), self.current_config
            )
            self.config_approved = False
        else:
            # Instructions are approved, check if we have any approved tools
            approved_tool_count = sum(
                1 for approved in self.approval_status["tools"].values() if approved
            )
            total_tool_count = len(self.approval_status["tools"])

            if approved_tool_count > 0:
                logger.info(
                    "Server partially approved - %d/%d tools approved",
                    approved_tool_count,
                    total_tool_count,
                )
                self.config_approved = True  # Allow partial operation
            else:
                logger.info("Server instructions approved but no tools approved yet")
                self.config_approved = False

    def get_server_identifier(self) -> str:
        """Get the server identifier for database storage."""
        if self.connection_type == "stdio" and self.child_command is not None:
            return self.child_command
        if self.connection_type in ["http", "sse"] and self.server_url is not None:
            return str(self.server_url)
        error_msg = f"Unknown connection type: {self.connection_type}"
        raise ValueError(error_msg)

    async def _connect_via_stdio(self) -> None:
        """Connect to a downstream server via stdio."""
        if self.child_command is None:
            raise ValueError("child_command must be set for stdio connection")

        logger.info("Connecting to downstream server via stdio: %s", self.child_command)

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        try:
            if self.child_command.startswith('"') and self.child_command.endswith('"'):
                self.child_command = self.child_command[1:-1]

            self.server_identifier = self.child_command

            self.saved_config = self.config_db.get_server_config("stdio", self.server_identifier)

            command_parts = self.child_command.split()
            if not command_parts:
                msg = "Invalid command"
                raise ValueError(msg)

            server_params = StdioServerParameters(
                command=command_parts[0],
                args=command_parts[1:] if len(command_parts) > 1 else [],
            )

            logger.info(
                "Starting downstream server with command: %s %s",
                command_parts[0],
                " ".join(command_parts[1:]),
            )
            self.client_context = stdio_client(server_params)
            self.streams = await self.client_context.__aenter__()

            self.session = await ClientSession(
                self.streams[0],
                self.streams[1],
                message_handler=self._handle_client_message,
            ).__aenter__()

        except McpError:
            logger.exception("Error connecting to downstream server via stdio")
            raise

    async def _connect_via_http(self) -> None:
        """Connect to a downstream server via SSE (Server-Sent Events)."""
        if self.server_url is None:
            raise ValueError("server_url must be set for SSE connection")

        logger.info("Connecting to downstream server via SSE: %s", self.server_url)

        # Set up imports
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        try:
            logger.info("Connecting to SSE server at %s", self.server_url)

            self.server_identifier = str(self.server_url)

            self.saved_config = self.config_db.get_server_config("sse", self.server_identifier)

            # Add MCP-Protocol-Version header for SSE client
            headers = {"MCP-Protocol-Version": "2025-06-18"}
            self.client_context = sse_client(str(self.server_url), headers=headers)
            self.streams = await self.client_context.__aenter__()

            self.session = await ClientSession(
                self.streams[0],
                self.streams[1],
                message_handler=self._handle_client_message,
            ).__aenter__()

        except McpError:
            logger.exception("Error connecting to downstream server via SSE")
            raise

    async def _connect_via_streamable_http(self) -> None:
        """Connect to a downstream server via streamable HTTP."""
        if self.server_url is None:
            raise ValueError("server_url must be set for streamable HTTP connection")

        logger.info("Connecting to downstream server via streamable HTTP: %s", self.server_url)

        # Set up imports
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        try:
            logger.info("Connecting to streamable HTTP server at %s", self.server_url)

            self.server_identifier = str(self.server_url)

            self.saved_config = self.config_db.get_server_config("http", self.server_identifier)

            # Add MCP-Protocol-Version header for streamable HTTP client
            headers = {"MCP-Protocol-Version": "2025-06-18"}
            self.client_context = streamablehttp_client(self.server_url, headers=headers)
            streams_and_session_id = await self.client_context.__aenter__()
            self.streams = (streams_and_session_id[0], streams_and_session_id[1])

            self.session = await ClientSession(
                self.streams[0],
                self.streams[1],
                message_handler=self._handle_client_message,
            ).__aenter__()

        except Exception:
            logger.exception("Error connecting to downstream server via streamable HTTP")
            raise

    def _create_server_config(self) -> MCPServerConfig:
        """Create a server configuration from the tool specs."""
        config = MCPServerConfig()

        if self.initialize_result and hasattr(self.initialize_result, "instructions"):
            # Handle None instructions
            config.instructions = self.initialize_result.instructions or ""

        for spec in self.tool_specs:
            parameters = []

            for param_name, param_info in spec.parameters.items():
                param_type = ParameterType.STRING  # Default type

                # Try to determine the parameter type based on the schema
                schema = param_info.get("schema", {})
                schema_type = schema.get("type", "string")

                if schema_type == "string":
                    param_type = ParameterType.STRING
                elif schema_type in ["number", "integer"]:
                    param_type = ParameterType.NUMBER
                elif schema_type == "boolean":
                    param_type = ParameterType.BOOLEAN
                elif schema_type == "array":
                    param_type = ParameterType.ARRAY
                elif schema_type == "object":
                    param_type = ParameterType.OBJECT

                param = MCPParameterDefinition(
                    name=param_name,
                    description=param_info.get("description", ""),
                    type=param_type,
                    required="required" in schema or param_name in spec.required,
                    default=schema.get("default"),
                    enum=schema.get("enum"),
                    items=schema.get("items"),
                    properties=schema.get("properties"),
                )
                parameters.append(param)

            tool = MCPToolDefinition(
                name=spec.name,
                description=spec.description,
                parameters=parameters,
                output_schema=spec.output_schema,
            )

            config.add_tool(tool)

        return config

    def _setup_notification_handlers(self) -> None:
        """Install handlers for client → server notifications to forward to downstream server."""

        @self.server.progress_notification()
        async def handle_progress_notification(notification: types.ProgressNotification) -> None:
            """Forward progress notifications from upstream client to downstream server."""
            logger.info("Forwarding progress notification from client to downstream server")

            if self.session:
                await self._forward_notification_to_downstream(notification)

        # Handle other client notifications by registering them manually
        # Since there may not be decorators for all notification types, we'll register directly

        async def handle_cancelled_notification(
            notification: types.CancelledNotification,
        ) -> None:
            """Forward cancelled notifications from upstream client to downstream server."""
            logger.info("Forwarding cancelled notification from client to downstream server")

            if self.session:
                try:
                    await self._forward_notification_to_downstream(notification)
                except Exception as e:
                    logger.warning("Failed to forward cancelled notification to downstream: %s", e)

        async def handle_initialized_notification(
            notification: types.InitializedNotification,
        ) -> None:
            """Forward initialized notifications from upstream client to downstream server."""
            logger.info("Forwarding initialized notification from client to downstream server")

            if self.session:
                try:
                    await self._forward_notification_to_downstream(notification)
                except Exception as e:
                    logger.warning(
                        "Failed to forward initialized notification to downstream: %s",
                        e,
                    )

        # Register the handlers manually in the notification_handlers dict
        self.server.notification_handlers[types.CancelledNotification] = (
            handle_cancelled_notification
        )
        self.server.notification_handlers[types.InitializedNotification] = (
            handle_initialized_notification
        )

    async def _forward_notification_to_downstream(
        self,
        notification: types.CancelledNotification
        | types.InitializedNotification
        | types.ProgressNotification,
    ) -> None:
        """Forward a notification from upstream client to downstream server."""
        if not self.session:
            logger.warning("No downstream session available to forward notification")
            return

        try:
            # Create a clean notification without the jsonrpc field to avoid conflicts
            # when send_notification adds its own jsonrpc="2.0"
            notification_data = notification.model_dump(exclude={"jsonrpc"})
            clean_notification = type(notification)(**notification_data)

            await self.session.send_notification(clean_notification)  # type: ignore[arg-type]
            logger.info(
                "Successfully forwarded notification %s to downstream server", notification.method
            )
        except McpError:
            logger.exception("Error forwarding notification %s to downstream", notification.method)

    def _make_ansi_escape_codes_visible(self, text: str) -> str:
        """Convert ANSI escape sequences to visible text by replacing escape character with "ESC".

        This makes ANSI color codes and other terminal control sequences visible in the text
        instead of being interpreted by the terminal.

        Args:
        ----
            text: The text that may contain ANSI escape sequences

        Returns:
        -------
            Text with ANSI escape sequences made visible

        """
        if not self.visualize_ansi_codes:
            return text

        return _make_ansi_escape_codes_visible_str(text)

    def _scan_tool_response(
        self, tool_name: str, tool_input: dict[str, Any], tool_output: str
    ) -> GuardrailAlert | None:
        """Scan a tool response with the configured guardrail provider.

        Args:
        ----
            tool_name: The name of the tool that was called
            tool_input: The input parameters to the tool
            tool_output: The output returned by the tool

        Returns:
        -------
            Optional GuardrailAlert if the guardrail is triggered, None otherwise

        """
        if not self.use_guardrails or self.guardrail_provider is None:
            return None

        try:
            logger.info(
                "Scanning tool response for '%s' with %s", tool_name, self.guardrail_provider.name
            )

            tool_response = ToolResponse(
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output=tool_output,
                context={},  # Could be extended with additional context in the future
            )

            alert = self.guardrail_provider.check_tool_response(tool_response)

            if alert:
                logger.warning(
                    "Guardrail alert triggered for tool '%s': %s", tool_name, alert.explanation
                )
        except Exception:
            logger.exception("Error scanning tool response")
            return None
        return alert

    async def stop_child_process(self) -> None:
        """Close connections to the downstream server."""
        if self.client_context:
            try:
                # The cleanup is the same regardless of connection type
                await self.client_context.__aexit__(None, None, None)
                self.client_context = None
                self.session = None
                self.streams = None
                self.child_process = None
                logger.info("Closed MCP client connection (type: %s)", self.connection_type)

                # Add a brief delay to ensure subprocess cleanup is complete
                # This prevents race conditions in tests where multiple wrapper instances
                # are created and destroyed rapidly
                import asyncio

                await asyncio.sleep(0.1)

            except RuntimeError as e:
                if "cancel scope" in str(e):
                    # Context was already cancelled (e.g., by timeout), just clean up state
                    self.client_context = None
                    self.session = None
                    self.streams = None
                    self.child_process = None
                    logger.info("MCP client connection was cancelled, cleaned up state")
                else:
                    logger.exception("Runtime error closing MCP client")
            except Exception:
                logger.exception("Error closing MCP client")

    async def run(self) -> None:
        """Run the MCP wrapper server using stdio."""
        await self.connect()

        try:
            from contextlib import AsyncExitStack

            import anyio
            from mcp.server.session import ServerSession
            from mcp.server.stdio import stdio_server

            async with stdio_server() as streams:
                init_options = InitializationOptions(
                    server_name="mcp_wrapper",
                    server_version="0.1.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(
                            tools_changed=True,
                            prompts_changed=True,
                            resources_changed=True,
                        ),
                        experimental_capabilities={},
                    ),
                )

                async with AsyncExitStack() as stack:
                    # Create and store the server session
                    self.server_session = await stack.enter_async_context(
                        ServerSession(
                            streams[0],
                            streams[1],
                            init_options,
                        )
                    )

                    # Process incoming messages
                    async with anyio.create_task_group() as tg:
                        async for message in self.server_session.incoming_messages:
                            tg.start_soon(
                                self.server._handle_message,
                                message,
                                self.server_session,
                                None,  # No lifespan context needed
                            )
        finally:
            await self.stop_child_process()


def _make_ansi_escape_codes_visible_str(text: str) -> str:
    r"""Neutralize ANSI escape codes in a string.

    Replace the escape character (ASCII 27, typically \x1b or \033) with "ESC"
    This will convert escape sequences like "\x1b[31m" (red text) to "ESC[31m"
    making them visible instead of changing the terminal colors.

    Args:
    ----
        text: String to process

    Returns:
    -------
        String with ANSI escape codes made visible

    """
    return re.sub(r"\x1b", "ESC", text)


def make_ansi_escape_codes_visible(
    content: str | types.TextContent | types.ImageContent | types.EmbeddedResource,
) -> str | types.TextContent | types.ImageContent | types.EmbeddedResource:
    r"""Neutralize ANSI escape codes.

    Replace the escape character (ASCII 27, typically \x1b or \033) with "ESC"
    This will convert escape sequences like "\x1b[31m" (red text) to "ESC[31m"
    making them visible instead of changing the terminal colors.

    Args:
    ----
        content: String or content object to process

    Returns:
    -------
        Same type as input with ANSI escape codes made visible in text content

    """
    if isinstance(content, str):
        return _make_ansi_escape_codes_visible_str(content)
    elif isinstance(content, types.TextContent):
        processed_text = _make_ansi_escape_codes_visible_str(content.text)
        return types.TextContent(type="text", text=processed_text, annotations=content.annotations)
    else:
        # For ImageContent and EmbeddedResource, return unchanged
        return content
