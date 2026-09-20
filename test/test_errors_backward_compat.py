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

import pytest

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
from contextprotector.mcp_json_config import (
    MCPJsonConfig,
    MCPServerSpec,
    MCPUnifiedConfig,
    SchemaDetector,
)
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
