# Context Protector

A security wrapper for MCP servers that enforces trust-on-first-use pinning of tool descriptions and parameters.

## Overview

Context Protector is a security wrapper for MCP servers that provides trust-on-first-use pinning for server configuration data. Any deviation from the approved or known-good server configuration will cause downstream tool calls to be blocked until the user explicitly approves the changed server configuration. Server approval is handled through the `approve_server_config` tool, which the wrapper adds to the downstream server's tool list.

Implementing these security controls through a wrapper (rather than through a separate tool that lives outside the host app) streamlines enforcement, makes the tool as frictionless as possible for the user, and ensures universal compatibility with all MCP apps.

## Server configuration semantics and threats

Context Protector currently compares tool descriptions and input schemas to determine whether a server configuration is equivalent to any approved one. Comparisons are semantic and ignore irrelevant factors like tool order.

The database of server configurations is stored in a JSON-encoded file at `~/.context-protector/config`. If a server configuration is in that file, it's approved and will run without tool blocking and without requiring user approval. The wrapper server checks downstream server configurations as soon as the connection is initiated and again whenever the wrapper receives a notification that the downstream server's tools have changed (`notifications/tools/list_changed`).

Servers are uniquely identified by their type and an identifier, which is either a URL or the command string that launches the server. context-protector does not care about changes to a server's name in the host app's configuration (such as the `claude_desktop_config.json` file). If the command string (or URL) is unchanged, it's treated as the same server, and if the command string has changed, even in inconsequential ways, it's treated as a different server, and the configuration will need to be approved exactly as if context-protector were seeing the server for the first time.

## Usage

Context Protector currently supports the stdio and SSE transports. It does not yet fully support the current streamable HTTP transport, but it will as soon as an official release of the Python SDK adds support for streamable HTTP.

To start using Context Protector, first set up a virtual environment and install dependencies:

```bash
# Environment setup (can also use venv directly)
uv venv && uv pip install -r requirements.txt

# Run tests if you like
uv run pytest -v
```

To start the server through the Context Protector wrapper, run `mcp_wrapper.py` with either the `--command <COMMAND>` or `--url <URL>` argument:

```
# Start the wrapper with an stdio server
uv run mcp_wrapper.py --command DOWNSTREAM_SERVER_COMMAND

# Start the wrapper with an HTTP server
uv run mcp_wrapper.py --url DOWNSTREAM_SERVER_URL
```

Configure your host app to run the command above using full paths to `uv`. In the case of Claude Desktop, your `claude_config.json` file should look something like this:

```json
{
  "mcpServers": {
    "wrapped_weather": {
      "command": "/Users/user/.local/bin/uv",
      "args": ["--directory", "/path/to/context-protector", "run", "--command", "/path/to/node /path/to/downstream/server.js"]
    }
  }
}
```

## Development

### Setup

Using `uv`:
```bash
# Create virtual environment
uv venv

# Install dependencies
uv pip install -r requirements.txt
```

Using `venv`:

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Testing

```bash
# Run all tests
pytest

# Run specific tests
pytest tests/test_mcp_wrapper.py::TestMCPWrapper::test_approve_with_correct_config
```

### Code Quality

```bash
# Lint code
ruff check .

# Format code
ruff format .
```

# To do

* Add server instructions to server configs
* Add support for resources
* Add built-in detection for prompt injection in tool descriptions