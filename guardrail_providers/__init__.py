#!/usr/bin/env python3
"""
Guardrail providers package for MCP Context Protector.
Contains various guardrail implementations that can check server configurations.
"""
import os
import sys

# Check if we're running in a test environment
is_test = 'pytest' in sys.modules or any('test' in arg.lower() for arg in sys.argv)

# Always import the real providers
from .llama_firewall import LlamaFirewallProvider

# Import mock providers only when testing
if is_test:
    from .mock_provider import (
        MockGuardrailProvider,
        AlwaysAlertGuardrailProvider,
        NeverAlertGuardrailProvider
    )