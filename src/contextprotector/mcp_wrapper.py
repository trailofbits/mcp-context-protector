#!/usr/bin/env python3
# ruff: noqa: T201
import asyncio
import base64
import logging
import json
import re
import traceback
from typing import List, Literal, Dict, Any

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
    ApprovalStatus,
)

logger = logging.getLogger("mcp_wrapper")


class MCPWrapperServer:
    @classmethod
    def wrap_stdio(
        cls,
        command: str,
        config_path: str = None,
        guardrail_provider: GuardrailProvider | None = None,
        visualize_ansi_codes: bool = False,
        quarantine_path: str = None,
    ):
        """
        Create a wrapper server that connects to a child process via stdio.

        Args:
        ----
            command: The command to run as a child process
            config_path: Optional path to the wrapper config file
            guardrail_provider: Optional guardrail provider object to use
            visualize_ansi_codes: Whether to make ANSI escape codes visible in tool outputs

        Returns:
        -------
            An instance of MCPWrapperServer configured for stdio

        """
        instance = cls(config_path, guardrail_provider, visualize_ansi_codes, quarantine_path)
        instance.connection_type = "stdio"
        instance.child_command = command
        return instance

    @classmethod
    def wrap_http(
        cls,
        url: str,
        config_path: str = None,
        guardrail_provider: GuardrailProvider | None = None,
        visualize_ansi_codes: bool = False,
        quarantine_path: str = None,
    ):
        """
        Create a wrapper server that connects to a remote MCP server via HTTP.

        Args:
        ----
            url: The URL to connect to for a remote MCP server
            config_path: Optional path to the wrapper config file
            guardrail_provider: Optional guardrail provider object to use
            visualize_ansi_codes: Whether to make ANSI escape codes visible in tool outputs

        Returns:
        -------
            An instance of MCPWrapperServer configured for HTTP

        """
        instance = cls(config_path, guardrail_provider, visualize_ansi_codes, quarantine_path)
        instance.connection_type = "sse"
        instance.server_url = url
        return instance

    @classmethod
    def wrap_streamable_http(
        cls,
        url: str,
        config_path: str = None,
        guardrail_provider: GuardrailProvider | None = None,
        visualize_ansi_codes: bool = False,
        quarantine_path: str = None,
    ):
        """
        Create a wrapper server that connects to a remote MCP server via streamable HTTP.

        Args:
        ----
            url: The URL to connect to for a remote MCP server
            config_path: Optional path to the wrapper config file
            guardrail_provider: Optional guardrail provider object to use
            visualize_ansi_codes: Whether to make ANSI escape codes visible in tool outputs

        Returns:
        -------
            An instance of MCPWrapperServer configured for streamable HTTP

        """
        instance = cls(config_path, guardrail_provider, visualize_ansi_codes, quarantine_path)
        instance.connection_type = "http"
        instance.server_url = url
        return instance

    def __init__(
        self,
        config_path: str = None,
        guardrail_provider: GuardrailProvider | None = None,
        visualize_ansi_codes: bool = False,
        quarantine_path: str = None,
    ):
        """
        Initialize the wrapper server with common attributes.
        Use wrap_stdio or wrap_http class methods instead of calling this directly.

        Args:
        ----
            config_path: Optional path to the wrapper config file
            guardrail_provider: Optional guardrail provider object to use for checking configs
            visualize_ansi_codes: Whether to make ANSI escape codes visible in tool outputs
            quarantine_path: Optional path to the quarantine database file

        """
        self.child_command = None
        self.server_url = None
        self.connection_type = None
        self.server_identifier = None  # Will be set after determining connection details
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
        self.server_session = None  # Track the server session for sending notifications
        self.quarantine = ToolResponseQuarantine(quarantine_path) if self.use_guardrails else None
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Setup MCP server handlers"""
        self._setup_notification_handlers()

        @self.server.list_prompts()
        async def list_prompts() -> list[types.Prompt]:
            """
            Return prompts from the downstream server, or an empty list if server config is not approved.
            When config isn't approved, we don't reveal any prompts to clients.
            """
            if not self.config_approved:
                logger.warning("Blocking list_prompts - server configuration not approved")
                return []

            return self.prompts

        @self.server.list_resources()
        async def list_resources() -> list[types.Resource]:
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
            ----
                name: The name/id of the resource

            Returns:
            -------
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
                            ReadResourceContents(content=content, mime_type=content_item.mimeType)
                        )
                        assert isinstance(
                            contents[-1].content, bytes
                        ), f"type {type(contents[-1].content)} value {content} is not bytes"
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

                description = f"Get information about blocked server configuration. {total_tools} tools blocked"
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
                                    "description": "UUID of the quarantined tool response to release",
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
        async def get_prompt(name: str, arguments: dict) -> list[types.TextContent]:
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
                            content.content = make_ansi_escape_codes_visible(content.content)
                        text_parts.append(content.content)

                return types.GetPromptResult(
                    description=result.description,
                    messages=[
                        types.PromptMessage(role="user", content=text) for text in text_parts
                    ],
                )

            except Exception as e:
                logger.error(
                    f"Error from downstream server during prompt dispatch:\n\n---\n\n{e}\n\n---\n\n"
                )
                raise ValueError(f"Error from downstream server: {str(e)}")

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
            """
            Handle tool use requests - either approve config, proxy to downstream server,
            handle quarantine release, or block if config not approved.
            """
            logger.info(f"Tool call with name {name} and config_approved {self.config_approved}")

            # Handle wrapper tools
            if name == "context-protector-block":
                return await self._handle_context_protector_block()

            if name == "quarantine_release" and self.use_guardrails and self.quarantine:
                return await self._handle_quarantine_release(arguments)

            if not self.session:
                raise ValueError("Child MCP server not connected")

            # Check if this specific tool is approved using granular approval system
            if not hasattr(self, "approval_status"):
                logger.warning(f"Blocking tool '{name}' - approval status not initialized")
                blocked_response = {
                    "status": "blocked",
                    "reason": "Server approval status not initialized. Try reconnecting.",
                }
                error_json = json.dumps(blocked_response)
                raise ValueError(error_json)

            # Check if server is completely new or instructions changed
            if self.approval_status.get("is_new_server", False):
                logger.warning(f"Blocking tool '{name}' - new server not approved")
                blocked_response = {
                    "status": "blocked",
                    "reason": "Server configuration not approved. Use the 'context-protector-block' tool for approval instructions.",
                }
                error_json = json.dumps(blocked_response)
                raise ValueError(error_json)

            # Check instructions approval - but differentiate between never-approved and changed instructions
            if not self.approval_status.get("instructions_approved", False):
                if self.approval_status.get("server_approved", False):
                    # Server was previously approved but instructions changed
                    logger.warning(f"Blocking tool '{name}' - server instructions have changed")
                    blocked_response = {
                        "status": "blocked",
                        "reason": "Server instructions have changed and need re-approval. Use the 'context-protector-block' tool for approval instructions.",
                    }
                else:
                    # Server was never approved
                    logger.warning(f"Blocking tool '{name}' - server not approved")
                    blocked_response = {
                        "status": "blocked",
                        "reason": "Server configuration not approved. Use the 'context-protector-block' tool for approval instructions.",
                    }
                error_json = json.dumps(blocked_response)
                raise ValueError(error_json)

            # Check if this specific tool is approved
            # Only block if the tool exists in our config but is not approved
            # If the tool doesn't exist in our config, let the downstream server handle it
            tools_dict = self.approval_status.get("tools", {})
            if name in tools_dict and not tools_dict[name]:
                logger.warning(f"Blocking tool '{name}' - tool not approved")
                blocked_response = {
                    "status": "blocked",
                    "reason": f"Tool '{name}' is not approved. Use the 'context-protector-block' tool for approval instructions.",
                }
                error_json = json.dumps(blocked_response)
                raise ValueError(error_json)

            # Tool is approved, proxy the call
            try:
                tool_result = await self._proxy_tool_to_downstream(name, arguments)

                # If tool_result is a dict with structured content, handle it properly
                if isinstance(tool_result, dict) and "structured_content" in tool_result:
                    # Check if we have non-text content that needs to be preserved
                    has_non_text_content = False
                    if "content_list" in tool_result and tool_result["content_list"]:
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

    async def _handle_context_protector_block(self) -> list[types.TextContent]:
        """
        Handle the context-protector-block tool call.

        Returns:
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
context-protector status:

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

