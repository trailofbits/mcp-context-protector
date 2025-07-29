#!/usr/bin/env python3
"""
Quarantine system for tool responses that have been flagged by guardrails.
Provides storage and retrieval of quarantined tool responses.
"""

import datetime
import json
import pathlib
import threading
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Tuple


@dataclass
class QuarantinedToolResponse:
    """
    Class representing a quarantined tool response.

    Attributes:
    ----------
        id: Unique identifier for the quarantined response
        tool_name: Name of the tool that was called
        tool_input: Input parameters to the tool
        tool_output: Output returned by the tool
        reason: Reason the response was quarantined
        timestamp: When the response was quarantined
        released: Whether the response has been released from quarantine
        released_at: When the response was released (if applicable)

    """

    id: str
    tool_name: str
    tool_input: dict[str, Any]
    tool_output: Any
    reason: str
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.now)
    released: bool = False
    released_at: datetime.datetime | None = None

    def release(self) -> None:
        """Mark this quarantined response as released."""
        self.released = True
        self.released_at = datetime.datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary representation for storage."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        if self.released_at:
            data["released_at"] = self.released_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QuarantinedToolResponse":
        """Create a QuarantinedToolResponse from a dictionary."""
        if "timestamp" in data and isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.datetime.fromisoformat(data["timestamp"])
        if "released_at" in data and isinstance(data["released_at"], str) and data["released_at"]:
            data["released_at"] = datetime.datetime.fromisoformat(data["released_at"])
        return cls(**data)


class ToolResponseQuarantine:
    """
    Database for storing quarantined tool responses.

    This database stores tool responses that have been flagged by guardrails.
    It provides thread-safe access to the quarantine file to prevent race conditions.
    """

    _file_lock = threading.RLock()  # Class-level lock for file operations

    def __init__(self, db_path: str | None = None):
        """
        Initialize the quarantine database.

        Args:
        ---
            db_path: Path to the database file. If None, uses the default path.

        """
        self.db_path = db_path or self.get_default_db_path()
        self.quarantined_responses = {}  # dict[str, QuarantinedToolResponse]
        self._load()

    @staticmethod
    def get_default_db_path() -> str:
        """
        Get the default quarantine database path (~/.context-protector/quarantine.json).

        Returns:
        -------
            The default database path as a string

        """
        home_dir = pathlib.Path.home()
        data_dir = home_dir / ".context-protector"

        data_dir.mkdir(exist_ok=True)

        return str(data_dir / "quarantine.json")

    def _load(self) -> None:
        """Load quarantined responses from the database file."""
        with ToolResponseQuarantine._file_lock:
            try:
                if pathlib.Path(self.db_path).exists():
                    with pathlib.Path(self.db_path).open("r") as f:
                        data = json.load(f)
                        for response_data in data.get("responses", []):
                            response = QuarantinedToolResponse.from_dict(response_data)
                            self.quarantined_responses[response.id] = response
            except (json.JSONDecodeError, FileNotFoundError, ValueError):
                # If the file doesn't exist or is invalid, start with an empty database
                self.quarantined_responses = {}

    def _save(self) -> None:
        """Save quarantined responses to the database file."""
        with ToolResponseQuarantine._file_lock:
            data = {
                "responses": [
                    response.to_dict() for response in self.quarantined_responses.values()
                ]
            }

            pathlib.Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

            # Write to a temporary file first, then rename
            temp_path = f"{self.db_path}.tmp"
            with pathlib.Path(temp_path).open("w") as f:
                json.dump(data, f, indent=2)

            # Atomically replace the old file with the new one
            pathlib.Path(temp_path).replace(self.db_path)

    def quarantine_response(
        self, tool_name: str, tool_input: dict[str, Any], tool_output: Any, reason: str
    ) -> str:
        """
        Add a tool response to the quarantine.

        Args:
        ----
        ____
            tool_name: The name of the tool that was called
            tool_input: The input parameters to the tool
            tool_output: The output returned by the tool
            reason: The reason the response was quarantined

        Returns:
        -------
            The unique ID of the quarantined response

        """
        # Reload the database first to avoid overwriting other changes
        self._load()

        response_id = str(uuid.uuid4())

        response = QuarantinedToolResponse(
            id=response_id,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            reason=reason,
        )

        self.quarantined_responses[response_id] = response

        self._save()

        return response_id

    def get_response(self, response_id: str) -> QuarantinedToolResponse | None:
        """
        Get a quarantined response by ID.

        Args:
        ----
            response_id: The ID of the quarantined response

        Returns:
        -------
            The quarantined response, or None if not found

        """
        return self.quarantined_responses.get(response_id)

    def release_response(self, response_id: str) -> bool:
        """
        Release a quarantined response.

        Args:
        ----
            response_id: The ID of the quarantined response

        Returns:
        -------
            True if the response was released, False if it wasn't found

        """
        # Reload the database first to avoid overwriting other changes
        self._load()

        response = self.quarantined_responses.get(response_id)
        if response:
            if not response.released:  # Only release if not already released
                response.release()
                self._save()
            return True

        return False

    def list_responses(self, include_released: bool = False) -> list[dict[str, Any]]:
        """
        List all quarantined responses.

        Args:
        ----
            include_released: Whether to include responses that have been released

        Returns:
        -------
            A list of quarantined responses

        """
        responses = self.quarantined_responses.values()
        if not include_released:
            responses = [r for r in responses if not r.released]

        return [
            {
                "id": response.id,
                "tool_name": response.tool_name,
                "reason": response.reason,
                "timestamp": response.timestamp.isoformat(),
                "released": response.released,
            }
            for response in responses
        ]

    def get_response_pairs(self) -> list[tuple[dict[str, Any], Any]]:
        """
        Get all request-response pairs from quarantine.

        Returns:
        -------
            A list of (request, response) tuples

        """
        return [
            (
                {
                    "tool_name": response.tool_name,
                    "input": response.tool_input,
                },
                response.tool_output,
            )
            for response in self.quarantined_responses.values()
            if not response.released  # Only include non-released responses
        ]

    def delete_response(self, response_id: str) -> bool:
        """
        Delete a quarantined response.

        Args:
        ----
            response_id: The ID of the quarantined response

        Returns:
        -------
            True if the response was deleted, False if it wasn't found

        """
        # Reload the database first to avoid overwriting other changes
        self._load()

        if response_id in self.quarantined_responses:
            del self.quarantined_responses[response_id]
            self._save()
            return True

        return False

    def clear_quarantine(self, only_released: bool = False) -> int:
        """
        Clear the quarantine, optionally only removing released responses.

        Args:
        ----
            only_released: If True, only clear released responses

        Returns:
        -------
            The number of responses cleared

        """
        # Reload the database first to avoid overwriting other changes
        self._load()

        original_count = len(self.quarantined_responses)

        if only_released:
            self.quarantined_responses = {
                k: v for k, v in self.quarantined_responses.items() if not v.released
            }
        else:
            self.quarantined_responses = {}

        removed_count = original_count - len(self.quarantined_responses)

        if removed_count > 0:
            self._save()

        return removed_count
