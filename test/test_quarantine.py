"""
Tests for the quarantine system.
"""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from contextprotector.quarantine import QuarantinedToolResponse, ToolResponseQuarantine


class TestQuarantinedToolResponse(unittest.TestCase):
    """Tests for the QuarantinedToolResponse class."""

    def test_init(self) -> None:
        """Test initialization of a quarantined tool response."""
        response = QuarantinedToolResponse(
            id="test-id",
            tool_name="test-tool",
            tool_input={"param": "value"},
            tool_output="test output",
            reason="test reason",
        )

        assert response.id == "test-id"
        assert response.tool_name == "test-tool"
        assert response.tool_input == {"param": "value"}
        assert response.tool_output == "test output"
        assert response.reason == "test reason"
        assert not response.released
        assert response.released_at is None

    def test_release(self) -> None:
        """Test releasing a quarantined tool response."""
        response = QuarantinedToolResponse(
            id="test-id",
            tool_name="test-tool",
            tool_input={"param": "value"},
            tool_output="test output",
            reason="test reason",
        )

        assert not response.released
        assert response.released_at is None

        response.release()

        assert response.released
        assert response.released_at is not None

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        now = datetime.now(timezone.utc)
        response = QuarantinedToolResponse(
            id="test-id",
            tool_name="test-tool",
            tool_input={"param": "value"},
            tool_output="test output",
            reason="test reason",
            timestamp=now,
        )

        data = response.to_dict()

        assert data["id"] == "test-id"
        assert data["tool_name"] == "test-tool"
        assert data["tool_input"] == {"param": "value"}
        assert data["tool_output"] == "test output"
        assert data["reason"] == "test reason"
        assert data["timestamp"] == now.isoformat()
        assert not data["released"]
        assert data["released_at"] is None

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        now = datetime.now(timezone.utc)
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

        assert response.id == "test-id"
        assert response.tool_name == "test-tool"
        assert response.tool_input == {"param": "value"}
        assert response.tool_output == "test output"
        assert response.reason == "test reason"
        assert response.timestamp.isoformat() == now.isoformat()
        assert response.released
        assert response.released_at.isoformat() == released_at.isoformat()


class TestToolCallQuarantine(unittest.TestCase):
    """Tests for the ToolCallQuarantine class."""

    def setUp(self) -> None:
        """Set up a temporary file for testing."""
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.temp_file.close()
        self.quarantine = ToolResponseQuarantine(self.temp_file.name)

    def tearDown(self) -> None:
        """Clean up the temporary file."""
        if Path(self.temp_file.name).exists():
            Path(self.temp_file.name).unlink()

    def test_quarantine_response(self) -> None:
        """Test quarantining a tool response."""
        response_id = self.quarantine.quarantine_response(
            tool_name="test-tool",
            tool_input={"param": "value"},
            tool_output="test output",
            reason="test reason",
        )

        assert response_id is not None

        # Check that the response was saved to the database
        quarantine = ToolResponseQuarantine(self.temp_file.name)
        response = quarantine.get_response(response_id)

        assert response is not None
        assert response.tool_name == "test-tool"
        assert response.tool_input == {"param": "value"}
        assert response.tool_output == "test output"
        assert response.reason == "test reason"
        assert not response.released

    def test_release_response(self) -> None:
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

        assert result

        # Check that it was marked as released
        response = self.quarantine.get_response(response_id)
        assert response.released
        assert response.released_at is not None

        # Try releasing it again
        result = self.quarantine.release_response(response_id)

        assert result  # Should still return True

        # Try releasing a non-existent response
        result = self.quarantine.release_response("non-existent")

        assert not result

    def test_list_responses(self) -> None:
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
        responses = self.quarantine.list_responses()

        assert len(responses) == 1
        assert responses[0]["id"] == response_id2

        # List responses with released
        responses = self.quarantine.list_responses_with_released()

        assert len(responses) == 2
        assert any(r["id"] == response_id1 for r in responses)
        assert any(r["id"] == response_id2 for r in responses)

    def test_get_response_pairs(self) -> None:
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
        assert len(pairs) == 1
        request, response = pairs[0]

        assert request["tool_name"] == "test-tool-2"
        assert request["input"] == {"param": "value2"}
        assert response == "test output 2"

    def test_delete_response(self) -> None:
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

        assert result

        # Check that it was deleted
        response = self.quarantine.get_response(response_id)
        assert response is None

        # Try deleting a non-existent response
        result = self.quarantine.delete_response("non-existent")

        assert not result

    def test_purge_tidy_quarantine(self) -> None:
        """Test purging and tidying the quarantine."""
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
        cleared = self.quarantine.tidy_quarantine()

        assert cleared == 1

        # Check that only the released response was cleared
        response1 = self.quarantine.get_response(response_id1)
        response2 = self.quarantine.get_response(response_id2)

        assert response1 is None
        assert response2 is not None

        # Clear all responses
        cleared = self.quarantine.purge_quarantine()

        assert cleared == 1

        # Check that all responses were cleared
        response2 = self.quarantine.get_response(response_id2)
        assert response2 is None

    def test_file_persistence(self) -> None:
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

        assert response is not None
        assert response.tool_name == "test-tool"
        assert response.tool_input == {"param": "value"}
        assert response.tool_output == "test output"
        assert response.reason == "test reason"

        # Release the response from the second instance
        quarantine2.release_response(response_id)

        # Create a third instance to check that the release was persisted
        quarantine3 = ToolResponseQuarantine(self.temp_file.name)

        response = quarantine3.get_response(response_id)
        assert response.released
        assert response.released_at is not None


if __name__ == "__main__":
    unittest.main()
