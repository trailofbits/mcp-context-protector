#!/usr/bin/env python3
"""
Tests for the resource proxying functionality in MCP wrapper.
"""

import base64
import json
import os
import tempfile
import pytest
import asyncio
from pathlib import Path
import sys
import mcp.types as types

# Configure path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import test utilities
from .test_utils import approve_server_config_using_review, run_with_wrapper_session

# Path to the resource test server script
RESOURCE_TEST_SERVER_PATH = Path(__file__).resolve().parent / "resource_test_server.py"


# Local helper function for backward compatibility
async def run_with_wrapper(callback, config_path: str) -> None:
    """
    Run a test with a wrapper connected to the resource test server.

    Args:
        callback: Async function that will be called with the client session
        config_path: Path to the configuration file
    """
    command = f"python {str(RESOURCE_TEST_SERVER_PATH)}"
    await run_with_wrapper_session(callback, "stdio", command, config_path)


class TestResourceProxying:
    """Tests for resource proxying functionality."""

    def setup_method(self) -> None:
        """Set up test by creating temp config file."""
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.config_path = self.temp_file.name

    def teardown_method(self) -> None:
        """Clean up after test."""
        os.unlink(self.config_path)

    @pytest.mark.asyncio()
    async def test_initial_resource_listing(self) -> None:
        """Test that resources are correctly listed from the downstream server."""

        async def callback(session) -> None:
            # List available resources - should work right away regardless of approval status
            initial_resources = await session.list_resources()
            assert len(initial_resources.resources) == 2

            resource_names = [r.name for r in initial_resources.resources]
            assert "Sample data" in resource_names
            assert "Image resource" in resource_names

            # Verify resource details
            sample_data = next(r for r in initial_resources.resources if r.name == "Sample data")
            assert "Sample data resource" in sample_data.description
            assert sample_data.mime_type == "application/json"

        await run_with_wrapper(callback, self.config_path)

    @pytest.mark.asyncio()
    async def test_resource_content_access(self) -> None:
        """Test that resource content can be accessed without config approval."""

        async def callback(session) -> None:
            # Check we can access resource content without approving the server config
            sample_data_result = await session.read_resource("contextprotector://sample_data")

            # Verify the resource content
            assert sample_data_result.contents[0].mimeType == "application/json"

            # Parse the content and check it
            content = json.loads(sample_data_result.contents[0].text)
            assert content["name"] == "Sample Data"
            assert len(content["items"]) == 3

        await run_with_wrapper(callback, self.config_path)

    @pytest.mark.asyncio()
    async def test_resource_changes(self) -> None:
        """
        Test that changes to resources are correctly proxied without affecting
        the approval status of the server configuration.
        """

        # Create the test command
        command = f"python {str(RESOURCE_TEST_SERVER_PATH)}"

        # First do the approval process
        await run_with_wrapper(
            lambda session: asyncio.create_task(
                session.call_tool("test_tool", {"message": "test"})
            ),
            self.config_path,
        )

        # Use review process to approve the config
        await approve_server_config_using_review("stdio", command, self.config_path)

        # Now the main callback after approval
        async def callback(session) -> None:
            # Initial resources check
            initial_resources = await session.list_resources()
            assert len(initial_resources.resources) == 2
            assert "Sample data" in [r.name for r in initial_resources.resources]
            assert "Image resource" in [r.name for r in initial_resources.resources]

            # Toggle to alternate resources
            toggle_result = await session.call_tool("toggle_resources", {})
            assert "Toggled to alternate resources" in toggle_result.content[0].text

            # Wait briefly for notification to be processed
            await asyncio.sleep(0.5)

            # Check updated resources
            updated_resources = await session.list_resources()
            assert len(updated_resources.resources) == 2
            resource_names = [r.name for r in updated_resources.resources]
            assert "Sample data" in resource_names
            assert "Document resource" in resource_names
            assert "Image resource" not in resource_names

            # Verify we can still use tools without re-approval after resource changes
            tool_result = await session.call_tool("test_tool", {"message": "after resource change"})
            response_text = tool_result.content[0].text
            assert "Echo: after resource change" in response_text

            # Verify we can access the new resource
            document_result = await session.read_resource("contextprotector://document_resource")
            assert document_result.contents[0].mimeType == "text/plain"
            assert "sample document resource" in document_result.contents[0].text

            # Verify we can use the updated version of an existing resource
            sample_data_result = await session.read_resource("contextprotector://sample_data")
            assert sample_data_result.contents[0].mimeType == "application/json"
            content = json.loads(sample_data_result.contents[0].text)
            assert content["name"] == "Sample Data"

        # Run the test with the approved config
        await run_with_wrapper(callback, self.config_path)

    @pytest.mark.asyncio()
    async def test_resource_access_with_parameters(self) -> None:
        """Test that resources can be accessed with parameters."""

        async def callback(session) -> None:
            # Access image resource with custom width parameter
            image_result = await session.read_resource("contextprotector://image_resource")

            # Verify the correct parameter was passed through
            assert type(image_result.contents[0]) is types.BlobResourceContents
            assert b"image data" in base64.b64decode(image_result.contents[0].blob)
            assert image_result.contents[0].mimeType == "image/png"

        await run_with_wrapper(callback, self.config_path)


if __name__ == "__main__":
    pytest.main(["-v", __file__])
