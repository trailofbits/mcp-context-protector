"""Backward-compatibility tests for the typed exception hierarchy.

These tests pin the guarantees the hierarchy makes to existing callers:

- ``ConfigValidationError`` and ``ConnectionConfigError`` are still caught by
  ``except ValueError`` (multiple inheritance), and by
  ``except ContextProtectorError`` for new code.
- ``ToolBlockedError`` carries the block detail as structured attributes,
  not as a JSON string in the message.
- ``ChildServerNotConnectedError`` is still a ``ConnectionError``.

The raise-site tests exercise real code paths (``mcp_json_config`` and
``wrapper_config`` import with stdlib only). They are written against the
migrated code described in migration-guide.md: each site that used to
``raise ValueError`` now raises the typed subclass named here.
"""

import json
import tempfile
from functools import partial
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from mcp import types as mcp_types
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, ErrorData

from contextprotector.errors import (
    ChildServerNotConnectedError,
    ConfigConversionError,
    ConfigLoadError,
    ConfigValidationError,
    ConnectionConfigError,
    ConnectionFailedError,
    ContextProtectorError,
    QuarantineError,
    ServerPinMismatchError,
    ToolBlockedError,
)
from contextprotector.mcp_config import MCPServerConfig
from contextprotector.mcp_json_cli import (
    EnvironmentSelector,
    MCPJsonManager,
    WrapMCPJsonManager,
)
from contextprotector.mcp_json_config import (
    MCPJsonConfig,
    MCPServerSpec,
    MCPUnifiedConfig,
    ProjectMCPSchema,
    SchemaDetector,
)
from contextprotector.mcp_wrapper import MCPWrapperServer
from contextprotector.wrapper_config import MCPWrapperConfig


def assert_dual_catch(raise_fn):
    """Assert the same raise is caught by both old and new handler styles."""
    with pytest.raises(ValueError):
        raise_fn()
    with pytest.raises(ContextProtectorError):
        raise_fn()


def test_compat_classes_keep_value_error_inheritance():
    assert issubclass(ConfigValidationError, ContextProtectorError)
    assert issubclass(ConfigValidationError, ValueError)
    assert issubclass(ConnectionConfigError, ContextProtectorError)
    assert issubclass(ConnectionConfigError, ValueError)


def test_non_compat_classes_do_not_subclass_value_error():
    for cls in (
        ConfigLoadError,
        ConfigConversionError,
        ConnectionFailedError,
        ToolBlockedError,
        ServerPinMismatchError,
        QuarantineError,
    ):
        assert issubclass(cls, ContextProtectorError)
        assert not issubclass(cls, ValueError)


def test_child_server_not_connected_error_still_connection_error():
    assert issubclass(ChildServerNotConnectedError, ConnectionError)
    assert issubclass(ChildServerNotConnectedError, ContextProtectorError)
    assert str(ChildServerNotConnectedError()) == "Child MCP server not connected"


def test_config_validation_sites_catchable_as_value_error():
    assert_dual_catch(lambda: MCPServerSpec.from_dict("not-a-dict"))
    assert_dual_catch(lambda: MCPServerSpec.from_dict({"command": 123}))
    assert_dual_catch(lambda: MCPJsonConfig.from_dict("not-a-dict"))
    assert_dual_catch(lambda: MCPJsonConfig.from_dict({}).save())


def test_config_conversion_sites_raise_typed_error():
    with pytest.raises(ConfigConversionError):
        SchemaDetector.detect_schema({"not-a-known-schema": True})
    with pytest.raises(ConfigConversionError):
        MCPServerSpec(command="python", args=["server.py"]).without_context_protector()


def test_config_load_sites_raise_typed_error():
    with pytest.raises(ConfigLoadError):
        MCPUnifiedConfig("/nonexistent/config.json").get_servers()


def test_connection_config_sites_catchable_as_value_error():
    assert_dual_catch(lambda: MCPWrapperConfig(connection_type="stdio"))
    assert_dual_catch(
        lambda: MCPWrapperConfig(connection_type="stdio", command="x", url="http://y")
    )


def test_tool_blocked_error_carries_structured_fields():
    err = ToolBlockedError(
        "Tool 'delete-file' is not approved.",
        tool_name="delete-file",
        reason="not-approved",
    )
    assert err.tool_name == "delete-file"
    assert err.reason == "not-approved"
    assert str(err) == "Tool 'delete-file' is not approved."


def test_tool_blocked_error_message_is_not_a_json_payload():
    err = ToolBlockedError(
        "Tool 'delete-file' is not approved.",
        tool_name="delete-file",
        reason="not-approved",
    )
    with pytest.raises(json.JSONDecodeError):
        json.loads(str(err))


def test_tool_blocked_error_fields_are_keyword_only():
    with pytest.raises(TypeError):
        ToolBlockedError("message", "delete-file", "not-approved")


def test_typed_catch_must_come_before_value_error_catch():
    # Documents the ordering rule from migration-guide.md: because the compat
    # classes subclass ValueError, an `except ValueError` placed first would
    # shadow the typed catch. New handlers must list the typed type first.
    seen = []
    try:
        raise ConfigValidationError("bad value")
    except ContextProtectorError:
        seen.append("typed")
    except ValueError:
        seen.append("value")
    assert seen == ["typed"]


def test_connection_failed_error_still_connection_error():
    # The downstream-communication failures now typed as
    # ConnectionFailedError previously surfaced as bare ConnectionError,
    # so the compatibility base is preserved (mirrors
    # ChildServerNotConnectedError).
    assert issubclass(ConnectionFailedError, ConnectionError)
    assert issubclass(ConnectionFailedError, ContextProtectorError)
    assert not issubclass(ConnectionFailedError, ValueError)


