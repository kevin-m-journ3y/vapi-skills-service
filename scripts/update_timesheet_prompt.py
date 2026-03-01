"""
Update Timesheet Assistant Prompt with Site Name Variant Handling

This script updates the Timesheet assistant in VAPI with the new system prompt
that includes site name variant recognition for commonly misheard site names.

Usage:
    python scripts/update_timesheet_prompt.py
    python scripts/update_timesheet_prompt.py --summary "Added half seven time parsing"
"""

import asyncio
import argparse
import os
import sys
import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.assistants.timesheet import TimesheetAssistant
from scripts.record_prompt_change import record_prompt_change

VAPI_API_KEY = os.getenv("VAPI_API_KEY")
ASSISTANT_NAME = "JSMB-Jill-timesheet"


async def main():
    parser = argparse.ArgumentParser(description="Update Timesheet prompt in VAPI")
    parser.add_argument("--summary", default="Timesheet prompt updated", help="Description of what changed")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("UPDATING TIMESHEET PROMPT")
    print("=" * 60)
    print()

    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Find the timesheet assistant
        response = await client.get("https://api.vapi.ai/assistant", headers=headers)
        assistants = response.json()

        assistant_id = None
        for a in assistants:
            if a.get('name') == ASSISTANT_NAME:
                assistant_id = a['id']
                break

        if not assistant_id:
            print(f"ERROR: Could not find {ASSISTANT_NAME}")
            return

        print(f"Found Timesheet Assistant: {assistant_id}")

        # Get new prompt from code
        timesheet = TimesheetAssistant()
        new_prompt = timesheet.get_system_prompt()

        # Update the model config with new prompt
        response = await client.get(f"https://api.vapi.ai/assistant/{assistant_id}", headers=headers)
        current = response.json()

        model_config = current.get('model', {})
        model_config['messages'] = [{"role": "system", "content": new_prompt}]

        update_payload = {"model": model_config}

        response = await client.patch(
            f"https://api.vapi.ai/assistant/{assistant_id}",
            headers=headers,
            json=update_payload
        )

        if response.status_code == 200:
            print("✓ Timesheet prompt updated successfully")

            # Record the change in the learning loop
            await record_prompt_change(
                assistant_key=ASSISTANT_NAME,
                assistant_id=assistant_id,
                change_summary=args.summary,
                change_category="prompt",
                prompt_content=new_prompt,
            )
        else:
            print(f"✗ Failed: {response.status_code}")
            print(response.text)


if __name__ == "__main__":
    asyncio.run(main())
