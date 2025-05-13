#!/usr/bin/env python3
"""
CLI interface for reviewing and managing quarantined tool responses.
"""

import json
import logging
from typing import Optional, List, Dict, Any

from .quarantine import ToolResponseQuarantine, QuarantinedToolResponse

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("quarantine_cli")


async def review_quarantine(quarantine_path: Optional[str] = None, quarantine_id: Optional[str] = None) -> None:
    """
    Review quarantined tool responses and optionally release them.

    Args:
        quarantine_path: Optional path to the quarantine database file
        quarantine_id: Optional ID of a specific quarantined response to review
    """
    # Open the quarantine database
    quarantine = ToolResponseQuarantine(quarantine_path)
    
    # Check if there are any quarantined responses
    responses = quarantine.list_responses(include_released=False)
    if not responses:
        print("\n⚠️ No quarantined tool responses found.")
        return

    print(f"\n🔍 Found {len(responses)} quarantined tool response(s).")
    
    # If a specific quarantine ID was provided, review just that one
    if quarantine_id:
        response = quarantine.get_response(quarantine_id)
        if not response:
            print(f"\n❌ No quarantined response found with ID: {quarantine_id}")
            return
        
        if response.released:
            print(f"\n⚠️ Response with ID {quarantine_id} has already been released.")
            return
            
        review_response(quarantine, response)
    else:
        # Otherwise, show a list and let the user choose
        review_response_list(quarantine, responses)


def review_response_list(quarantine: ToolResponseQuarantine, responses: List[Dict[str, Any]]) -> None:
    """
    Display a list of quarantined responses and let the user choose one to review.
    
    Args:
        quarantine: The quarantine database instance
        responses: List of quarantined responses
    """
    # Display the list of quarantined responses
    print("\n===== QUARANTINED TOOL RESPONSES =====")
    for i, response_data in enumerate(responses):
        # Format the timestamp for better readability
        timestamp = response_data["timestamp"].split("T")[0]
        print(f"{i+1}. [{timestamp}] {response_data['tool_name']} - {response_data['reason'][:50]}...")
    print("=====================================\n")
    
    # Prompt user to select a response to review
    while True:
        try:
            choice = input("Enter the number of the response to review (or 'q' to quit): ")
            if choice.lower() in ('q', 'quit', 'exit'):
                return
                
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(responses):
                response_id = responses[choice_idx]["id"]
                response = quarantine.get_response(response_id)
                if response:
                    review_response(quarantine, response)
                    # After reviewing, show the list again with updated data
                    responses = quarantine.list_responses(include_released=False)
                    if not responses:
                        print("\n✅ No more quarantined responses to review.")
                        return
                    review_response_list(quarantine, responses)
                    return
                else:
                    print("\n❌ Error retrieving response from quarantine.")
            else:
                print(f"\n❌ Invalid choice. Please enter a number between 1 and {len(responses)}.")
        except ValueError:
            print("\n❌ Please enter a valid number.")


def review_response(quarantine: ToolResponseQuarantine, response: QuarantinedToolResponse) -> None:
    """
    Review a specific quarantined response and prompt for release.
    
    Args:
        quarantine: The quarantine database instance
        response: The quarantined response to review
    """
    # Display the full response details
    print("\n===== QUARANTINED RESPONSE DETAILS =====")
    print(f"ID: {response.id}")
    print(f"Tool: {response.tool_name}")
    print(f"Quarantine Reason: {response.reason}")
    print(f"Timestamp: {response.timestamp.isoformat()}")
    print("\nTool Input:")
    print(json.dumps(response.tool_input, indent=2))
    print("\nTool Output:")
    print(f"{response.tool_output}")
    print("=======================================\n")
    
    # Prompt for release
    while True:
        choice = input("Do you want to release this response from quarantine? [y/n]: ").lower()
        if choice in ('y', 'yes'):
            quarantine.release_response(response.id)
            print(f"\n✅ Response {response.id} has been released from quarantine.")
            break
        elif choice in ('n', 'no'):
            print("\n❌ Response remains in quarantine.")
            break
        else:
            print("\n❌ Invalid choice. Please enter 'y' or 'n'.")