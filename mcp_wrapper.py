#!/usr/bin/env python3
import argparse
import asyncio
import logging
import json
import re
import sys
from typing import List, Optional

import mcp.types as types
from mcp.server.lowlevel import Server, NotificationOptions
from mcp.server.models import InitializationOptions

from mcp_config import (
    MCPServerConfig,
    MCPToolSpec,
    MCPToolDefinition,
    MCPParameterDefinition,
    ParameterType,
    MCPConfigDatabase,
)
from guardrails import get_provider_names, get_provider, GuardrailProvider, GuardrailAlert

logger = logging.getLogger("mcp_wrapper")

class MCPWrapperServer:
    @classmethod
    def wrap_stdio(cls, command: str, config_path: str = None, guardrail_provider: Optional[GuardrailProvider] = None, 
                  visualize_ansi_codes: bool = False):
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
        instance = cls(config_path, guardrail_provider, visualize_ansi_codes)
        instance.connection_type = "stdio"
        instance.child_command = command
        return instance
        
    @classmethod
    def wrap_http(cls, url: str, config_path: str = None, guardrail_provider: Optional[GuardrailProvider] = None,
                 visualize_ansi_codes: bool = False):
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
        instance = cls(config_path, guardrail_provider, visualize_ansi_codes)
        instance.connection_type = "http"
        instance.server_url = url
        return instance
    
    def __init__(self, config_path: str = None, guardrail_provider: Optional[GuardrailProvider] = None, visualize_ansi_codes: bool = False):
        """
        Initialize the wrapper server with common attributes.
        Use wrap_stdio or wrap_http class methods instead of calling this directly.
        
        Args:
            config_path: Optional path to the wrapper config file
            guardrail_provider: Optional guardrail provider object to use for checking configs
            visualize_ansi_codes: Whether to make ANSI escape codes visible in tool outputs
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
        self.config_path = config_path
        self.config_db = MCPConfigDatabase(config_path)
        self.saved_config = None  # Will be loaded after server_identifier is set
        self.current_config = MCPServerConfig()
        self.server = Server("mcp_wrapper")
        self.guardrail_provider = guardrail_provider  # Store the provider object
        self.use_guardrails = guardrail_provider is not None  # Enable guardrails if provider is specified
        self.guardrail_alert = None  # Will hold GuardrailAlert if a guardrail is triggered
        self.visualize_ansi_codes = visualize_ansi_codes  # Whether to make ANSI escape codes visible
        self.prompts = []  # Will store prompts from the downstream server
        self._setup_server()

    def _setup_server(self):
        """Setup MCP server handlers"""

        @self.server.list_prompts()
        async def list_prompts() -> List[types.Prompt]:
            """
            Return prompts from the downstream server, or an empty list if server config is not approved.
            When config isn't approved, we don't reveal any prompts to clients.
            """
            if not self.config_approved:
                logger.warning("Blocking list_prompts - server configuration not approved")
                return []
            
            return self.prompts
        
        @self.server.list_tools()
        async def list_tools() -> List[types.Tool]:
            """Return tool specs from the child MCP server and add wrapper-specific tools."""
            # Create a list with the downstream server tools
            all_tools = []

            # Add downstream tools
            for spec in self.tool_specs:
                tool = types.Tool(
                    name=spec.name,
                    description=spec.description,
                    inputSchema=self._convert_parameters_to_schema(
                        spec.parameters, spec.required
                    ),
                )
                all_tools.append(tool)

            # Add our wrapper-specific tool
            approve_tool = types.Tool(
                name="approve_server_config",
                description="""
                    Approve the server configuration to enable downstream tool calls. ONLY run this tool when the user
                    has explicitly indicated that the new tool configuration is trusted. Whenever you determine that a
                    server configuration has changed and needs to be re-approved, prominently display the diff to the
                    user in the GUI and direct the user to manually review it. When a tool call is blocked, do NOT
                    automatically call this tool without asking the user for permission first. It is critical that
                    the user knows that the server configuration has changed and has an opportunity to say "yes, the
                    server configuration is approved" or "no, the server configuration is not approved" before you
                    call this tool.
                    """,
                inputSchema={
                    "type": "object",
                    "required": ["config"],
                    "properties": {
                        "config": {
                            "type": "string",
                            "description": "Serialized server configuration as a JSON string",
                        }
                    },
                },
            )

            # Add our tool to the list
            all_tools.append(approve_tool)
            
            # Add the ignore_guardrail_alert tool if guardrails are enabled
            if self.use_guardrails:
                ignore_guardrail_tool = types.Tool(
                    name="ignore_guardrail_alert",
                    description="""
                        Use this tool if the server configuration triggers a guardrail. ONLY trigger this tool if the user 
                        explicitly asks to ignore the guardrail alert and specifically says "I understand the risks".
                        You must provide the full explanation text from the guardrail alert to confirm you understand
                        what guardrail is being bypassed.
                        Do not use this tool proactively or without clear user instruction to bypass the guardrail.
                        """,
                    inputSchema={
                        "type": "object",
                        "required": ["alert_text"],
                        "properties": {
                            "alert_text": {
                                "type": "string",
                                "description": "The exact explanation text from the guardrail alert you want to ignore"
                            }
                        },
                    },
                )
                all_tools.append(ignore_guardrail_tool)

            return all_tools

        @self.server.get_prompt()
        async def get_prompt(name: str, arguments: dict) -> List[types.TextContent]:
            """
            Handle prompt dispatch requests - proxy to downstream server if config is approved.
            If the server config isn't approved, return an empty message list.
            """
            logger.info(f"Prompt dispatch with name {name} and config_approved {self.config_approved}")
            
            # For prompt dispatch, check if config is approved
            if not self.config_approved:
                logger.warning(f"Blocking prompt '{name}' - server configuration not approved")
                
                # Return an empty result with no messages instead of raising an error
                return types.GetPromptResult(
                    description="Server configuration not approved",
                    messages=[]  # Empty message list
                )
            
            # If we get here, config is approved, so proxy the prompt call
            logger.info(f"Proxying prompt dispatch: {name}")
            try:
                # Use the session to dispatch the prompt to the downstream server
                result = await self.session.get_prompt(name, arguments)
                
                # Extract the text content from the result
                text_parts = []
                for content in result.messages:
                    if content.content:
                        # Apply ANSI escape code processing if enabled
                        processed_text = self._make_ansi_escape_codes_visible(content.content)
                        text_parts.append(processed_text)
                
                # Return the results
                return types.GetPromptResult(
                    description=result.description,
                    messages=[types.PromptMessage(role="user", content=text) for text in text_parts]
                )
                
            except Exception as e:
                logger.error(f"Error from downstream server during prompt dispatch:\n\n---\n\n{e}\n\n---\n\n")
                raise ValueError(f"Error from downstream server: {str(e)}")
                
        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> List[types.TextContent]:
            """
            Handle tool use requests - either approve config, proxy to downstream server,
            or block if config not approved.
            """
            logger.info(f"Tool call with name {name} and config_approved {self.config_approved}")
            if not self.session and name not in ["approve_server_config", "ignore_guardrail_alert"]:
                raise ValueError("Child MCP server not connected")

            # Special handling for our approve_server_config tool
            if name == "approve_server_config":
                result = await self._handle_approve_config(arguments.get("config", ""))
                return [types.TextContent(type="text", text=result)]
                
            # Special handling for our ignore_guardrail_alert tool
            if name == "ignore_guardrail_alert" and self.use_guardrails:
                logger.info("Processing ignore_guardrail_alert request")
                
                # Check if there's an active guardrail alert
                if not self.guardrail_alert:
                    logger.warning("No active guardrail alert to ignore")
                    return [types.TextContent(type="text", text=json.dumps({
                        "status": "failed",
                        "reason": "No active guardrail alert to ignore"
                    }))]
                
                # Get the alert_text parameter
                alert_text = arguments.get("alert_text", "")
                if not alert_text:
                    logger.warning("No alert_text provided for ignore_guardrail_alert")
                    return [types.TextContent(type="text", text=json.dumps({
                        "status": "failed",
                        "reason": "You must provide the full alert_text to ignore the guardrail alert",
                        "current_alert": self.guardrail_alert.explanation
                    }))]
                
                # Verify the alert text matches
                actual_explanation = self.guardrail_alert.explanation
                if alert_text.strip() != actual_explanation.strip():
                    logger.warning(f"Alert text mismatch. Expected: '{actual_explanation}', Got: '{alert_text}'")
                    return [types.TextContent(type="text", text=json.dumps({
                        "status": "failed",
                        "reason": "The provided alert text does not match the actual guardrail alert",
                        "current_alert": actual_explanation,
                        "provided_alert": alert_text
                    }))]
                
                # Alert text matches, clear the guardrail alert
                logger.info("User explicitly chose to ignore guardrail alert with correct alert text")
                self.guardrail_alert = None
                
                return [types.TextContent(type="text", text=json.dumps({
                    "status": "success",
                    "reason": "Guardrail alert successfully ignored at user's explicit request"
                }))]

            # For all other tools, check if config is approved
            if not self.config_approved:
                logger.warning(f"Blocking tool '{name}' - server configuration not approved")

                # Load the registry and configs
                self.current_config = self._create_server_config()

                # Create diff if we have a saved config to compare against
                diff_text = "New server - no previous configuration to compare"
                if self.saved_config:
                    diff = self.saved_config.compare(self.current_config)
                    if diff.has_differences():
                        diff_text = str(diff)
                    else:
                        diff_text = "No differences found (configs are identical)"

                # Serialize the server config (use current config)
                serialized_config = self.current_config.to_json()

                # Create blocked response with diff and guardrail alert if any
                blocked_response = {
                    "status": "blocked",
                    "server_config": serialized_config,
                    "diff": diff_text,
                    "reason": "Server configuration not approved - all tools blocked",
                }
                
                # Add guardrail alert information if available
                if self.guardrail_alert:
                    blocked_response["guardrail_alert"] = {
                        "provider": self.guardrail_provider.name,
                        "explanation": self.guardrail_alert.explanation,
                        "data": self.guardrail_alert.data
                    }

                # Return a formatted error with the blocked response
                error_json = json.dumps(blocked_response)
                logger.debug(f"Returning error: {error_json}")
                raise ValueError(error_json)

            # If we get here, config is approved, so proxy the tool call
            logger.info(f"Proxying tool use: {name}")
            try:
                # Convert to actual downstream call format using the new client
                tool_result = await self._proxy_tool_to_downstream(name, arguments)

                # Wrap the successful response
                wrapped_response = {"status": "completed", "response": tool_result}
                logger.info(f"Tool result response: {wrapped_response}")

                # Create a new result with the wrapped response
                json_response = json.dumps(wrapped_response)
                logger.info(f"Returning JSON: {json_response}")
                return [types.TextContent(type="text", text=json_response)]

            except Exception as e:
                logger.error(f"Error from child MCP server: {e}")
                raise ValueError(f"Error from child MCP server: {str(e)}")

    async def _proxy_tool_to_downstream(self, name: str, arguments: dict) -> str:
        """Proxy a tool call to the downstream server using MCP client"""
        if not self.session:
            raise ValueError("No client connection to downstream server")
            
        try:
            # Make the actual tool call to the downstream server
            logger.info(f"Forwarding tool call to downstream: {name} with args {arguments}")
            result = await self.session.call_tool(name, arguments)
            
            # Extract the text content from the result
            if result and len(result.content) > 0:
                # The client call returns a list of content objects, we'll join all text content
                text_parts = []
                for content in result.content:
                    if content.type == "text" and content.text:
                        # Apply ANSI escape code processing if enabled
                        processed_text = self._make_ansi_escape_codes_visible(content.text)
                        text_parts.append(processed_text)
                
                if text_parts:
                    return " ".join(text_parts)
            
            # If we didn't get usable content, return a generic success message
            return f"Tool call to '{name}' succeeded but returned no content"
            
        except Exception as e:
            logger.error(f"Error calling downstream tool '{name}': {e}")
            raise ValueError(f"Error calling downstream tool: {str(e)}")

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
                        "schema": {
                            "type": prop_details.get("type", "string")
                        }
                    }
                    
                    # Add enum values if present
                    if "enum" in prop_details:
                        parameters[prop_name]["schema"]["enum"] = prop_details["enum"]
            
            # Extract required fields
            if tool.inputSchema and "required" in tool.inputSchema:
                required = tool.inputSchema["required"]
            
            # Create our tool spec
            tool_spec = MCPToolSpec(
                name=tool.name,
                description=tool.description,
                parameters=parameters,
                required=required
            )
            
            tool_specs.append(tool_spec)
            
        return tool_specs

    async def _handle_tool_updates(self, tools):
        """
        Handle tool update notifications from the downstream server.
        
        Args:
            tools: Updated list of tools from the downstream server
        """
        # Convert MCP tools to our internal format
        self.tool_specs = self._convert_mcp_tools_to_specs(tools)
        
        # Temporarily reset approval while we check if the config has changed
        self.config_approved = False
        # Reset any guardrail alert
        self.guardrail_alert = None
        
        old_config = self.current_config
        self.current_config = self._create_server_config()
        
        # If tools have changed, check against the saved config (if any)
        if old_config != self.current_config:
            logger.warning("Tools have changed from previous state")
            
            # Generate diff for logging
            diff = old_config.compare(self.current_config)
            if diff.has_differences():
                logger.warning(f"Configuration differences: {diff}")
            
            # If we have a saved config, check if the current config matches it
            if self.saved_config and self.saved_config == self.current_config:
                logger.info("Tools changed but match saved approved configuration")
                self.config_approved = True
            else:
                logger.warning("Tools changed, requiring re-approval")
                
                # Check with guardrail provider if configured
                if self.use_guardrails and self.guardrail_provider:
                    logger.info(f"Checking config with guardrail provider: {self.guardrail_provider.name}")
                    self.guardrail_alert = self.guardrail_provider.check_server_config(self.current_config)
                    if self.guardrail_alert:
                        logger.warning(f"Guardrail alert triggered: {self.guardrail_alert.explanation}")
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
        logger.info(f"Received message: {type(message)}")
        
        # Check if it's a notification
        if isinstance(message, types.ServerNotification):
            if message.root.method == "notifications/tools/list_changed":
                # Tool changes require re-approval of the configuration
                self.config_approved = False
                asyncio.create_task(self.update_tools())
            elif message.root.method == "notifications/prompts/list_changed":
                # Prompt changes do NOT affect the config approval status
                logger.info("Received notification that prompts have changed (not affecting approval status)")
                asyncio.create_task(self.update_prompts())
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
            # Get updated prompts from the downstream server
            downstream_prompts = await self.session.list_prompts()
            
            if downstream_prompts and downstream_prompts.prompts:
                old_prompt_count = len(self.prompts)
                self.prompts = downstream_prompts.prompts
                new_prompt_count = len(self.prompts)
                logger.info(f"Updated prompts from downstream server (old: {old_prompt_count}, new: {new_prompt_count})")
                logger.info("Note: Prompt changes do not affect server configuration approval status")
            else:
                logger.info("No prompts available from downstream server")
                self.prompts = []
        except Exception as e:
            logger.warning(f"Error updating prompts from downstream server: {e}")
            
    async def update_tools(self):
        """Update tools from the downstream server."""
        try:
            # Get updated tools from the downstream server
            downstream_tools = await self.session.list_tools()

            assert downstream_tools.tools
            logger.info(f"Received {len(downstream_tools.tools)} tools after update notification")
            
            # Process the updated tools
            logger.info("Processing tool update notification")
            await self._handle_tool_updates(downstream_tools.tools)
            
            # Also update prompts whenever tools are updated
            await self.update_prompts()
        except Exception as e:
            logger.warning(f"Error handling tool update notification: {e}")

    async def start_child_process(self):
        """Initialize the connection to the downstream server."""
        if self.connection_type == "stdio":
            await self._connect_via_stdio()
        elif self.connection_type == "http":
            await self._connect_via_http()
        else:
            raise ValueError(f"Unknown connection type: {self.connection_type}")
        
        # Create server configuration
        self.current_config = self._create_server_config()
        
        # Check if we need to evaluate guardrails (already done in _connect_via_* methods)
        # but set here if no alert was set for some reason
        if self.use_guardrails and self.guardrail_provider and self.guardrail_alert is None:
            logger.info(f"Checking config with guardrail provider in start_child_process: {self.guardrail_provider.name}")
            self.guardrail_alert = self.guardrail_provider.check_server_config(self.current_config)
            if self.guardrail_alert:
                logger.warning(f"Guardrail alert triggered: {self.guardrail_alert.explanation}")
        
        # Check if we can auto-approve based on saved config
        # Don't auto-approve if there's a guardrail alert
        if self.guardrail_alert is not None:
            logger.warning("Cannot auto-approve config due to active guardrail alert")
            self.config_approved = False
        elif self.saved_config and self.saved_config == self.current_config:
            logger.info("Current configuration matches saved configuration - auto-approving")
            self.config_approved = True
        else:
            if not self.saved_config:
                logger.info("No saved configuration found - approval required")
            else:
                logger.info("Configuration has changed since last approval - re-approval required")
            
    async def _connect_via_stdio(self):
        """Connect to a downstream server via stdio."""
        logger.info(f"Connecting to downstream server via stdio: {self.child_command}")
        
        # Set up imports
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        try:
            # We'll use the MCP client to start the child process for us
            # Parse the command
            if self.child_command.startswith('"') and self.child_command.endswith('"'):
                self.child_command = self.child_command[1:-1]
                
            # Set the server identifier for config lookup
            self.server_identifier = self.child_command
            
            # Load the saved config if it exists in the database
            self.saved_config = self.config_db.get_server_config("stdio", self.server_identifier)
                
            command_parts = self.child_command.split()
            if not command_parts:
                raise ValueError("Invalid command")
                
            # Create server parameters to pass to stdio_client
            server_params = StdioServerParameters(
                command=command_parts[0],
                args=command_parts[1:] if len(command_parts) > 1 else [],
            )
            
            # Create the client
            logger.info(f"Starting downstream server with command: {command_parts[0]} {' '.join(command_parts[1:])}")
            self.client_context = stdio_client(server_params)
            self.streams = await self.client_context.__aenter__()
            
            # Create the client session with a message handler to process notifications
            self.session = await ClientSession(
                self.streams[0], 
                self.streams[1],
                message_handler=self._handle_client_message
            ).__aenter__()
            
            self.initialize_result = await self.session.initialize()
            
            # Get tool specifications from the downstream server
            downstream_tools = await self.session.list_tools()
            assert downstream_tools.tools

            # Convert MCP tools to our internal format
            self.tool_specs = self._convert_mcp_tools_to_specs(downstream_tools.tools)
            
            # Get prompts from the downstream server if available
            self.prompts = []
            try:
                downstream_prompts = await self.session.list_prompts()
                if downstream_prompts and downstream_prompts.prompts:
                    self.prompts = downstream_prompts.prompts
                    logger.info(f"Received {len(self.prompts)} prompts during stdio initialization")
            except Exception as e:
                logger.info(f"Downstream stdio server does not support prompts: {e}")
                
            # Check guardrails if provider is available
            if self.use_guardrails and self.guardrail_provider:
                # Create the server config to check against guardrails
                self.current_config = self._create_server_config()
                logger.info(f"Checking initial config with guardrail provider in stdio: {self.guardrail_provider.name}")
                self.guardrail_alert = self.guardrail_provider.check_server_config(self.current_config)
                if self.guardrail_alert:
                    logger.warning(f"Guardrail alert triggered during stdio initialization: {self.guardrail_alert.explanation}")
                    # We don't auto-approve configs with guardrail alerts
                    self.config_approved = False
                
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
            # No need to parse the URL, sse_client handles the full URL directly
            logger.info(f"Connecting to SSE server at {self.server_url}")
            
            # Set the server identifier for config lookup
            self.server_identifier = self.server_url
            
            # Load the saved config if it exists in the database
            self.saved_config = self.config_db.get_server_config("sse", self.server_identifier)
            
            # Create the SSE client - it takes the full URL
            self.client_context = sse_client(self.server_url)
            self.streams = await self.client_context.__aenter__()
            
            # Create the client session with a message handler to process notifications
            self.session = await ClientSession(
                self.streams[0], 
                self.streams[1],
                message_handler=self._handle_client_message
            ).__aenter__()
            
            # Initialize the session and store the result
            self.initialize_result = await self.session.initialize()
            
            # Get tool specifications from the downstream server
            downstream_tools = await self.session.list_tools()
            assert downstream_tools.tools

            # Convert MCP tools to our internal format
            self.tool_specs = self._convert_mcp_tools_to_specs(downstream_tools.tools)
            
            # Get prompts from the downstream server if available
            self.prompts = []
            try:
                downstream_prompts = await self.session.list_prompts()
                if downstream_prompts and downstream_prompts.prompts:
                    self.prompts = downstream_prompts.prompts
                    logger.info(f"Received {len(self.prompts)} prompts during stdio initialization")
            except Exception as e:
                logger.info(f"Downstream stdio server does not support prompts: {e}")
                
            # Check guardrails if provider is available
            if self.use_guardrails and self.guardrail_provider:
                # Create the server config to check against guardrails
                self.current_config = self._create_server_config()
                logger.info(f"Checking initial config with guardrail provider in http: {self.guardrail_provider.name}")
                self.guardrail_alert = self.guardrail_provider.check_server_config(self.current_config)
                if self.guardrail_alert:
                    logger.warning(f"Guardrail alert triggered during http initialization: {self.guardrail_alert.explanation}")
                    # We don't auto-approve configs with guardrail alerts
                    self.config_approved = False
                
        except Exception as e:
            logger.error(f"Error connecting to downstream server via SSE: {e}")
            raise

    def _create_server_config(self) -> MCPServerConfig:
        """Create a server configuration from the tool specs."""
        config = MCPServerConfig()

        # Add server instructions if available
        if self.initialize_result and hasattr(self.initialize_result, 'instructions'):
            config.instructions = self.initialize_result.instructions

        for spec in self.tool_specs:
            parameters = []

            # Convert parameters to our format
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
                name=spec.name, description=spec.description, parameters=parameters
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

        # Replace the escape character (ASCII 27, typically \x1b or \033) with "ESC"
        # This will convert escape sequences like "\x1b[31m" (red text) to "ESC[31m"
        # making them visible instead of changing the terminal colors
        return re.sub(r'\x1b', 'ESC', text)
    
    def _print_server_config(self, config: MCPServerConfig):
        """Print the server configuration to stdout."""
        # Convert to JSON and print to stdout
        json_str = config.to_json()

        # Format approval status
        approval_status = "APPROVED" if self.config_approved else "NOT APPROVED"

        print(f"\n==== SERVER CONFIGURATION ({approval_status}) ====")
        print(json_str)
        print("=============================\n")

    async def stop_child_process(self):
        """Close connections to the downstream server."""
        # Clean up the client context if it exists
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

    async def _handle_approve_config(self, config_json: str) -> str:
        """
        Handle the approve_server_config tool.

        Args:
            config_json: The serialized configuration

        Returns:
            JSON string with success or failure result
        """
        logger.info("Processing approve_server_config request")

        try:
            # Check if there's an active guardrail alert
            if self.guardrail_alert:
                logger.warning("Cannot approve config while guardrail alert is active")
                
                # Create failure response with guardrail information
                failure_response = {
                    "status": "failed",
                    "reason": "Cannot approve server configuration while guardrail alert is active",
                    "guardrail_alert": {
                        "provider": self.guardrail_provider.name,
                        "explanation": self.guardrail_alert.explanation,
                        "data": self.guardrail_alert.data
                    },
                    "message": "You must first clear the guardrail alert using the ignore_guardrail_alert tool"
                }
                
                return json.dumps(failure_response)
                
            # Get the submitted config
            submitted_config_json = config_json
            if not submitted_config_json:
                raise ValueError("No configuration provided")

            # Deserialize the submitted config
            try:
                submitted_config = MCPServerConfig.from_json(
                    json_str=submitted_config_json
                )
            except Exception as e:
                raise ValueError(f"Invalid configuration format: {str(e)}")

            # Get the current server config
            current_config = self._create_server_config()

            # Compare the configs
            diff = current_config.compare(submitted_config)

            if diff.has_differences():
                logger.warning("Submitted config does not match server config")
                logger.warning(f"Differences: {diff}")

                # Create failure response
                failure_response = {
                    "status": "failed",
                    "reason": "Config did not match current server configuration",
                    "server_config": current_config.to_json(),
                    "diff": str(diff),
                }

                return json.dumps(failure_response)

            # Configs match, so approve it
            logger.info("Submitted config matches server config - approving")

            # Save the config to the database
            if self.connection_type and self.server_identifier:
                self.config_db.save_server_config(
                    self.connection_type, 
                    self.server_identifier, 
                    current_config
                )
                logger.info(f"Saved {self.connection_type} server config for {self.server_identifier}")
            else:
                logger.warning("Connection type or server identifier not set, config not saved to database")
                
            # Update the saved config
            self.saved_config = current_config

            # Set approved flag and clear any guardrail alert
            self.config_approved = True
            self.guardrail_alert = None

            # Create success response
            success_response = {
                "status": "success",
                "reason": "Server configuration approved",
            }

            return json.dumps(success_response)

        except Exception as e:
            logger.error(f"Error processing approve_server_config: {e}")

            error_response = {"status": "error", "reason": str(e)}

            return json.dumps(error_response)

    async def run(self):
        """Run the MCP wrapper server using stdio."""
        await self.start_child_process()

        try:
            # Run the server using stdio transport
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
                                prompts_changed=True
                            ),
                            experimental_capabilities={},
                        ),
                    ),
                )
        finally:
            await self.stop_child_process()


async def main():
    parser = argparse.ArgumentParser(description="MCP Wrapper Server")
    
    # Create mutually exclusive group for command, URL, and list-guardrail-providers
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--command", help="The command to run as a child process")
    source_group.add_argument("--url", help="The URL to connect to for a remote MCP server")
    source_group.add_argument("--list-guardrail-providers", action="store_true", 
                             help="List available guardrail providers and exit")
    
    # Add config file argument with new name
    parser.add_argument("--config-file", help="The path to the wrapper config file", default="")
    
    # Add guardrail provider argument
    parser.add_argument("--guardrail-provider", help="The guardrail provider to use for checking server configurations")
    
    # Add ANSI escape code visualization argument
    parser.add_argument("--visualize-ansi-codes", action="store_true", 
                      help="Make ANSI escape codes visible by replacing escape characters with 'ESC'")

    args = parser.parse_args()

    # Check if we should just list guardrail providers and exit
    if args.list_guardrail_providers:
        provider_names = get_provider_names()
        if provider_names:
            print("Available guardrail providers:")
            for provider in provider_names:
                print(f"  - {provider}")
        else:
            print("No guardrail providers found.")
        return
    
    # Get guardrail provider object if specified
    guardrail_provider = None
    if args.guardrail_provider:
        provider_names = get_provider_names()
        if args.guardrail_provider not in provider_names:
            print(f"Error: Unknown guardrail provider '{args.guardrail_provider}'", file=sys.stderr)
            print("Available providers: " + ", ".join(provider_names), file=sys.stderr)
            sys.exit(1)
        
        # Get the provider object
        guardrail_provider = get_provider(args.guardrail_provider)
        if not guardrail_provider:
            print(f"Error: Failed to initialize guardrail provider '{args.guardrail_provider}'", file=sys.stderr)
            sys.exit(1)
        
        logger.info(f"Using guardrail provider: {guardrail_provider.name}")
    
    # Determine which source was provided and create appropriate wrapper
    if args.command:
        wrapper = MCPWrapperServer.wrap_stdio(
            args.command, 
            args.config_file, 
            guardrail_provider,
            args.visualize_ansi_codes
        )
    elif args.url:
        wrapper = MCPWrapperServer.wrap_http(
            args.url, 
            args.config_file, 
            guardrail_provider,
            args.visualize_ansi_codes
        )
    else:
        # This should never happen due to the mutually exclusive group being required
        # But we'll keep it as a fallback error message
        print("Error: Either --command, --url, or --list-guardrail-providers must be provided", file=sys.stderr)
        sys.exit(1)
    
    try:
        await wrapper.run()
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        await wrapper.stop_child_process()

if __name__ == "__main__":
    asyncio.run(main())
