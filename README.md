# mcp-context-protector

## Overview

mcp-context-protector is a security wrapper for MCP servers that addresses risks associated with running untrusted MCP servers, including line jumping, unexpected server configuration changes, and other prompt injection attacks. Implementing these security controls through a wrapper (rather than through a scanner that runs before a tool is installed or by adding security features to an MCP host app) streamlines enforcement and ensures universal compatibility with all MCP apps.

## Features

- Trust-on-first-use pinning of server configurations
- Automatic blocking of unapproved configuration changes
- Guardrail scanning and quarantining of tool responses
- ANSI control character sanitization
- Assisted editing of `mcp.json` files

## Quickstart

Installation:

```
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
# Download mcp-context-protector
git clone https://github.com/trailofbits/mcp-context-protector
# Install dependencies
cd mcp-context-protector
uv sync
```

To make it easier to launch `mcp-context-protector`, we recommend updating `mcp-context-protector.sh` to contain the full path to `uv`. Some MCP clients, including Claude Desktop, replace the `PATH` environment variable with a minimal set of paths when launching MCP servers, which can make your `claude_desktop_config.json` file unwieldy and hard to maintain. Including a full path to `uv` in the launcher helps mitigate this problem.

Now configure your client to run your MCP servers through `mcp-context-protector`, and tool configuration pinning will automatically be enabled. Here's a sample Claude Desktop config:

```
{
  "mcpServers": {
    "wrapped_acme_server": {
      "command": "/path/to/mcp-context-protector/mcp-context-protector.sh",
      "args": ["--command", "/path/to/node /path/to/acme/server.js"]
    }
  }
}
```

Alternatively, use `--command-args` to have `mcp-context-protector` concatenate all arguments that follow into one command string:

```
{
  "mcpServers": {
    "wrapped_acme_server": {
      "command": "/path/to/mcp-context-protector/mcp-context-protector.sh",
      "args": ["--command-args", "/path/to/node", "/path/to/acme/server.js", "--acme-enhanced"]
    }
  }
}
```

TL;DR: use `--command-args` if your MCP client mangles your stdio server command, but be careful with escaping of shell metacharacters.

Longer explanation: Some clients (including, as of this writing, Cursor) will construct their MCP server commands by concatenating the arguments together into a space-delimited string. That is, `mcp-context-protector.sh --command "cmd arg1 arg2 --arg3"` will become `mcp-context-protector.sh --command cmd arg1 arg2 --arg3`, and `mcp-context-protector` will think `arg1` through `--arg3` are meant as arguments to the wrapper, not to the child command. The `--command-args` option addresses this issue.

## Security risks and controls

| Risk    | Relevant control |
| -------- | ------- |
| Line jumping  | Server configuration blocking, approval and pinning; guardrail evaluation of server instructions and tool descriptions    |
| Server configuration changes/rug pulls | Server configuration pinning     |
| User deception through ANSI control characters    | ANSI control character sanitization    |
| Other prompt injection attacks  | Tool response guardrails and quarantining |



## Server configuration pinning

mcp-context-protector uses a trust-on-first use pinning system for MCP server configurations. Any deviation from the approved/known-good server configuration will block downstream tool calls until the user explicitly approves the changed server configuration. Server approval is handled through mcp-context-protector's command-line interface.

Server configuration comparisons compare server instructions, tool descriptions, and tool input schemas to determine whether a server configuration is equivalent to any approved one. Comparisons are semantic and ignore irrelevant factors like tool order and parameter order.

The database of server configurations is stored in a JSON-encoded file whose default location is `~/.mcp-context-protector/servers.json`. If a server configuration is in that file, it's approved and will run without tool blocking and without requiring user approval. The wrapper server checks downstream server configurations as soon as the connection is initiated and again whenever the wrapper receives a notification that the downstream server's tools have changed (`notifications/tools/list_changed`).

Servers are uniquely identified in this file by their type and an identifier, which is either a URL or the command string that launches the server. mcp-context-protector does not care about changes to a server's name in the host app's configuration (such as the `claude_desktop_config.json` file). If the command string (or URL) is unchanged, it's treated as the same server, and if the command string has changed, even in inconsequential ways, it's treated as a different server, and the configuration will need to be approved exactly as if mcp-context-protector were seeing the server for the first time.

To approve a server's configuration and allow the host app to connect to it, run the CLI app with the argument `--review-server`. The wrapper server will connect to the downstream server, retrieve its configuration, and display it in the shell. If you approve the configuration, it will be added to the database, and you can restart your host app to use it normally.

## Tool response guardrails and quarantine

If mcp-context-protector is launched with a guardrail provider, it will use the chosen provider to scan every tool response for prompt injection attacks. If an attack is detected, the response will be saved in a quarantine database at `~/.mcp-context-protector/quarantine.json`. The host app will receive a response that includes the guardrail provider's output.

