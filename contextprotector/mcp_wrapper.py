#!/usr/bin/env python3
import asyncio
import base64
import logging
import json
import re
from typing import List, Optional, Literal, Dict, Any

import mcp.types as types
from mcp.server.lowlevel import Server, NotificationOptions
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.models import InitializationOptions

# Import guardrail types for type hints
from .guardrail_types import GuardrailProvider, GuardrailAlert, ToolResponse

# Import quarantine functionality
from .quarantine import ToolResponseQuarantine

from .mcp_config import (
    MCPServerConfig,
    MCPToolSpec,
    MCPToolDefinition,
    MCPParameterDefinition,
    ParameterType,
    MCPConfigDatabase,
)

logger = logging.getLogger("mcp_wrapper")


class MCPWrapperServer:
    @classmethod
    def wrap_stdio(
        cls,
        command: str,
        config_path: str = None,
        guardrail_provider: Optional[GuardrailProvider] = None,
        visualize_ansi_codes: bool = False,
        quarantine_path: str = None,
    ):
        """
        Create a wrapper server that connects to a child process via stdio.

        Args:
            command: The command to run as a child process
            config_path: Optional path to the wrapper config file
            guardrail_provider: Optional guardrail provider object to use
            visualize_ansi_codes: Whether to make ANSI escape codes visible in tool outputs

        Returns:
            An instance of MCPWrapperServer configured for stdio
        """
        instance = cls(
            config_path, guardrail_provider, visualize_ansi_codes, quarantine_path
        )
        instance.connection_type = "stdio"
        instance.child_command = command
        return instance

    @classmethod
    def wrap_http(
        cls,
        url: str,
        config_path: str = None,
        guardrail_provider: Optional[GuardrailProvider] = None,
        visualize_ansi_codes: bool = False,
        quarantine_path: str = None,
    ):
        """
        Create a wrapper server that connects to a remote MCP server via HTTP.

        Args:
            url: The URL to connect to for a remote MCP server
            config_path: Optional path to the wrapper config file
            guardrail_provider: Optional guardrail provider object to use
            visualize_ansi_codes: Whether to make ANSI escape codes visible in tool outputs

        Returns:
            An instance of MCPWrapperServer configured for HTTP
        """
        instance = cls(
            config_path, guardrail_provider, visualize_ansi_codes, quarantine_path
        )
        instance.connection_type = "http"
        instance.server_url = url
        return instance

    def __init__(
        self,
        config_path: str = None,
        guardrail_provider: Optional[GuardrailProvider] = None,
        visualize_ansi_codes: bool = False,
        quarantine_path: str = None,
    ):
        """
        Initialize the wrapper server with common attributes.
        Use wrap_stdio or wrap_http class methods instead of calling this directly.

        Args:
            config_path: Optional path to the wrapper config file
            guardrail_provider: Optional guardrail provider object to use for checking configs
            visualize_ansi_codes: Whether to make ANSI escape codes visible in tool outputs
            quarantine_path: Optional path to the quarantine database file
        """
        self.child_command = None
        self.server_url = None
        self.connection_type = None
        self.server_identifier = None # Will be set after determining connection details
        self.child_process = None
        self.client_context = None
        self.streams = None
        self.session = None
        self.initialize_result = None
        self.tool_specs = []
        self.config_approved = False
        self.config_db = MCPConfigDatabase(config_path)
        self.saved_config = None  # Will be loaded after server_identifier is set
        self.current_config = MCPServerConfig()
        self.server = Server("mcp_wrapper")
        self.guardrail_provider = guardrail_provider
        self.use_guardrails = guardrail_provider is not None
        self.visualize_ansi_codes = visualize_ansi_codes
        self.prompts = []
        self.resources = []
        self.quarantine = (
            ToolResponseQuarantine(quarantine_path) if self.use_guardrails else None
        )
        self._setup_handlers()

    def _setup_handlers(self):
        """Setup MCP server handlers"""

        @self.server.list_prompts()
        async def list_prompts() -> List[types.Prompt]:
            """
            Return prompts from the downstream server, or an empty list if server config is not approved.
            When config isn't approved, we don't reveal any prompts to clients.
            """
            if not self.config_approved:
                logger.warning(
                    "Blocking list_prompts - server configuration not approved"
                )
                return []

            return self.prompts

        @self.server.list_resources()
        async def list_resources() -> List[types.Resource]:
            """
            Return resources from the downstream server.
            Unlike prompts and tools, resources are always available regardless of config approval.
            """
            logger.info(f"Returning {len(self.resources)} resources to upstream client")
            return self.resources

        @self.server.read_resource()
        async def read_resource(name: str) -> types.ReadResourceResult:
            """
            Handle resource content requests - proxy directly to downstream server.
            Resources are always accessible regardless of server config approval status.

            Args:
                name: The name/id of the resource

            Returns:
                The resource content from the downstream server
            """
            logger.info(f"Proxying resource request: {name}")

            if not self.session:
                raise ValueError("Child MCP server not connected")

            try:
                # Directly proxy the resource request to the downstream server
                result = await self.session.read_resource(name)
                contents = []
                for content_item in result.contents:
                    content = getattr(content_item, "blob", None)
                    if content is not None:
                        content = base64.b64decode(content)
                        contents.append(
                            ReadResourceContents(
                                content=content, mime_type=content_item.mimeType
                            )
                        )
                        assert isinstance(contents[-1].content, bytes), (
                            f"type {type(contents[-1].content)} value {content} is not bytes"
                        )
                    else:
                        contents.append(
                            ReadResourceContents(
                                content=content_item.text,
                                mime_type=content_item.mimeType,
                            )
                        )

                logger.info(f"Successfully fetched resource {name} from downstream server")
                return contents
            except Exception as e:
                logger.error(f"Error fetching resource {name} from downstream server: {e}")
                raise ValueError(f"Error fetching resource from downstream server: {str(e)}")

        @self.server.list_tools()
        async def list_tools() -> List[types.Tool]:
            """Return tool specs from the child MCP server and add wrapper-specific tools."""
            all_tools = []

            for spec in self.tool_specs:
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

            # Add quarantine_release tool if quarantine is enabled
            if self.use_guardrails and self.quarantine:
                quarantine_release_tool = types.Tool(
                    name="quarantine_release",
                    description="Release a quarantined tool response for review",
                    inputSchema={
                        "type": "object",
                        "required": ["uuid"],
                        "properties": {
                            "uuid": {
                                "type": "string",
                                "description": "UUID of the quarantined tool response to release",
                            }
                        },
                    },
                )
                all_tools.append(quarantine_release_tool)

            return all_tools

        @self.server.get_prompt()
        async def get_prompt(name: str, arguments: dict) -> List[types.TextContent]:
            """
            Handle prompt dispatch requests - proxy to downstream server if config is approved.
            If the server config isn't approved, return an empty message list.
            """
            logger.info(
                f"Prompt dispatch with name {name} and config_approved {self.config_approved}"
            )

            if not self.config_approved:
                logger.warning(f"Blocking prompt '{name}' - server configuration not approved")

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
                            content.content = make_ansi_escape_codes_visible(
                                content.content
                            )
                        text_parts.append(content.content)

                return types.GetPromptResult(
                    description=result.description,
                    messages=[
                        types.PromptMessage(role="user", content=text)
                        for text in text_parts
                    ],
                )

            except Exception as e:
                logger.error(
                    f"Error from downstream server during prompt dispatch:\n\n---\n\n{e}\n\n---\n\n"
                )
                raise ValueError(f"Error from downstream server: {str(e)}")

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> List[types.TextContent]:
            """
            Handle tool use requests - either approve config, proxy to downstream server,
            handle quarantine release, or block if config not approved.
            """
            logger.info(
                f"Tool call with name {name} and config_approved {self.config_approved}"
            )

            if name == "quarantine_release" and self.use_guardrails and self.quarantine:
                return await self._handle_quarantine_release(arguments)

            if not self.session:
                raise ValueError("Child MCP server not connected")

            if not self.config_approved:
                logger.warning(
                    f"Blocking tool '{name}' - server configuration not approved"
                )

                self.current_config = self._create_server_config()

                # Create diff if we have a saved config to compare against
                diff_text = "New server - no previous configuration to compare"
                if self.saved_config:
                    diff = self.saved_config.compare(self.current_config)
                    if diff.has_differences():
                        diff_text = str(diff)
                    else:
                        diff_text = "No differences found (configs are identical)"

                serialized_config = self.current_config.to_json()

                blocked_response = {
                    "status": "blocked",
                    "server_config": serialized_config,
                    "diff": diff_text,
                    "reason": "Server configuration not approved - all tools blocked",
                }

                error_json = json.dumps(blocked_response)
                raise ValueError(error_json)

            # If we get here, config is approved, so proxy the tool call
            try:
                tool_result = await self._proxy_tool_to_downstream(name, arguments)

                # If tool_result is a dict with structured content, handle it properly
                if (
                    isinstance(tool_result, dict)
                    and "structured_content" in tool_result
                ):
                    # Check if we have non-text content that needs to be preserved
                    has_non_text_content = False
                    if "content_list" in tool_result and tool_result["content_list"]:
                        has_non_text_content = any(c.type != "text" for c in tool_result["content_list"])
                    
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
                    if tool_result["structured_content"] is not None:
                        return types.CallToolResult(
                            content=content,
                            structuredContent=tool_result["structured_content"],
                        )
                    else:
                        # For backward compatibility, return content list or text
                        return content if isinstance(content, list) else [content]
                else:
                    # Legacy text-only response (backward compatibility)
                    wrapped_response = {"status": "completed", "response": tool_result}
                    json_response = json.dumps(wrapped_response)
                    return [types.TextContent(type="text", text=json_response)]

            except Exception as e:
                logger.error(f"Error from child MCP server: {e}")
                raise ValueError(f"Error from child MCP server: {str(e)}")

    async def _handle_quarantine_release(
        self, arguments: Dict[str, Any]
    ) -> List[types.TextContent]:
        """
        Handle the quarantine_release tool call.

        Args:
            arguments: The tool arguments containing the UUID of the quarantined response

        Returns:
            The original tool response if found and available for release

        Raises:
            ValueError: If the UUID is invalid or not found, or if the response is not available for release
        """
        if "uuid" not in arguments:
            raise ValueError(
                "Missing required parameter 'uuid' for quarantine_release tool"
            )

        response_id = arguments["uuid"]
        logger.info(f"Processing quarantine_release request for UUID: {response_id}")

        quarantined_response = self.quarantine.get_response(response_id)

        if not quarantined_response:
            raise ValueError(f"No quarantined response found with UUID: {response_id}")

        if quarantined_response.released:
            original_tool_info = {
                "tool_name": quarantined_response.tool_name,
                "tool_input": quarantined_response.tool_input,
                "tool_output": quarantined_response.tool_output,
                "quarantine_reason": quarantined_response.reason,
                "quarantine_id": quarantined_response.id,
            }

            self.quarantine.delete_response(response_id)
            logger.info(
                f"Released response {response_id} from quarantine and deleted it"
            )

            json_response = json.dumps(original_tool_info)
            wrapped_response = {"status": "completed", "response": json_response}
            final_response = json.dumps(wrapped_response)
            return [types.TextContent(type="text", text=final_response)]
        else:
            raise ValueError(
                f"Response {response_id} is not marked for release. "
                f"Please use the CLI to review and release it first: "
                f"python -m contextprotector --review-quarantine --quarantine-id {response_id}"
            )

    async def _proxy_tool_to_downstream(self, name: str, arguments: dict) -> str:
        """Proxy a tool call to the downstream server using MCP client"""
        if not self.session:
            raise ValueError("No client connection to downstream server")

        try:
            logger.info(
                f"Forwarding tool call to downstream: {name} with args {arguments}"
            )
            result = await self.session.call_tool(name, arguments)

            # Extract content, structured content, and preserve all content types
            response_text = ""
            structured_content = None
            processed_content = []

            if result and len(result.content) > 0:
                # Process all content types, preserving non-text content like EmbeddedResource
                text_parts = []
                for content in result.content:
                    if content.type == "text" and content.text:
                        # Apply ANSI escape code processing if enabled
                        processed_text = self._make_ansi_escape_codes_visible(
                            content.text
                        )
                        text_parts.append(processed_text)
                        # Create processed text content for the response
                        processed_content.append(types.TextContent(type="text", text=processed_text))
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

            # Check if response_text is already valid JSON (from FastMCP tools)
            # If so, we should not double-wrap it in our legacy format
            try:
                json.loads(response_text)
                is_json_response = True
            except (json.JSONDecodeError, TypeError):
                is_json_response = False

            # Scan the tool response with guardrail provider if configured
            if self.use_guardrails and self.guardrail_provider is not None:
                guardrail_alert = self._scan_tool_response(
                    name, arguments, response_text
                )
                if guardrail_alert:
                    # Log the alert but don't block the response yet
                    logger.error(
                        f"Guardrail alert triggered for tool '{name}': {guardrail_alert.explanation}"
                    )
                    # Store in quarantine for future reference (when quarantine system is integrated)
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
            return self._create_tool_response(
                response_text, structured_content, processed_content, is_json_response
            )

        except Exception as e:
            logger.error(f"Error calling downstream tool '{name}': {e}")
            raise ValueError(f"Error calling downstream tool: {str(e)}")

    def _create_tool_response(
        self,
        response_text: str,
        structured_content: Optional[Dict[str, Any]],
        content_list: List[types.Content],
        is_json_response: bool = False,
    ) -> Dict[str, Any]:
        """Create a tool response dict with text, structured content, and all content types."""
        return {
            "text": response_text,
            "structured_content": structured_content,
            "content_list": content_list,
            "is_json_response": is_json_response,
        }

    def _guardrail_tool_response(
        self,
        tool_name: str,
        arguments: dict,
        response_text: str,
        guardrail_alert: GuardrailAlert,
        quarantine_id: Optional[str],
    ) -> str:
        """Generates the response message sent to the client when a tool response is blocked by a guardrail."""

        return f"""
        This tool call was quarantined because it appears to contain a prompt injection attack.

        Tool name: {tool_name}
        Arguments: {json.dumps(arguments, indent=2)}
        Alert explanation: {guardrail_alert.explanation}

        To review this response and release it from the quarantine, run contextprotector with the arguments `--review-quarantine{" --quarantine-id " + quarantine_id if quarantine_id else ""}`.
        """

    def _convert_parameters_to_schema(
        self, parameters: dict, required: List[str]
    ) -> dict:
        """Convert parameters format to JSON Schema for MCP Tool"""
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

    def _convert_mcp_tools_to_specs(self, tools):
        """
        Convert MCP tool definitions to internal tool specs.

        Args:
            tools: List of MCP tool definitions

        Returns:
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
                description=tool.description,
                parameters=parameters,
                required=required,
                output_schema=output_schema,
            )

            tool_specs.append(tool_spec)

        return tool_specs

    async def _handle_tool_updates(self, tools):
        """
        Handle tool update notifications from the downstream server.

        Args:
            tools: Updated list of tools from the downstream server
        """
        self.tool_specs = self._convert_mcp_tools_to_specs(tools)

        # Temporarily reset approval while we check if the config has changed
        self.config_approved = False

        old_config = self.current_config
        self.current_config = self._create_server_config()

        # If tools have changed, check against the saved config (if any)
        if old_config != self.current_config:
            diff = old_config.compare(self.current_config)
            if diff.has_differences():
                logger.warning(f"Configuration differences: {diff}")

            if self.saved_config and self.saved_config == self.current_config:
                logger.info("Tools changed but match saved approved configuration")
                self.config_approved = True
            else:
                logger.warning("Tools changed, requiring re-approval")

        else:
            logger.info("Tools updated but configuration unchanged")
            self.config_approved = True

    async def _handle_client_message(self, message):
        """
        Message handler for the ClientSession to process notifications,
        particularly tool update notifications.

        Args:
            message: The message from the server, can be a notification or other message type
        """
        if isinstance(message, types.ServerNotification):
            if message.root.method == "notifications/tools/list_changed":
                self.config_approved = False
                asyncio.create_task(self.update_tools())
            elif message.root.method == "notifications/prompts/list_changed":
                # Prompt changes do NOT affect the config approval status
                logger.info(
                    "Received notification that prompts have changed (not affecting approval status)"
                )
                asyncio.create_task(self.update_prompts())
            elif message.root.method == "notifications/resources/list_changed":
                # Resource changes do NOT affect the config approval status
                logger.info(
                    "Received notification that resources have changed (not affecting approval status)"
                )
                asyncio.create_task(self.update_resources())
            else:
                logger.info(f"Received notification: {message.method}")
        else:
            logger.info(f"Received non-notification message: {type(message)}")

    async def update_prompts(self):
        """
        Update prompts from the downstream server.

        Important: This method updates the available prompts but does NOT affect
        the server configuration approval status. Prompts are not considered part
        of the server configuration for approval purposes.
        """
        try:
            downstream_prompts = await self.session.list_prompts()

            if downstream_prompts and downstream_prompts.prompts:
                old_prompt_count = len(self.prompts)
                self.prompts = downstream_prompts.prompts
                new_prompt_count = len(self.prompts)
                logger.info(
                    f"Updated prompts from downstream server (old: {old_prompt_count}, new: {new_prompt_count})"
                )
                logger.info(
                    "Note: Prompt changes do not affect server configuration approval status"
                )
            else:
                logger.info("No prompts available from downstream server")
                self.prompts = []
        except Exception as e:
            logger.warning(f"Error updating prompts from downstream server: {e}")

    async def update_resources(self):
        """
        Update resources from the downstream server.

        Important: This method updates the available resources but does NOT affect
        the server configuration approval status. Resources are not considered part
        of the server configuration for approval purposes.
        """
        try:
            downstream_resources = await self.session.list_resources()

            if downstream_resources and downstream_resources.resources:
                old_resource_count = len(self.resources)
                self.resources = downstream_resources.resources
                new_resource_count = len(self.resources)
                logger.info(
                    f"Updated resources from downstream server (old: {old_resource_count}, new: {new_resource_count})"
                )
                logger.info(
                    "Note: Resource changes do not affect server configuration approval status"
                )

                await self.server.send_resource_list_changed()
            else:
                logger.info("No resources available from downstream server")
                self.resources = []
        except Exception as e:
            logger.warning(f"Error updating resources from downstream server: {e}")

    async def update_tools(self):
        """Update tools from the downstream server."""
        try:
            downstream_tools = await self.session.list_tools()

            assert downstream_tools.tools
            logger.info(
                f"Received {len(downstream_tools.tools)} tools after update notification"
            )

            await self._handle_tool_updates(downstream_tools.tools)
        except Exception as e:
            logger.warning(f"Error handling tool update notification: {e}")

    async def connect(self):
        """Initialize the connection to the downstream server."""
        if self.connection_type == "stdio":
            await self._connect_via_stdio()
        elif self.connection_type == "http":
            await self._connect_via_http()
        else:
            raise ValueError(f"Unknown connection type: {self.connection_type}")
        await self._initialize_config()

    async def _initialize_config(self):
        """Setup tasks after connecting to a downstream server"""
        self.initialize_result = await self.session.initialize()

        downstream_tools = await self.session.list_tools()
        assert downstream_tools.tools

        self.tool_specs = self._convert_mcp_tools_to_specs(downstream_tools.tools)

        self.prompts = []
        try:
            downstream_prompts = await self.session.list_prompts()
            if downstream_prompts and downstream_prompts.prompts:
                self.prompts = downstream_prompts.prompts
                logger.info(
                    f"Received {len(self.prompts)} prompts during initialization"
                )
        except Exception as e:
            logger.info(f"Downstream server does not support prompts: {e}")

        self.resources = []
        try:
            downstream_resources = await self.session.list_resources()
            if downstream_resources and downstream_resources.resources:
                self.resources = downstream_resources.resources
                logger.info(
                    f"Received {len(self.resources)} resources during initialization"
                )
        except Exception as e:
            logger.info(f"Downstream server does not support resources: {e}")

        self.current_config = self._create_server_config()

        if self.saved_config and self.saved_config == self.current_config:
            logger.info(
                "Current configuration matches saved configuration - auto-approving"
            )
            self.config_approved = True
        else:
            if not self.saved_config:
                logger.info("No saved configuration found - approval required")
            else:
                logger.info(
                    "Configuration has changed since last approval - re-approval required"
                )

    async def _connect_via_stdio(self):
        """Connect to a downstream server via stdio."""
        logger.info(f"Connecting to downstream server via stdio: {self.child_command}")

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        try:
            if self.child_command.startswith('"') and self.child_command.endswith('"'):
                self.child_command = self.child_command[1:-1]

            self.server_identifier = self.child_command

            self.saved_config = self.config_db.get_server_config(
                "stdio", self.server_identifier
            )

            command_parts = self.child_command.split()
            if not command_parts:
                raise ValueError("Invalid command")

            server_params = StdioServerParameters(
                command=command_parts[0],
                args=command_parts[1:] if len(command_parts) > 1 else [],
            )

            logger.info(
                f"Starting downstream server with command: {command_parts[0]} {' '.join(command_parts[1:])}"
            )
            self.client_context = stdio_client(server_params)
            self.streams = await self.client_context.__aenter__()

            self.session = await ClientSession(
                self.streams[0],
                self.streams[1],
                message_handler=self._handle_client_message,
            ).__aenter__()

        except Exception as e:
            logger.error(f"Error connecting to downstream server via stdio: {e}")
            raise

    async def _connect_via_http(self):
        """Connect to a downstream server via SSE (Server-Sent Events)."""
        logger.info(f"Connecting to downstream server via SSE: {self.server_url}")

        # Set up imports
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        try:
            logger.info(f"Connecting to SSE server at {self.server_url}")

            self.server_identifier = self.server_url

            self.saved_config = self.config_db.get_server_config(
                "http", self.server_identifier
            )

            # Add MCP-Protocol-Version header for SSE client
            headers = {"MCP-Protocol-Version": "2025-06-18"}
            self.client_context = sse_client(self.server_url, headers=headers)
            self.streams = await self.client_context.__aenter__()

            self.session = await ClientSession(
                self.streams[0],
                self.streams[1],
                message_handler=self._handle_client_message,
            ).__aenter__()

        except Exception as e:
            logger.error(f"Error connecting to downstream server via SSE: {e}")
            raise

    def _create_server_config(self) -> MCPServerConfig:
        """Create a server configuration from the tool specs."""
        config = MCPServerConfig()

        if self.initialize_result and hasattr(self.initialize_result, "instructions"):
            config.instructions = self.initialize_result.instructions

        for spec in self.tool_specs:
            parameters = []

            for param_name, param_info in spec.parameters.items():
                param_type = ParameterType.STRING  # Default type

                # Try to determine the parameter type based on the schema
                schema = param_info.get("schema", {})
                schema_type = schema.get("type", "string")

                if schema_type == "string":
                    param_type = ParameterType.STRING
                elif schema_type == "number" or schema_type == "integer":
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

    def _make_ansi_escape_codes_visible(self, text: str) -> str:
        """
        Convert ANSI escape sequences to visible text by replacing escape character with "ESC".
        This makes ANSI color codes and other terminal control sequences visible in the text
        instead of being interpreted by the terminal.

        Args:
            text: The text that may contain ANSI escape sequences

        Returns:
            Text with ANSI escape sequences made visible
        """
        if not self.visualize_ansi_codes:
            return text

        return make_ansi_escape_codes_visible(text)

    def _print_server_config(self, config: MCPServerConfig):
        """Print the server configuration to stdout."""
        json_str = config.to_json()

        approval_status = "APPROVED" if self.config_approved else "NOT APPROVED"

        print(f"\n==== SERVER CONFIGURATION ({approval_status}) ====")
        print(json_str)
        print("=============================\n")

    def _scan_tool_response(
        self, tool_name: str, tool_input: Dict[str, Any], tool_output: str
    ) -> Optional[GuardrailAlert]:
        """
        Scan a tool response with the configured guardrail provider.

        Args:
            tool_name: The name of the tool that was called
            tool_input: The input parameters to the tool
            tool_output: The output returned by the tool

        Returns:
            Optional GuardrailAlert if the guardrail is triggered, None otherwise
        """
        if not self.use_guardrails or self.guardrail_provider is None:
            return None

        try:
            logger.info(
                f"Scanning tool response for '{tool_name}' with {self.guardrail_provider.name}"
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
                    f"Guardrail alert triggered for tool '{tool_name}': {alert.explanation}"
                )

            return alert

        except Exception as e:
            logger.error(f"Error scanning tool response: {e}", exc_info=True)
            return None

    async def stop_child_process(self):
        """Close connections to the downstream server."""
        if self.client_context:
            try:
                # The cleanup is the same regardless of connection type
                await self.client_context.__aexit__(None, None, None)
                self.client_context = None
                self.session = None
                self.streams = None
                self.child_process = None
                logger.info(
                    f"Closed MCP client connection (type: {self.connection_type})"
                )
            except Exception as e:
                logger.error(f"Error closing MCP client: {e}")

    async def run(self):
        """Run the MCP wrapper server using stdio."""
        await self.connect()

        try:
            from mcp.server.stdio import stdio_server

            async with stdio_server() as streams:
                await self.server.run(
                    streams[0],
                    streams[1],
                    InitializationOptions(
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
                    ),
                )
        finally:
            await self.stop_child_process()


async def review_server_config(
    connection_type: Literal["stdio", "http"],
    identifier: str,
    config_path: Optional[str] = None,
    guardrail_provider: Optional[GuardrailProvider] = None,
    quarantine_path: Optional[str] = None,
) -> None:
    """
    Review and approve server configuration for the given connection.

    This function connects to the downstream server, retrieves its configuration,
    and prompts the user to approve it. If approved, the configuration is saved
    as trusted in the config database.

    Args:
        connection_type: Type of connection ("stdio" or "http")
        identifier: The command or URL to connect to
        config_path: Optional path to config file
        guardrail_provider: Optional guardrail provider to use
        quarantine_path: Optional path to the quarantine database file
    """
    if connection_type == "stdio":
        wrapper = MCPWrapperServer.wrap_stdio(
            command=identifier,
            config_path=config_path,
            guardrail_provider=guardrail_provider,
            quarantine_path=quarantine_path,
        )
    else:  # http
        wrapper = MCPWrapperServer.wrap_http(
            url=identifier,
            config_path=config_path,
            guardrail_provider=guardrail_provider,
            quarantine_path=quarantine_path,
        )

    try:
        await wrapper.connect()

        if wrapper.config_approved:
            print(f"\nServer configuration for {identifier} is already trusted.")
            return

        print(f"\nServer configuration for {identifier} is not trusted or has changed.")

        if wrapper.saved_config:
            print("\nPrevious configuration found. Checking for changes...")

            diff = wrapper.saved_config.compare(wrapper.current_config)
            if diff.has_differences():
                print("\n===== CONFIGURATION DIFFERENCES =====")
                print(make_ansi_escape_codes_visible(str(diff)))
                print("====================================\n")
            else:
                print("No differences found (configs are identical)")
        else:
            print("\nThis appears to be a new server.")

        print("\n===== TOOL LIST =====")
        for tool_spec in wrapper.tool_specs:
            print(
                f"• {tool_spec.name}: {make_ansi_escape_codes_visible(tool_spec.description)}"
            )
        print("=====================\n")

        guardrail_alert = None
        if wrapper.guardrail_provider is not None:
            guardrail_alert = wrapper.guardrail_provider.check_server_config(
                wrapper.current_config
            )

        if guardrail_alert:
            print("\n==== GUARDRAIL CHECK: ALERT ====")
            print(f"Provider: {wrapper.guardrail_provider.name}")
            print(f"Alert: {guardrail_alert.explanation}")
            print("==================================\n")

        response = (
            input("Do you want to trust this server configuration? (yes/no): ")
            .strip()
            .lower()
        )
        if response in ("yes", "y"):
            wrapper.config_db.save_server_config(
                wrapper.connection_type,
                wrapper.server_identifier,
                wrapper.current_config,
            )
            print(
                f"\nThe server configuration for {identifier} has been trusted and saved."
            )
        else:
            print(
                f"\nThe server configuration for {identifier} has NOT been trusted."
            )

    finally:
        # Clean up
        await wrapper.stop_child_process()


def make_ansi_escape_codes_visible(text: str) -> str:
    # Replace the escape character (ASCII 27, typically \x1b or \033) with "ESC"
    # This will convert escape sequences like "\x1b[31m" (red text) to "ESC[31m"
    # making them visible instead of changing the terminal colors
    return re.sub(r"\x1b", "ESC", text)
