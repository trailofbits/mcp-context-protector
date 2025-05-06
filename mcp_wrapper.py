#!/usr/bin/env python3
import argparse
import asyncio
import logging
import json
from typing import List

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

logger = logging.getLogger("mcp_wrapper")

class MCPWrapperServer:
    @classmethod
    def wrap_stdio(cls, command: str, config_path: str = None):
        """
        Create a wrapper server that connects to a child process via stdio.
        
        Args:
            command: The command to run as a child process
            config_path: Optional path to the wrapper config file
            
        Returns:
            An instance of MCPWrapperServer configured for stdio
        """
        instance = cls(config_path)
        instance.connection_type = "stdio"
        instance.child_command = command
        return instance
        
    @classmethod
    def wrap_http(cls, url: str, config_path: str = None):
        """
        Create a wrapper server that connects to a remote MCP server via HTTP.
        
        Args:
            url: The URL to connect to for a remote MCP server
            config_path: Optional path to the wrapper config file
            
        Returns:
            An instance of MCPWrapperServer configured for HTTP
        """
        instance = cls(config_path)
        instance.connection_type = "http"
        instance.server_url = url
        return instance
    
    def __init__(self, config_path: str = None):
        """
        Initialize the wrapper server with common attributes.
        Use wrap_stdio or wrap_http class methods instead of calling this directly.
        
        Args:
            config_path: Optional path to the wrapper config file
        """
        self.child_command = None
        self.server_url = None
        self.connection_type = None
        self.server_identifier = None  # Will be set after determining connection details
        self.child_process = None
        self.client_context = None
        self.streams = None
        self.session = None
        self.tool_specs = []
        self.config_approved = False
        self.config_path = config_path
        self.config_db = MCPConfigDatabase(config_path)
        self.saved_config = None  # Will be loaded after server_identifier is set
        self.current_config = MCPServerConfig()
        self.server = Server("mcp_wrapper")
        self._setup_server()

    def _setup_server(self):
        """Setup MCP server handlers"""

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

            return all_tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> List[types.TextContent]:
            """
            Handle tool use requests - either approve config, proxy to downstream server,
            or block if config not approved.
            """
            logger.info(f"Tool call with name {name} and config_approved {self.config_approved}")
            if not self.session and name != "approve_server_config":
                raise ValueError("Child MCP server not connected")

            # Special handling for our approve_server_config tool
            if name == "approve_server_config":
                result = await self._handle_approve_config(arguments.get("config", ""))
                return [types.TextContent(type="text", text=result)]

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

                # Create blocked response with diff
                blocked_response = {
                    "status": "blocked",
                    "server_config": serialized_config,
                    "diff": diff_text,
                    "reason": "Server configuration not approved - all tools blocked",
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
                        text_parts.append(content.text)
                
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
                self.config_approved = False
                asyncio.create_task(self.update_tools())
            else:
                logger.info(f"Received notification: {message.method}")
        else:
            logger.info(f"Received non-notification message: {type(message)}")

    async def update_tools(self):
        try:
            # Get updated tools from the downstream server
            downstream_tools = await self.session.list_tools()

            assert downstream_tools.tools
            logger.info(f"Received {len(downstream_tools.tools)} tools after update notification")
            
            # Process the updated tools
            logger.info(f"Handling tool update with f{downstream_tools.tools}")
            await self._handle_tool_updates(downstream_tools.tools)
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
        
        # Check if we can auto-approve based on saved config
        if self.saved_config and self.saved_config == self.current_config:
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
            
            await self.session.initialize()
            
            # Get tool specifications from the downstream server
            downstream_tools = await self.session.list_tools()
            assert downstream_tools.tools

            # Convert MCP tools to our internal format
            self.tool_specs = self._convert_mcp_tools_to_specs(downstream_tools.tools)
                
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
            
            await self.session.initialize()
            
            # Get tool specifications from the downstream server
            downstream_tools = await self.session.list_tools()
            assert downstream_tools.tools

            # Convert MCP tools to our internal format
            self.tool_specs = self._convert_mcp_tools_to_specs(downstream_tools.tools)
                
        except Exception as e:
            logger.error(f"Error connecting to downstream server via SSE: {e}")
            raise

    def _create_server_config(self) -> MCPServerConfig:
        """Create a server configuration from the tool specs."""
        config = MCPServerConfig()

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

            # Set approved flag
            self.config_approved = True

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
                            notification_options=NotificationOptions(tools_changed=True),
                            experimental_capabilities={},
                        ),
                    ),
                )
        finally:
            await self.stop_child_process()


async def main():
    parser = argparse.ArgumentParser(description="MCP Wrapper Server")
    
    # Create mutually exclusive group for command and URL
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--command", help="The command to run as a child process")
    source_group.add_argument("--url", help="The URL to connect to for a remote MCP server")
    
    # Add config file argument with new name
    parser.add_argument("--config-file", help="The path to the wrapper config file", default="")

    args = parser.parse_args()

    # Determine which source was provided and create appropriate wrapper
    if args.command:
        wrapper = MCPWrapperServer.wrap_stdio(args.command, args.config_file)
    elif args.url:
        wrapper = MCPWrapperServer.wrap_http(args.url, args.config_file)
    else:
        raise ValueError("Either --command or --url must be provided")
    
    try:
        await wrapper.run()
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        await wrapper.stop_child_process()

if __name__ == "__main__":
    asyncio.run(main())