To review the response and release it from the quarantine, run the app with the argument `--review-quarantine`, optionally with the `--quarantine-id <ID>` argument to specify which quarantined response you want to review. The app will then display the tool call and response in the shell and let you review it. If you approve the response, the LLM app can then use the `quarantine_release` tool to retrieve the response and continue as normal.

## Configuring mcp-context-protector

`mcp-context-protector` is packaged with `uv` and can be run with `uv run mcp-context-protector`. To start a server through the wrapper, run the `mcp-context-protector.sh` launcher script with the arguments `--command <COMMAND>`, `--command-args <CMD> <ARG1> <ARG2>` or `--url <URL>`:

```
# Start the wrapper with an stdio server
/path/mcp-context-protector.sh --command "DOWNSTREAM_SERVER_COMMAND ARG1 ARG2"

# Start the wrapper with an stdio server (alternative)
/path/mcp-context-protector.sh --command-args DOWNSTREAM_SERVER_COMMAND ARG1 ARG2

# Start the wrapper with an HTTP server
/path/mcp-context-protector.sh --url DOWNSTREAM_SERVER_URL
```

If your downstream server requires the older SSE transport, use `--sse-url <URL>`.

To include support for tool response scanning, include the `--guardrail-provider` argument:

```
mcp-context-protector.sh --command DOWNSTREAM_SERVER_COMMAND --guardrail-provider LlamaFirewall
```

Review functions:

```
mcp-context-protector.sh --review-all-servers
mcp-context-protector.sh --review-quarantine --quarantine-id <ID>
```

## Management of mcp.json files

`mcp-context-protector` can also help add the wrapper server to any existing configuration files that follow the `mcp.json` standard. To edit a specific file, use the `--manage-all-mcp-json` flag. All configuration files found at known locations on the filesystem will automatically be detected. Use the CLI interface to add and remove the wrapper from MCP servers. Configuration files located in project directories or code repositories will not be detected automatically. To edit a project's MCP configuration file, or any other specified file, use `--manage-mcp-json-file FILENAME`.

The following MCP clients' configuration files will automatically be detected:

* Claude Code
* Claude Desktop
* Continue.dev
* Cursor
* Visual Studio Code
* Windsurf


## Usage

```
usage: mcp-context-protector [-h] [--command COMMAND] [--command-args COMMAND_ARGS [COMMAND_ARGS ...]] [--url URL] [--sse-url SSE_URL] [--list-guardrail-providers]
                             [--review-server] [--review-quarantine] [--review-all-servers] [--manage-mcp-json-file MANAGE_MCP_JSON_FILE] [--manage-all-mcp-json]
                             [--wrap-mcp-json CONFIG_FILE] [--environment ENV] [--server-config-file SERVER_CONFIG_FILE] [--guardrail-provider GUARDRAIL_PROVIDER]
                             [--visualize-ansi-codes] [--quarantine-id QUARANTINE_ID] [--quarantine-path QUARANTINE_PATH]

options:
  -h, --help            show this help message and exit
  --server-config-file SERVER_CONFIG_FILE
                        The path to the server config database file (default: ~/.mcp-context-protector/servers.json)
  --guardrail-provider GUARDRAIL_PROVIDER
                        The guardrail provider to use for checking server configurations
  --visualize-ansi-codes
                        Make ANSI escape codes visible by replacing escape characters with 'ESC'
  --quarantine-id QUARANTINE_ID
                        The ID of a specific quarantined response to review
  --quarantine-path QUARANTINE_PATH
                        The path to the quarantine database file (default: ~/.mcp-context-protector/quarantine.json)

  --command COMMAND     Start a wrapped server over the stdio transport using the specified command
  --command-args COMMAND_ARGS [COMMAND_ARGS ...]
                        Start a wrapped server over the stdio transport using the specified command arguments (space-separated). Supports arguments with dashes (e.g.
                        docker run --rm -i)
  --url URL             Connect to a remote MCP server over streamable HTTP at the specified URL
  --sse-url SSE_URL     Connect to a remote MCP server over SSE at the specified URL
  --list-guardrail-providers
                        List available guardrail providers and exit
  --review-server       Review and approve changes to a specific server configuration (must be used with --command, --command-args, --url or --sse-url)
  --review-quarantine   Review quarantined tool responses
  --review-all-servers  Review all unapproved server configurations
  --manage-mcp-json-file MANAGE_MCP_JSON_FILE
                        Interactively manage an MCP JSON configuration file
  --manage-all-mcp-json
                        Find and manage all MCP JSON configuration files from known locations
  --wrap-mcp-json CONFIG_FILE
                        Wrap all MCP servers in the specified JSON config file with context-protector
  --environment ENV, -e ENV
                        Select specific environment/profile for multi-environment config
```

## License
```
Copyright 2025 Trail of Bits

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.

You may obtain a copy of the License at
    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
