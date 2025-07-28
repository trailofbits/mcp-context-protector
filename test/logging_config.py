#!/usr/bin/env python3
"""
Logging configuration for tests.
"""

import logging
import sys


def configure_logging() -> None:
    """Configure logging for tests."""
    # Create a logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Create console handler with a higher log level
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    # Create formatter and add it to the handler
    formatter = logging.Formatter("%(levelname)s - %(name)s - %(message)s")
    console_handler.setFormatter(formatter)

    # Add the handler to the logger
    root_logger.addHandler(console_handler)

    # Configure specific loggers
    logging.getLogger("guardrails").setLevel(logging.DEBUG)
    logging.getLogger("llama_firewall_provider").setLevel(logging.DEBUG)

    return root_logger
