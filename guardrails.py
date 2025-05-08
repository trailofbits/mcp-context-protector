#!/usr/bin/env python3
"""
Guardrails module for MCP Context Protector.
Provides functionality to load and manage guardrail providers.
"""
import importlib
import inspect
import pkgutil
import logging
import sys
import types
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Type, Union

# We need to define the base classes first before importing the providers
# The actual import happens inside the load_guardrail_providers function

logger = logging.getLogger("guardrails")

@dataclass
class GuardrailAlert:
    """
    Class representing an alert triggered by a guardrail provider.
    
    Attributes:
        explanation: Human-readable explanation of why the guardrail was triggered
        data: Arbitrary data associated with the alert
    """
    explanation: str
    data: Dict[str, Any] = field(default_factory=dict)

class GuardrailProvider:
    """Base class for guardrail providers."""
    
    @property
    def name(self) -> str:
        """Get the provider name."""
        raise NotImplementedError("Guardrail providers must implement the name property")
    
    def check_server_config(self, config) -> Optional[GuardrailAlert]:
        """
        Check a server configuration against the guardrail.
        
        Args:
            config: The server configuration to check
            
        Returns:
            Optional GuardrailAlert if guardrail is triggered, or None if the configuration is safe
        """
        raise NotImplementedError("Guardrail providers must implement check_server_config method")

def _is_provider_class(obj) -> bool:
    """
    Check if an object is a valid guardrail provider class.
    
    Args:
        obj: The object to check
        
    Returns:
        True if it's a valid provider class, False otherwise
    """
    if not inspect.isclass(obj):
        return False
    if obj.__name__ == 'GuardrailProvider':
        return False
    # Check for required attributes and methods
    has_name = hasattr(obj, 'name') and isinstance(getattr(obj, 'name'), property)
    has_check = hasattr(obj, 'check_server_config') and callable(getattr(obj, 'check_server_config'))
    
    return has_name and has_check

def load_guardrail_providers() -> Dict[str, Type[GuardrailProvider]]:
    """
    Load all guardrail providers from the guardrail_providers package.
    
    Looks for classes that have:
    - A 'name' property
    - A 'check_server_config' method
    
    Returns:
        Dictionary mapping provider names to provider classes
    """
    providers = {}
    
    # Import guardrail_providers here to avoid circular imports
    import guardrail_providers
    
    # Find all modules in the guardrail_providers package
    for _, name, is_pkg in pkgutil.iter_modules(guardrail_providers.__path__):
        if is_pkg:
            continue  # Skip sub-packages, only process modules
            
        try:
            path = f"guardrail_providers.{name}"
            # Import the module
            module = importlib.import_module(path)
            
            # Fix inheritance for any placeholder GuardrailProvider classes
            # This ensures that classes defined before GuardrailProvider was available
            # will still inherit from the real GuardrailProvider class
            for obj_name in dir(module):
                obj = getattr(module, obj_name)
                if (inspect.isclass(obj) and 
                    obj.__module__ == module.__name__ and 
                    hasattr(obj, '__bases__')):
                    
                    # Check if the class inherits from a placeholder GuardrailProvider
                    bases = list(obj.__bases__)
                    for i, base in enumerate(bases):
                        if (base.__name__ == 'GuardrailProvider' and 
                            base.__module__ == module.__name__):
                            # Replace with the real GuardrailProvider
                            bases[i] = GuardrailProvider
                            obj.__bases__ = tuple(bases)
                            logger.debug(f"Fixed inheritance for {obj.__name__}")
            
            # Find all provider classes in the module
            for obj_name in dir(module):
                obj = getattr(module, obj_name)
                if _is_provider_class(obj):
                    # Create an instance to get the name
                    provider_instance = obj()
                    provider_name = provider_instance.name
                    
                    providers[provider_name] = obj
                    logger.info(f"Loaded guardrail provider: {provider_name}")
                    
        except Exception as e:
            logger.error(f"Error loading guardrail provider module {name}: {e}")
            
    return providers

def get_provider_names() -> List[str]:
    """
    Get a list of available guardrail provider names.
    
    Returns:
        List of provider names that were successfully loaded
    """
    return list(load_guardrail_providers().keys())

def get_provider(name: str) -> Optional[GuardrailProvider]:
    """
    Get a guardrail provider by name.
    
    Args:
        name: The name of the provider
        
    Returns:
        An instance of the provider, or None if not found
    """
    providers = load_guardrail_providers()
    
    if name in providers:
        return providers[name]()
    
    return None