context-protector.sh --list-server stdio "your-server-command"

The review process will show you the server's capabilities and tools, and ask if you want to trust them.
Once approved, you can use all the server's tools through this wrapper.

Note: This tool is only available when tools are blocked due to security restrictions.
"""

        return [types.TextContent(type="text", text=instructions.strip())]

    async def _handle_quarantine_release(
        self, arguments: dict[str, Any]
    ) -> list[types.TextContent]:
        """
        Handle the quarantine_release tool call.

        Args:
        ----
            arguments: The tool arguments containing the UUID of the quarantined response

        Returns:
        -------
            The original tool response if found and available for release

        Raises:
        ------
            ValueError: If the UUID is invalid or not found, or if the response is not available for release

        """
        if "uuid" not in arguments:
            raise ValueError("Missing required parameter 'uuid' for quarantine_release tool")

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
            logger.info(f"Released response {response_id} from quarantine and deleted it")

            json_response = json.dumps(original_tool_info)
            wrapped_response = {"status": "completed", "response": json_response}
            final_response = json.dumps(wrapped_response)
            return [types.TextContent(type="text", text=final_response)]
        else:
            error = (
                f"Response {response_id} is not marked for release. "
                + f"Please use the CLI to review and release it first: "
                + f"context-protector.sh --review-quarantine --quarantine-id {response_id}"
            )
            return [types.TextContent(type="text", text=error)]

    async def _proxy_tool_to_downstream(self, name: str, arguments: dict) -> str:
        """Proxy a tool call to the downstream server using MCP client"""
        if not self.session:
            raise ValueError("No client connection to downstream server")

        try:
            logger.info(f"Forwarding tool call to downstream: {name} with args {arguments}")
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

            # Check if response_text is already valid JSON (from FastMCP tools)
            # If so, we should not double-wrap it in our legacy format
            try:
                json.loads(response_text)
                is_json_response = True
            except (json.JSONDecodeError, TypeError):
                is_json_response = False

            # Scan the tool response with guardrail provider if configured
            if self.use_guardrails and self.guardrail_provider is not None:
                guardrail_alert = self._scan_tool_response(name, arguments, response_text)
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
        structured_content: dict[str, Any | None],
        content_list: list[types.Content],
        is_json_response: bool = False,
    ) -> dict[str, Any]:
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
        quarantine_id: str | None,
    ) -> str:
        """Generates the response message sent to the client when a tool response is blocked by a guardrail."""

        return f"""
        This tool call was quarantined because it appears to contain a prompt injection attack.

        Tool name: {tool_name}
        Arguments: {json.dumps(arguments, indent=2)}
        Alert explanation: {guardrail_alert.explanation}

        To review this response and release it from the quarantine, run contextprotector with the arguments `--review-quarantine{" --quarantine-id " + quarantine_id if quarantine_id else ""}`.
        """

    def _convert_parameters_to_schema(self, parameters: dict, required: list[str]) -> dict:
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

    def _convert_mcp_tools_to_specs(self, tools) -> list[MCPToolSpec]:
        """
        Convert MCP tool definitions to internal tool specs.

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
                description=tool.description,
                parameters=parameters,
                required=required,
                output_schema=output_schema,
            )

            tool_specs.append(tool_spec)

        return tool_specs

    async def _handle_tool_updates(self, tools) -> None:
        """
        Handle tool update notifications from the downstream server.

        Args:
        ----
            tools: Updated list of tools from the downstream server

        """
        self.tool_specs = self._convert_mcp_tools_to_specs(tools)

        old_config = self.current_config
        self.current_config = self._create_server_config()

        # Re-evaluate approval status with the new config
        self.approval_status = self.config_db.get_server_approval_status(
            self.connection_type, self._get_server_identifier(), self.current_config
        )

        # Log the configuration changes if any
        if old_config != self.current_config:
            diff = old_config.compare(self.current_config)
            if diff.has_differences():
                logger.warning(f"Configuration differences detected: {diff}")

                # Update the database with new unapproved config
                self.config_db.save_unapproved_config(
                    self.connection_type, self._get_server_identifier(), self.current_config
                )

        # Update config_approved based on the new granular status
        if self.approval_status.get("is_new_server", False):
            self.config_approved = False
        elif not self.approval_status.get("instructions_approved", False):
            self.config_approved = False
        else:
            # Check if we have any approved tools
            approved_tool_count = sum(
                1 for approved in self.approval_status["tools"].values() if approved
            )
            self.config_approved = approved_tool_count > 0

        logger.info(f"Tool update processed - approval status: {self.config_approved}")
        if hasattr(self, "approval_status"):
            approved_tools = [
                name for name, approved in self.approval_status["tools"].items() if approved
            ]
            logger.info(f"Approved tools: {approved_tools}")

    async def _forward_notification_to_upstream(self, method: str, params=None) -> None:
        """
        Forward a notification to the upstream client.

        Args:
        ----
            method: The notification method (e.g., "notifications/progress")
            params: Optional notification parameters

        """
        if not self.server_session:
            logger.warning("No server session available to forward notification")
            return

        try:
            # Create appropriate notification type based on method
            if method == "notifications/progress":
                notification = types.ProgressNotification(
                    method=method, params=params if params else None
                )
            elif method == "notifications/message":
                notification = types.LoggingMessageNotification(
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
            else:
                # Fallback for any other valid notifications
                notification = types.JSONRPCNotification(
                    jsonrpc="2.0", method=method, params=params
                )

            await self.server_session.send_notification(notification)
            logger.info(f"Forwarded {method} to upstream client")
        except Exception as e:
            logger.warning(f"Failed to forward {method} notification: {e}")

    async def _handle_client_message(self, message) -> None:
        """
        Message handler for the ClientSession to process notifications,
        particularly tool update notifications.

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

            if method == "notifications/tools/list_changed":
                self.config_approved = False
                asyncio.create_task(self.update_tools(send_notification=True))
            elif method == "notifications/prompts/list_changed":
                # Prompt changes do NOT affect the config approval status
                logger.info(
                    "Received notification that prompts have changed (not affecting approval status)"
                )
                asyncio.create_task(self.update_prompts(send_notification=True))
            elif method == "notifications/resources/list_changed":
                # Resource changes do NOT affect the config approval status
                logger.info(
                    "Received notification that resources have changed (not affecting approval status)"
                )
                asyncio.create_task(self.update_resources(send_notification=True))
                await self._forward_notification_to_upstream(method, params)
            elif method in spec_compliant_notifications:
                # Forward other specification-compliant notifications to upstream client
                logger.info(f"Forwarding notification to upstream client: {method}")
                await self._forward_notification_to_upstream(method, params)
            else:
                # Discard non-specification notifications
                logger.info(f"Discarding non-specification notification: {method}")
        else:
            logger.info(f"Received non-notification message: {type(message)}")

    async def update_prompts(self, send_notification: bool = False) -> None:
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
            if send_notification:
                await self._forward_notification_to_upstream(
                    "notifications/prompts/list_changed", None
                )
        except Exception as e:
            out = traceback.format_exc()
            logger.warning(f"Error updating prompts from downstream server: {e} {out}")

    async def update_resources(self, send_notification: bool = False) -> None:
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
            if send_notification:
                await self._forward_notification_to_upstream(
                    "notifications/resources/list_changed", None
                )
        except Exception as e:
            logger.warning(f"Error updating resources from downstream server: {e}")

    async def update_tools(self, send_notification: bool = False) -> None:
        """Update tools from the downstream server."""
        try:
            downstream_tools = await self.session.list_tools()

            assert downstream_tools.tools
            logger.info(f"Received {len(downstream_tools.tools)} tools after update notification")

            await self._handle_tool_updates(downstream_tools.tools)
            if send_notification:
                await self._forward_notification_to_upstream(
                    "notifications/tools/list_changed", None
                )
        except Exception as e:
            logger.warning(f"Error handling tool update notification: {e}")

    async def connect(self) -> None:
        """Initialize the connection to the downstream server."""
        if self.connection_type == "stdio":
            await self._connect_via_stdio()
        elif self.connection_type == "http":
            await self._connect_via_streamable_http()
        elif self.connection_type == "sse":
            await self._connect_via_http()
        else:
            raise ValueError(f"Unknown connection type: {self.connection_type}")
        await self._initialize_config()

    async def _initialize_config(self) -> None:
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
                logger.info(f"Received {len(self.prompts)} prompts during initialization")
        except Exception as e:
            logger.info(f"Downstream server does not support prompts: {e}")

        self.resources = []
        try:
            downstream_resources = await self.session.list_resources()
            if downstream_resources and downstream_resources.resources:
                self.resources = downstream_resources.resources
                logger.info(f"Received {len(self.resources)} resources during initialization")
        except Exception as e:
            logger.info(f"Downstream server does not support resources: {e}")

        self.current_config = self._create_server_config()

        # Get granular approval status using the new system
        self.approval_status = self.config_db.get_server_approval_status(
            self.connection_type, self._get_server_identifier(), self.current_config
        )

        if self.approval_status["is_new_server"]:
            logger.info("New server detected - saving as unapproved")
            # Save the config as unapproved for later review
            self.config_db.save_unapproved_config(
                self.connection_type, self._get_server_identifier(), self.current_config
            )
            self.config_approved = False
        elif not self.approval_status["instructions_approved"]:
            logger.info("Server instructions have changed - server blocked until re-approval")
            # Save the updated config as unapproved
            self.config_db.save_unapproved_config(
                self.connection_type, self._get_server_identifier(), self.current_config
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
                    f"Server partially approved - {approved_tool_count}/{total_tool_count} tools approved"
                )
                self.config_approved = True  # Allow partial operation
            else:
                logger.info("Server instructions approved but no tools approved yet")
                self.config_approved = False

    def _get_server_identifier(self) -> str:
        """Get the server identifier for database storage."""
        if self.connection_type == "stdio":
            return self.child_command
        elif self.connection_type in ["http", "sse"]:
            return self.server_url
        else:
            raise ValueError(f"Unknown connection type: {self.connection_type}")

    async def _connect_via_stdio(self) -> None:
        """Connect to a downstream server via stdio."""
        logger.info(f"Connecting to downstream server via stdio: {self.child_command}")

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        try:
            if self.child_command.startswith('"') and self.child_command.endswith('"'):
                self.child_command = self.child_command[1:-1]

            self.server_identifier = self.child_command

            self.saved_config = self.config_db.get_server_config("stdio", self.server_identifier)

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

    async def _connect_via_http(self) -> None:
        """Connect to a downstream server via SSE (Server-Sent Events)."""
        logger.info(f"Connecting to downstream server via SSE: {self.server_url}")

        # Set up imports
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        try:
            logger.info(f"Connecting to SSE server at {self.server_url}")

            self.server_identifier = self.server_url

            self.saved_config = self.config_db.get_server_config("sse", self.server_identifier)

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

    async def _connect_via_streamable_http(self) -> None:
        """Connect to a downstream server via streamable HTTP."""
        logger.info(f"Connecting to downstream server via streamable HTTP: {self.server_url}")

        # Set up imports
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        try:
            logger.info(f"Connecting to streamable HTTP server at {self.server_url}")

            self.server_identifier = self.server_url

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

        except Exception as e:
            logger.error(f"Error connecting to downstream server via streamable HTTP: {e}")
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

    def _setup_notification_handlers(self) -> None:
        """Setup handlers for client → server notifications to forward to downstream server."""

        @self.server.progress_notification()
        async def handle_progress_notification(notification: types.ProgressNotification) -> None:
            """Forward progress notifications from upstream client to downstream server."""
            logger.info("Forwarding progress notification from client to downstream server")

            if self.session:
                try:
                    # Forward the notification to the downstream server's session
                    # Note: ClientSession doesn't have send_notification, so we'll need to send as JSON-RPC
                    await self._forward_notification_to_downstream(notification)
                except Exception as e:
                    logger.warning(f"Failed to forward progress notification to downstream: {e}")

        # Handle other client notifications by registering them manually
        # Since there may not be decorators for all notification types, we'll register directly

        async def handle_cancelled_notification(notification: types.CancelledNotification) -> None:
            """Forward cancelled notifications from upstream client to downstream server."""
            logger.info("Forwarding cancelled notification from client to downstream server")

            if self.session:
                try:
                    await self._forward_notification_to_downstream(notification)
                except Exception as e:
                    logger.warning(f"Failed to forward cancelled notification to downstream: {e}")

        async def handle_initialized_notification(notification: types.InitializedNotification) -> None:
            """Forward initialized notifications from upstream client to downstream server."""
            logger.info("Forwarding initialized notification from client to downstream server")

            if self.session:
                try:
                    await self._forward_notification_to_downstream(notification)
                except Exception as e:
                    logger.warning(f"Failed to forward initialized notification to downstream: {e}")

        async def handle_message_notification(notification: types.LoggingMessageNotification) -> None:
            """Forward log message notifications from upstream client to downstream server."""
            logger.info("Forwarding message notification from client to downstream server")

            if self.session:
                try:
                    await self._forward_notification_to_downstream(notification)
                except Exception as e:
                    logger.warning(f"Failed to forward message notification to downstream: {e}")

        # Register the handlers manually in the notification_handlers dict
        self.server.notification_handlers[types.CancelledNotification] = (
            handle_cancelled_notification
        )
        self.server.notification_handlers[types.InitializedNotification] = (
            handle_initialized_notification
        )
        self.server.notification_handlers[types.LoggingMessageNotification] = (
            handle_message_notification
        )

    async def _forward_notification_to_downstream(self, notification) -> None:
        """Forward a notification from upstream client to downstream server."""
        if not self.session:
            logger.warning("No downstream session available to forward notification")
            return

        try:
            # ClientSession does have send_notification - use it to forward to downstream
            await self.session.send_notification(notification)
            logger.info(
                f"Successfully forwarded notification {notification.method} to downstream server"
            )
        except Exception as e:
            logger.error(f"Error forwarding notification {notification.method} to downstream: {e}")

    def _make_ansi_escape_codes_visible(self, text: str) -> str:
        """
        Convert ANSI escape sequences to visible text by replacing escape character with "ESC".
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

        return make_ansi_escape_codes_visible(text)

    def _scan_tool_response(
        self, tool_name: str, tool_input: dict[str, Any], tool_output: str
    ) -> GuardrailAlert | None:
        """
        Scan a tool response with the configured guardrail provider.

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
                logger.info(f"Closed MCP client connection (type: {self.connection_type})")
            except Exception as e:
                logger.error(f"Error closing MCP client: {e}")

    async def run(self) -> None:
        """Run the MCP wrapper server using stdio."""
        await self.connect()

        try:
            from mcp.server.stdio import stdio_server
            from mcp.server.session import ServerSession
            from contextlib import AsyncExitStack
            import anyio

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
                                False,  # Don't raise exceptions
                            )
        finally:
            await self.stop_child_process()


async def review_server_config(
    connection_type: Literal["stdio", "http", "sse"],
    identifier: str,
    config_path: str | None = None,
    guardrail_provider: GuardrailProvider | None = None,
    quarantine_path: str | None = None,
) -> None:
    """
    Review and approve server configuration for the given connection.

    This function connects to the downstream server, retrieves its configuration,
    and prompts the user to approve it. If approved, the configuration is saved
    as trusted in the config database.

    Args:
    ----
        connection_type: Type of connection ("stdio", "http", or "sse")
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
            print(f"• {tool_spec.name}: {make_ansi_escape_codes_visible(tool_spec.description)}")
        print("=====================\n")

        guardrail_alert = None
        if wrapper.guardrail_provider is not None:
            guardrail_alert = wrapper.guardrail_provider.check_server_config(wrapper.current_config)

        if guardrail_alert:
            print("\n==== GUARDRAIL CHECK: ALERT ====")
            print(f"Provider: {wrapper.guardrail_provider.name}")
            print(f"Alert: {guardrail_alert.explanation}")
            print("==================================\n")

        response = (
            input("Do you want to trust this server configuration? (yes/no): ").strip().lower()
        )
        if response in ("yes", "y"):
            # First approve instructions
            wrapper.config_db.approve_instructions(
                wrapper.connection_type,
                wrapper._get_server_identifier(),
                wrapper.current_config.instructions,
            )

            # Then approve each tool individually
            for tool in wrapper.current_config.tools:
                wrapper.config_db.approve_tool(
                    wrapper.connection_type,
                    wrapper._get_server_identifier(),
                    tool.name,
                    tool,
                )

            # Finally set the server as approved
            wrapper.config_db.save_server_config(
                wrapper.connection_type,
                wrapper._get_server_identifier(),
                wrapper.current_config,
                ApprovalStatus.APPROVED,
            )
            print(f"\nThe server configuration for {identifier} has been trusted and saved.")
        else:
            print(f"\nThe server configuration for {identifier} has NOT been trusted.")

    finally:
        # Clean up
        await wrapper.stop_child_process()


def make_ansi_escape_codes_visible(text: str) -> str:
    # Replace the escape character (ASCII 27, typically \x1b or \033) with "ESC"
    # This will convert escape sequences like "\x1b[31m" (red text) to "ESC[31m"
    # making them visible instead of changing the terminal colors
    return re.sub(r"\x1b", "ESC", text)
