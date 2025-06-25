# Context Protector

## Overview

context-protector is a security wrapper for MCP servers that addresses risks associated with running untrusted MCP servers, including line jumping, unexpected server configuration changes, and other prompt injection attacks. Implementing these security controls through a wrapper (rather than through a scanner that runs before a tool is installed or by adding security features to an MCP host app) streamlines enforcement and ensures universal compatibility with all MCP apps.

## Features

- Trust-on-first-use pinning of server configurations
- Automatic blocking of unapproved configuration changes
- Guardrail scanning and quarantining of tool responses
- ANSI control character sanitization

### Security risks and controls

| Risk    | Relevant control |
| -------- | ------- |
| Line jumping  | Server configuration blocking, approval and pinning; guardrail evaluation of server instructions and tool descriptions    |
| Server configuration changes/rug pulls | Server configuration pinning     |
| User deception through ANSI control characters    | ANSI control character sanitization    |
| Other prompt injection attacks  | Tool response guardrails and quarantining. |



## Server configuration pinning

context-protector uses a trust-on-first use pinning system for MCP server configurations. Any deviation from the approved/known-good server configuration will block downstream tool calls until the user explicitly approves the changed server configuration. Server approval is handled through context-protector's command-line interface.
 
Server configuration comparisons compare server instructions, tool descriptions, and tool input schemas to determine whether a server configuration is equivalent to any approved one. Comparisons are semantic and ignore irrelevant factors like tool order and parameter order.

The database of server configurations is stored in a JSON-encoded file whose default location is `~/.context-protector/servers.json`. If a server configuration is in that file, it's approved and will run without tool blocking and without requiring user approval. The wrapper server checks downstream server configurations as soon as the connection is initiated and again whenever the wrapper receives a notification that the downstream server's tools have changed (`notifications/tools/list_changed`).

Servers are uniquely identified in this file by their type and an identifier, which is either a URL or the command string that launches the server. context-protector does not care about changes to a server's name in the host app's configuration (such as the `claude_desktop_config.json` file). If the command string (or URL) is unchanged, it's treated as the same server, and if the command string has changed, even in inconsequential ways, it's treated as a different server, and the configuration will need to be approved exactly as if context-protector were seeing the server for the first time.

To approve a server's configuration and allow the host app to connect to it, run the CLI app with the argument `--review-server`. The wrapper server will connect to the downstream server, retrieve its configuration, and display it in the shell. If you approve the configuration, it will be added to the database and you can restart your host app to use it normally.

## Tool response guardrails and quarantine

If context-protector is launched with a guardrail provider, it will use the chosen provider to scan every tool response for prompt injection attacks. If an attack is detected, the response will be saved in a quarantine database at `~/.context-protector/quarantine.json`. The host app will receive a response that includes the guardrail provider's output.

To review the response and release it from the quarantine, run the app with the argument `--review-quarantine`, optionally with the `--quarantine-id <ID>` argument to specify which quarantined response you want to review. The app will then display the tool call and response in the shell and let you review it. If you approve the response, the LLM app can then use the `quarantine_release` tool to retrieve the response and continue as normal.

## Getting started

context-protector supports the stdio and SSE transports. It does not yet fully support the streamable HTTP transport introduced in the [March 26, 2025 update](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http) to the protocol specification, but it will as soon as an official release of the Python SDK adds support for streamable HTTP.

To start using Context Protector, first set up a virtual environment and install dependencies:

```bash
# Environment setup
git clone https://github.com/trailofbits/context-protector && cd context-protector
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run tests if you like
pytest -v --timeout=10
```

To start a server through the wrapper, run the `context-protector` script with either the `--command <COMMAND>` or `--sse-url <URL>` argument:

```
# Start the wrapper with an stdio server
/path/to/context-protector/.venv/bin/context-protector --command DOWNSTREAM_SERVER_COMMAND

# Start the wrapper with an HTTP server
/path/to/context-protector/.venv/bin/context-protector --sse-url DOWNSTREAM_SERVER_URL
```

Configure your host app to run the command above using full paths to your virtual env. In the case of Claude Desktop, your `claude_config.json` file should look something like this:

```json
{
  "mcpServers": {
    "wrapped_weather": {
      "command": "/path/to/context-protector/.venv/bin/context-protector",
      "args": ["--command", "/path/to/node /path/to/downstream/server.js"]
    }
  }
}
```

To include support for tool response scanning, include the `--guardrail-provider` argument:

```
/path/to/context-protector/.venv/bin/context-protector --command DOWNSTREAM_SERVER_COMMAND --guardrail-provider LlamaFirewall
```

Review functions:

```
/path/to/context-protector/.venv/bin/context-protector --review-server
/path/to/context-protector/.venv/bin/context-protector --review-quarantine --quarantine-id <ID>
```

## Usage

```
usage: context-protector [-h] (--command COMMAND | --sse-url URL | --list-guardrail-providers | --review-quarantine) [--config-file CONFIG_FILE]
                         [--guardrail-provider GUARDRAIL_PROVIDER] [--visualize-ansi-codes] [--review-server] [--quarantine-id QUARANTINE_ID]
                         [--quarantine-path QUARANTINE_PATH]

options:
  -h, --help            show this help message and exit
  --command COMMAND     Start a wrapped server over the stdio transport using the specified command
  --sse-url URL         Connect to a remote MCP server over SSE at the specified URL
  --list-guardrail-providers
                        List available guardrail providers and exit
  --review-quarantine   Review and manage quarantined tool responses
  --config-file CONFIG_FILE
                        The path to the wrapper config file
  --guardrail-provider GUARDRAIL_PROVIDER
                        The guardrail provider to use for checking server configurations
  --visualize-ansi-codes
                        Make ANSI escape codes visible by replacing escape characters with 'ESC'
  --review-server       Review and approve server configuration before starting
  --quarantine-id QUARANTINE_ID
                        The ID of a specific quarantined response to review
  --quarantine-path QUARANTINE_PATH
                        The path to the quarantine database file
```