def test_wrapper_config_remaining_sites_catchable_as_value_error():
    assert_dual_catch(lambda: MCPWrapperConfig(connection_type="http"))
    assert_dual_catch(lambda: MCPWrapperConfig(connection_type="bogus", command="x"))
    assert_dual_catch(lambda: MCPWrapperConfig(connection_type="sse", command="x", url="http://y"))


def test_mcp_server_config_from_json_requires_exactly_one_source():
    assert_dual_catch(MCPServerConfig.from_json)
    assert_dual_catch(partial(MCPServerConfig.from_json, json_str="{}", path="x.json"))


def test_environment_selector_unknown_environment():
    schema = ProjectMCPSchema()
    data = {"projects": {"dev": {}, "prod": {}}}
    with pytest.raises(ConfigLoadError, match="Environment 'nope' not found"):
        EnvironmentSelector.select_environment(
            schema, data, cli_environment="nope", interactive=False
        )


def test_project_schema_unknown_project():
    with pytest.raises(ConfigLoadError, match="Project 'missing' not found"):
        ProjectMCPSchema().get_servers({"projects": {"dev": {}}}, "missing")


def test_toggle_protection_handles_conversion_error_gracefully():
    """Regression test: with_context_protector/without_context_protector now
    raise ConfigConversionError (not ValueError), so the CLI's
    _toggle_server_protection must catch the typed hierarchy instead of
    letting the traceback escape to the user."""
    with tempfile.NamedTemporaryFile(suffix=".json") as f:
        manager = MCPJsonManager(f.name)
        manager.config = MCPJsonConfig()
        # Protected spec in a pattern the unwrapper cannot parse.
        manager.config.add_server(
            "weird-server",
            MCPServerSpec(command="mcp-context-protector", args=["--weird-flag"]),
        )
        with patch("builtins.print"):
            manager._toggle_server_protection(1)  # must not raise


def test_wrap_servers_handles_already_protected_gracefully():
    """Regression test: wrapping an already-protected server raises
    ConfigConversionError, which _wrap_servers must report per-server
    instead of aborting the whole run."""
    with tempfile.NamedTemporaryFile(suffix=".json") as f:
        manager = WrapMCPJsonManager(f.name)
        manager.config = MCPJsonConfig()
        manager.config.add_server(
            "protected-server",
            MCPServerSpec(
                command="mcp-context-protector",
                args=["--command-args", "python", "server.py"],
            ),
        )
        manager.servers_to_wrap = ["protected-server"]
        with patch("builtins.print"):
            manager._wrap_servers()  # must not raise


def _make_wrapper_server():
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    return MCPWrapperServer(config_path=tmp.name)


@pytest.mark.asyncio()
async def test_update_tools_without_session_raises_child_server_not_connected():
    server = _make_wrapper_server()
    with pytest.raises(ChildServerNotConnectedError):
        await server.update_tools()


@pytest.mark.asyncio()
async def test_update_tools_empty_tools_raises_connection_failed_error():
    server = _make_wrapper_server()

    class _EmptySession:
        async def list_tools(self):
            return SimpleNamespace(tools=[])

    server.session = _EmptySession()
    with pytest.raises(ConnectionFailedError, match="No tools received"):
        await server.update_tools()


@pytest.mark.asyncio()
async def test_proxy_tool_mcp_error_raises_connection_failed_error():
    """The downstream-communication failures that previously surfaced as
    bare ConnectionError are now typed ConnectionFailedError, which must
    still be catchable as ConnectionError."""
    server = _make_wrapper_server()

    class _FailingSession:
        async def call_tool(self, _name, _arguments):
            raise McpError(ErrorData(code=INTERNAL_ERROR, message="boom"))

    server.session = _FailingSession()
    with pytest.raises(ConnectionFailedError) as exc_info:
        await server._proxy_tool_to_downstream("mytool", {})
    assert isinstance(exc_info.value, ConnectionError)
    assert isinstance(exc_info.value, ContextProtectorError)


def _call_tool_via_handler(server, name, approval_status):
    """Drive the registered call_tool handler like the MCP server would."""
    if approval_status is None:
        if hasattr(server, "approval_status"):
            del server.approval_status
    else:
        server.approval_status = approval_status
    handler = server.server.request_handlers[mcp_types.CallToolRequest]
    request = SimpleNamespace(
        params=SimpleNamespace(name=name, arguments={}),
    )
    return handler(request)


@pytest.mark.asyncio()
async def test_tool_blocked_raise_paths_report_structured_message():
    """Each approval-blocking path in the tool-call handler must surface a
    ToolBlockedError whose message carries the tool name and reason (the
    structured replacement for the old JSON-string ValueError). The
    registered handler converts it to an isError result for the caller."""
    scenarios = [
        # (approval_status, expected message fragment)
        (None, "approval status not initialized"),
        ({"is_new_server": True}, "not approved"),
        (
            {
                "is_new_server": False,
                "instructions_approved": False,
                "server_approved": True,
            },
            "instructions have changed",
        ),
        (
            {
                "is_new_server": False,
                "instructions_approved": True,
                "tools": {"mytool": False},
            },
            "Tool 'mytool' is not approved",
        ),
    ]
    for approval_status, fragment in scenarios:
        server = _make_wrapper_server()
        server.session = object()  # connected; approval checks decide
        result = await _call_tool_via_handler(server, "mytool", approval_status)
        call_result = result.root
        assert call_result.isError is True
        text = call_result.content[0].text
        assert "mytool" in text
        assert fragment in text
