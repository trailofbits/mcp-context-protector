"""CLI interface for reviewing and managing quarantined tool responses."""

import datetime
import json
import logging
from typing import Any

from .cli_utils import confirm_prompt, truncate_text
from .mcp_wrapper import make_ansi_escape_codes_visible
from .quarantine import QuarantinedToolResponse, ToolResponseQuarantine, _utc_to_local_display

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quarantine_cli")

# Display constants
MAX_REASON_PREVIEW_LENGTH = 50
TIMESTAMP_DATE_LENGTH = 10  # "YYYY-MM-DD" portion


async def review_quarantine(
    quarantine_path: str | None = None, quarantine_id: str | None = None
) -> None:
    """Review quarantined tool responses and optionally release them.

    Args:
    ----
        quarantine_path: Optional path to the quarantine database file
        quarantine_id: Optional ID of a specific quarantined response to review

    """
    quarantine = ToolResponseQuarantine(quarantine_path)

    responses = quarantine.list_responses()
    if not responses:
        print("\nNo quarantined tool responses found.")
        return

    print(f"\nFound {len(responses)} quarantined tool response(s).")

    # If a specific quarantine ID was provided, review just that one
    if quarantine_id:
        response = quarantine.get_response(quarantine_id)
        if not response:
            print(f"\nNo quarantined response found with ID: {quarantine_id}")
            return

        if response.released:
            print(f"\nResponse with ID {quarantine_id} has already been released.")
            return

        review_response(quarantine, response)
    else:
        # Otherwise, show a list and let the user choose
        review_response_list(quarantine, responses)


def review_response_list(
    quarantine: ToolResponseQuarantine, responses: list[dict[str, Any]]
) -> None:
    """Display a list of quarantined responses and let the user choose one to review.

    Args:
    ----
        quarantine: The quarantine database instance
        responses: list of quarantined responses

    """
    print("\n===== QUARANTINED TOOL RESPONSES =====")
    for i, response_data in enumerate(responses):
        # Parse ISO timestamp and convert to local display
        utc_timestamp = response_data["timestamp"]
        if isinstance(utc_timestamp, str):
            utc_dt = datetime.datetime.fromisoformat(utc_timestamp.replace("Z", "+00:00"))
            local_display = _utc_to_local_display(utc_dt)
            timestamp = local_display.split()[0]  # Just the date part for list view
        else:
            timestamp = str(utc_timestamp)[:TIMESTAMP_DATE_LENGTH]  # Fallback
        reason_preview = truncate_text(response_data["reason"], MAX_REASON_PREVIEW_LENGTH)
        print(f"{i + 1}. [{timestamp}] {response_data['tool_name']} - {reason_preview}")
    print("========================================\n")

    # Prompt user to select a response to review
    while True:
        try:
            choice = input("Enter the number of the response to review (or 'q' to quit): ")
            if choice.lower() in ("q", "quit", "exit"):
                return

            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(responses):
                response_id = responses[choice_idx]["id"]
                response = quarantine.get_response(response_id)
                if response:
                    review_response(quarantine, response)
                    # After reviewing, show the list again with updated data
                    responses = quarantine.list_responses()
                    if not responses:
                        print("\nNo more quarantined responses to review.")
                        return
                    review_response_list(quarantine, responses)
                    return
                print("\nError retrieving response from quarantine.")
            else:
                print(f"\nInvalid choice. Please enter a number between 1 and {len(responses)}.")
        except ValueError:
            print("\nPlease enter a valid number.")


def review_response(quarantine: ToolResponseQuarantine, response: QuarantinedToolResponse) -> None:
    """Review a specific quarantined response and prompt for release.

    Args:
    ----
        quarantine: The quarantine database instance
        response: The quarantined response to review

    """
    print("\n===== QUARANTINED RESPONSE DETAILS =====")
    print(f"ID: {response.id}")
    print(f"Tool: {response.tool_name}")
    print(f"Quarantine Reason: {response.reason}")
    print(f"Timestamp: {response.get_local_timestamp_display()}")
    print("\nTool Input:")
    print(json.dumps(response.tool_input, indent=2))
    print("\nTool Output:")
    print(f"{make_ansi_escape_codes_visible(str(response.tool_output))}")
    print("=======================================\n")

    if confirm_prompt("Do you want to release this response from quarantine?"):
        quarantine.release_response(response.id)
        print(f"\nResponse {response.id} has been released from quarantine.")
    else:
        print("\nResponse remains in quarantine.")
