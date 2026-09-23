# Migration guide: typed exception hierarchy

`src/contextprotector/errors.py` replaces the bare `ValueError` (and bare
`ConnectionError`) raises scattered across the codebase with a hierarchy
rooted at `ContextProtectorError`. This guide is for contributors and
downstream callers updating their error handling.

## The hierarchy

| Exception | Also a | Raised for |
|---|---|---|
| `ContextProtectorError` | `Exception` | Base class for everything below |
| `ConfigValidationError` | `ValueError` | Malformed config values (bad server spec, bad name, bad JSON shape) |
| `ConfigLoadError` | — | Config file/schema/environment lookup failures |
| `ConfigConversionError` | — | Schema conversion and wrap/unwrap failures |
| `ConnectionConfigError` | `ValueError` | Missing or inconsistent connection settings |
| `ConnectionFailedError` | `ConnectionError` | Downstream server communication failures |
| `ChildServerNotConnectedError` | `ConnectionError` | Child MCP server not connected (moved here from `mcp_wrapper`) |
| `ToolBlockedError` | — | Tool call blocked by approval/guardrails |
| `ServerPinMismatchError` | — | Pinned server definition no longer matches its approval |
| `QuarantineError` | — | Quarantine lookup and release failures |

## Backward-compatibility guarantees

These are pinned by `test/test_errors_backward_compat.py`:

- `ConfigValidationError` and `ConnectionConfigError` subclass `ValueError`,
  so existing `except ValueError` handlers keep working unchanged.
- `ChildServerNotConnectedError` and `ConnectionFailedError` subclass
  `ConnectionError`, so existing `except ConnectionError` handlers keep
  working unchanged.
- `ChildServerNotConnectedError()` still stringifies to
  `"Child MCP server not connected"`.

## `except`-ordering rule

Because the compatibility classes use multiple inheritance, an
`except ValueError` placed *before* the typed catch will shadow it.
New handlers must list the typed exception first:

```python
try:
    ...
except ConfigValidationError:  # typed catch first
    ...
except ValueError:  # legacy catch second
    ...
```

Catching `ContextProtectorError` covers every error this package raises.

## `ToolBlockedError` API change

Previously, blocked tool calls raised `ValueError` with a JSON payload in the
message (`{"status": "blocked", "reason": ...}`), forcing callers to
`json.loads(str(exc))`. Now the detail is carried as structured attributes:

```python
try:
    ...
except ToolBlockedError as e:
    e.tool_name  # name of the blocked tool
    e.reason     # machine-usable reason for the block
    str(e)       # human-readable message (not JSON)
```

`tool_name` and `reason` are keyword-only constructor arguments.
