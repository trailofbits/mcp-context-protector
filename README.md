# MAPO Context Protector

A security wrapper for Model API Orchestration (MAPO) tools that enforces review and approval of downstream server configurations.

## Overview

The Mapo Context Protector (MCP) sits between a client and a downstream server, intercepting all tool calls. It ensures that the client approves the downstream server configuration before allowing any tool calls to pass through, protecting against unexpected configuration changes.

Key features:
- Intercepts and proxies tool calls to downstream servers
- Caches and validates server configurations against trusted versions
- Requires explicit approval of server configurations before allowing tool usage
- Monitors for dynamic tool changes and enforces reapproval
- Securely stores approved configurations

## Usage

MCP uses stdio-based transport for communication, making it easy to chain tools together.

```bash
# Start a downstream server
python3 tests/simple_downstream_server.py

# Start the wrapper pointing to the downstream server
python3 mcp_wrapper.py "python3 tests/simple_downstream_server.py"
```

## Development

### Setup

```bash
# Create virtual environment (using venv)
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

## Architecture

The MCP wrapper uses the Model Context Protocol (MCP) with stdio transport to communicate between components:

1. The client application sends tool requests via stdio
2. The wrapper server intercepts these requests
3. If the configuration is approved, requests are forwarded to the downstream server
4. If the configuration is not approved, requests are blocked until approval

All communication happens over stdio streams, with no HTTP or TCP networking required.

### Core Components

- `mcp_wrapper.py`: The main wrapper server that intercepts and proxies tool calls
- `mcp_config.py`: Configuration management and diff generation for server configurations
- `mcp_models.py`: Data models for MCP tool specifications and usage

## License

MIT