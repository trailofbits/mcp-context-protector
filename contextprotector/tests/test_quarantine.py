#!/usr/bin/env python3
"""
Tests for the quarantine system.
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta

from ..quarantine import QuarantinedToolResponse, ToolResponseQuarantine


class TestQuarantinedToolResponse(unittest.TestCase):
    """Tests for the QuarantinedToolResponse class."""

    def test_init(self):
        """Test initialization of a quarantined tool response."""
        response = QuarantinedToolResponse(
            id="test-id",
            tool_name="test-tool",
            tool_input={"param": "value"},
            tool_output="test output",
            reason="test reason",
        )

        self.assertEqual(response.id, "test-id")
        self.assertEqual(response.tool_name, "test-tool")
        self.assertEqual(response.tool_input, {"param": "value"})
        self.assertEqual(response.tool_output, "test output")
        self.assertEqual(response.reason, "test reason")
        self.assertFalse(response.released)
        self.assertIsNone(response.released_at)

    def test_release(self):
        """Test releasing a quarantined tool response."""
        response = QuarantinedToolResponse(
            id="test-id",
            tool_name="test-tool",
            tool_input={"param": "value"},
            tool_output="test output",
            reason="test reason",
        )

        self.assertFalse(response.released)
        self.assertIsNone(response.released_at)

        response.release()

        self.assertTrue(response.released)
        self.assertIsNotNone(response.released_at)

    def test_to_dict(self):
        """Test conversion to dictionary."""
        now = datetime.now()
        response = QuarantinedToolResponse(
            id="test-id",
            tool_name="test-tool",
            tool_input={"param": "value"},
            tool_output="test output",
            reason="test reason",
            timestamp=now,
        )

        data = response.to_dict()

        self.assertEqual(data["id"], "test-id")
        self.assertEqual(data["tool_name"], "test-tool")
        self.assertEqual(data["tool_input"], {"param": "value"})
        self.assertEqual(data["tool_output"], "test output")
        self.assertEqual(data["reason"], "test reason")
        self.assertEqual(data["timestamp"], now.isoformat())
        self.assertFalse(data["released"])
        self.assertIsNone(data["released_at"])

    def test_from_dict(self):
        """Test creation from dictionary."""
        now = datetime.now()
        released_at = now + timedelta(minutes=5)

        data = {
            "id": "test-id",
            "tool_name": "test-tool",
            "tool_input": {"param": "value"},
            "tool_output": "test output",
            "reason": "test reason",
            "timestamp": now.isoformat(),
            "released": True,
            "released_at": released_at.isoformat(),
        }

        response = QuarantinedToolResponse.from_dict(data)

        self.assertEqual(response.id, "test-id")
        self.assertEqual(response.tool_name, "test-tool")
        self.assertEqual(response.tool_input, {"param": "value"})
        self.assertEqual(response.tool_output, "test output")
        self.assertEqual(response.reason, "test reason")
        self.assertEqual(response.timestamp.isoformat(), now.isoformat())
        self.assertTrue(response.released)
        self.assertEqual(response.released_at.isoformat(), released_at.isoformat())


class TestToolCallQuarantine(unittest.TestCase):
    """Tests for the ToolCallQuarantine class."""

    def setUp(self):
        """Set up a temporary file for testing."""
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.temp_file.close()
        self.quarantine = ToolResponseQuarantine(self.temp_file.name)

    def tearDown(self):
        """Clean up the temporary file."""
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)

    def test_quarantine_response(self):
        """Test quarantining a tool response."""
        response_id = self.quarantine.quarantine_response(
            tool_name="test-tool",
            tool_input={"param": "value"},
            tool_output="test output",
            reason="test reason",
        )

        self.assertIsNotNone(response_id)

        # Check that the response was saved to the database
        quarantine = ToolResponseQuarantine(self.temp_file.name)
        response = quarantine.get_response(response_id)

        self.assertIsNotNone(response)
        self.assertEqual(response.tool_name, "test-tool")
        self.assertEqual(response.tool_input, {"param": "value"})
        self.assertEqual(response.tool_output, "test output")
        self.assertEqual(response.reason, "test reason")
        self.assertFalse(response.released)

    def test_release_response(self):
        """Test releasing a quarantined response."""
        # Quarantine a response
        response_id = self.quarantine.quarantine_response(
            tool_name="test-tool",
            tool_input={"param": "value"},
            tool_output="test output",
            reason="test reason",
        )

        # Release it
        result = self.quarantine.release_response(response_id)

        self.assertTrue(result)

        # Check that it was marked as released
        response = self.quarantine.get_response(response_id)
        self.assertTrue(response.released)
        self.assertIsNotNone(response.released_at)

        # Try releasing it again
        result = self.quarantine.release_response(response_id)

        self.assertTrue(result)  # Should still return True

        # Try releasing a non-existent response
        result = self.quarantine.release_response("non-existent")

        self.assertFalse(result)

    def test_list_responses(self):
        """Test listing quarantined responses."""
        # Quarantine two responses
        response_id1 = self.quarantine.quarantine_response(
            tool_name="test-tool-1",
            tool_input={"param": "value1"},
            tool_output="test output 1",
            reason="test reason 1",
        )

        response_id2 = self.quarantine.quarantine_response(
            tool_name="test-tool-2",
            tool_input={"param": "value2"},
            tool_output="test output 2",
            reason="test reason 2",
        )

        # Release one of them
        self.quarantine.release_response(response_id1)

        # List responses without released
        responses = self.quarantine.list_responses(include_released=False)

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], response_id2)

        # List responses with released
        responses = self.quarantine.list_responses(include_released=True)

        self.assertEqual(len(responses), 2)
        self.assertTrue(any(r["id"] == response_id1 for r in responses))
        self.assertTrue(any(r["id"] == response_id2 for r in responses))

    def test_get_response_pairs(self):
        """Test getting request-response pairs."""
        # Quarantine two responses
        response_id1 = self.quarantine.quarantine_response(
            tool_name="test-tool-1",
            tool_input={"param": "value1"},
            tool_output="test output 1",
            reason="test reason 1",
        )

        _response_id2 = self.quarantine.quarantine_response(
            tool_name="test-tool-2",
            tool_input={"param": "value2"},
            tool_output="test output 2",
            reason="test reason 2",
        )

        # Release one of them
        self.quarantine.release_response(response_id1)

        # Get request-response pairs
        pairs = self.quarantine.get_response_pairs()

        # Should only include non-released responses
        self.assertEqual(len(pairs), 1)
        request, response = pairs[0]

        self.assertEqual(request["tool_name"], "test-tool-2")
        self.assertEqual(request["input"], {"param": "value2"})
        self.assertEqual(response, "test output 2")

    def test_delete_response(self):
        """Test deleting a quarantined response."""
        # Quarantine a response
        response_id = self.quarantine.quarantine_response(
            tool_name="test-tool",
            tool_input={"param": "value"},
            tool_output="test output",
            reason="test reason",
        )

        # Delete it
        result = self.quarantine.delete_response(response_id)

        self.assertTrue(result)

        # Check that it was deleted
        response = self.quarantine.get_response(response_id)
        self.assertIsNone(response)

        # Try deleting a non-existent response
        result = self.quarantine.delete_response("non-existent")

        self.assertFalse(result)

    def test_clear_quarantine(self):
        """Test clearing the quarantine."""
        # Quarantine two responses
        response_id1 = self.quarantine.quarantine_response(
            tool_name="test-tool-1",
            tool_input={"param": "value1"},
            tool_output="test output 1",
            reason="test reason 1",
        )

        response_id2 = self.quarantine.quarantine_response(
            tool_name="test-tool-2",
            tool_input={"param": "value2"},
            tool_output="test output 2",
            reason="test reason 2",
        )

        # Release one of them
        self.quarantine.release_response(response_id1)

        # Clear only released responses
        cleared = self.quarantine.clear_quarantine(only_released=True)

        self.assertEqual(cleared, 1)

        # Check that only the released response was cleared
        response1 = self.quarantine.get_response(response_id1)
        response2 = self.quarantine.get_response(response_id2)

        self.assertIsNone(response1)
        self.assertIsNotNone(response2)

        # Clear all responses
        cleared = self.quarantine.clear_quarantine()

        self.assertEqual(cleared, 1)

        # Check that all responses were cleared
        response2 = self.quarantine.get_response(response_id2)
        self.assertIsNone(response2)

    def test_file_persistence(self):
        """Test that responses are correctly persisted to the file."""
        # Quarantine a response
        response_id = self.quarantine.quarantine_response(
            tool_name="test-tool",
            tool_input={"param": "value"},
            tool_output="test output",
            reason="test reason",
        )

        # Create a new quarantine instance with the same file
        quarantine2 = ToolResponseQuarantine(self.temp_file.name)

        # Check that the response was loaded
        response = quarantine2.get_response(response_id)

        self.assertIsNotNone(response)
        self.assertEqual(response.tool_name, "test-tool")
        self.assertEqual(response.tool_input, {"param": "value"})
        self.assertEqual(response.tool_output, "test output")
        self.assertEqual(response.reason, "test reason")

        # Release the response from the second instance
        quarantine2.release_response(response_id)

        # Create a third instance to check that the release was persisted
        quarantine3 = ToolResponseQuarantine(self.temp_file.name)

        response = quarantine3.get_response(response_id)
        self.assertTrue(response.released)
        self.assertIsNotNone(response.released_at)


if __name__ == "__main__":
    unittest.main()
