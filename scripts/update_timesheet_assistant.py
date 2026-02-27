"""
Script to update the existing Timesheet assistant in VAPI

This script:
1. Creates any missing tools (e.g., get_signon_data) - reuses existing ones
2. Finds the existing timesheet assistant in VAPI
3. PATCHes it with updated prompt, tools, and first message
"""

import asyncio
import os
import sys
from dotenv import load_dotenv
import logging

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

from app.skills.timesheet import TimesheetSkill
from app.skills.authentication import AuthenticationSkill
from app.assistants.timesheet import TimesheetAssistant


async def update_timesheet_in_vapi():
    """Update the existing timesheet assistant in VAPI"""

    VAPI_API_KEY = os.getenv("VAPI_API_KEY")
    if not VAPI_API_KEY:
        print("VAPI_API_KEY not set")
        return False

    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }

    print("=" * 70)
    print("UPDATING TIMESHEET ASSISTANT IN VAPI")
    print("=" * 70)
    print()

    # Step 1: Ensure all tools exist (creates missing ones, reuses existing)
    print("1. Creating/verifying timesheet tools...")
    print("-" * 70)

    timesheet_skill = TimesheetSkill()
    tool_ids = await timesheet_skill.create_tools()
    print(f"   Timesheet tools ({len(tool_ids)}):")
    for name, tid in tool_ids.items():
        print(f"   - {name}: {tid}")

    auth_skill = AuthenticationSkill()
    auth_tool_ids = await auth_skill.create_tools()
    print(f"   Auth tools ({len(auth_tool_ids)}):")
    for name, tid in auth_tool_ids.items():
        print(f"   - {name}: {tid}")

    all_tool_ids = {**auth_tool_ids, **tool_ids}
    print()

    # Step 2: Find existing timesheet assistant
    print("2. Finding existing timesheet assistant in VAPI...")
    print("-" * 70)

    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.vapi.ai/assistant",
            headers=headers
        )

        if response.status_code != 200:
            print(f"   Failed to list assistants: {response.status_code}")
            return False

        assistants = response.json()
        timesheet_assistant = None
        for a in assistants:
            name = a.get('name', '')
            if 'timesheet' in name.lower():
                timesheet_assistant = a
                print(f"   Found: {name} (ID: {a['id']})")
                break

        if not timesheet_assistant:
            print("   No existing timesheet assistant found!")
            print("   Available assistants:")
            for a in assistants:
                print(f"   - {a.get('name', 'unnamed')}: {a['id']}")
            return False

        assistant_id = timesheet_assistant['id']

        # Show current tool count
        current_tools = timesheet_assistant.get('model', {}).get('toolIds', [])
        print(f"   Current tool count: {len(current_tools)}")
        print()

        # Step 3: Build the updated config
        print("3. Building updated assistant config...")
        print("-" * 70)

        assistant_def = TimesheetAssistant()

        # Map required tool names to VAPI tool IDs
        required_tools = assistant_def.get_required_tool_names()
        new_tool_ids = []
        for tool_name in required_tools:
            if tool_name in all_tool_ids:
                new_tool_ids.append(all_tool_ids[tool_name])
                print(f"   + {tool_name}: {all_tool_ids[tool_name]}")
            else:
                print(f"   ! MISSING: {tool_name}")

        print(f"   New tool count: {len(new_tool_ids)}")
        print()

        # Step 4: PATCH the assistant
        print("4. Updating assistant in VAPI...")
        print("-" * 70)

        model_config = assistant_def.get_model_config()
        model_config["messages"] = [
            {
                "role": "system",
                "content": assistant_def.get_system_prompt()
            }
        ]
        model_config["toolIds"] = new_tool_ids

        patch_payload = {
            "model": model_config,
            "firstMessage": assistant_def.get_first_message(),
            "firstMessageMode": "assistant-speaks-first",
            "transcriber": assistant_def.get_transcriber_config(),
        }

        response = await client.patch(
            f"https://api.vapi.ai/assistant/{assistant_id}",
            headers=headers,
            json=patch_payload
        )

        if response.status_code == 200:
            print(f"   Updated assistant {assistant_id}")
            updated = response.json()
            updated_tools = updated.get('model', {}).get('toolIds', [])
            print(f"   Tool count after update: {len(updated_tools)}")
            print(f"   First message: {updated.get('firstMessage', 'N/A')[:80]}...")
        else:
            print(f"   FAILED: {response.status_code}")
            print(f"   {response.text[:500]}")
            return False

    print()
    print("=" * 70)
    print("UPDATE COMPLETE")
    print("=" * 70)
    print()
    print(f"Assistant ID: {assistant_id}")
    print(f"Tools: {len(new_tool_ids)} (was {len(current_tools)})")
    print()
    print("Changes applied:")
    print("- Updated system prompt (added sign-on awareness)")
    print("- Added get_signon_data tool")
    print("- Updated first message")
    print()

    return True


if __name__ == "__main__":
    success = asyncio.run(update_timesheet_in_vapi())
    if not success:
        exit(1)
