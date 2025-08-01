"""Guardrails module for mcp-context-protector.

Provides functionality to load and manage guardrail providers.
"""

import importlib
import inspect
import logging
import pkgutil
import sys
from typing import Any

from . import guardrail_providers
from .guardrail_types import GuardrailProvider

logger = logging.getLogger("guardrails")

# Check if we're running in a test environment
IS_TEST = "pytest" in sys.modules or any("test" in arg.lower() for arg in sys.argv)

# List of test-only providers that should be excluded from production
TEST_ONLY_PROVIDERS = {
    "Mock Guardrail Provider",
    "Always Alert Provider",
    "Never Alert Provider",
}


def _is_provider_class(obj: Any) -> bool:  # noqa: ANN401
    """Check if an object is a valid guardrail provider class.

    Args:
    ----
        obj: The object to check

    Returns:
    -------
        True if it's a valid provider class, False otherwise

    """
    if not inspect.isclass(obj):
        return False
    if obj.__name__ == "GuardrailProvider":
        return False
    has_name = hasattr(obj, "name") and isinstance(obj.name, property)
    has_check = hasattr(obj, "check_server_config") and callable(obj.check_server_config)

    return has_name and has_check


def load_guardrail_providers() -> dict[str, type[GuardrailProvider]]:
    """Load all guardrail providers from the guardrail_providers package.

    Looks for classes that have:
    - A 'name' property
    - A 'check_server_config' method

    Returns
    -------
        Dictionary mapping provider names to provider classes

    """
    providers = {}

    # Find all modules in the guardrail_providers package
    for _, name, is_pkg in pkgutil.iter_modules(guardrail_providers.__path__):
        if is_pkg:
            continue  # Skip sub-packages, only process modules

        try:
            # Get the current module's package path
            current_package = __name__.rsplit(".", 1)[0]
            path = f"{current_package}.guardrail_providers.{name}"
            module = importlib.import_module(path)

            # Find all provider classes in the module
            for obj_name in dir(module):
                obj = getattr(module, obj_name)
                if _is_provider_class(obj):
                    provider_instance = obj()
                    provider_name = provider_instance.name

                    # Only add to providers if it's not a test-only provider or we're in test mode
                    if IS_TEST or provider_name not in TEST_ONLY_PROVIDERS:
                        providers[provider_name] = obj
                        logger.info("Loaded guardrail provider: %s", provider_name)
                    else:
                        logger.debug("Skipped test-only guardrail provider: %s", provider_name)

        except Exception:
            logger.exception("Error loading guardrail provider module %s", name)

    return providers


def get_provider_names() -> list[str]:
    """Get a list of available guardrail provider names.

    Returns
    -------
        List of provider names that were successfully loaded

    """
    return list(load_guardrail_providers().keys())


def get_provider(name: str) -> GuardrailProvider | None:
    """Get a guardrail provider by name.

    Args:
    ----
        name: The name of the provider

    Returns:
    -------
        An instance of the provider, or None if not found

    """
    providers = load_guardrail_providers()

    if name in providers:
        return providers[name]()

    return None
