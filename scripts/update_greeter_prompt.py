"""
Update Greeter Assistant Prompt with Phonetic Variant Handling

This script updates the Greeter assistant in VAPI with the new system prompt
that includes phonetic variant recognition for commonly misheard words.

Usage:
    python scripts/update_greeter_prompt.py
    python scripts/update_greeter_prompt.py --summary "Added new phonetic variant for timesheet"
"""

import asyncio
import argparse
import os
import sys
import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.assistants.greeter import GreeterAssistant
from scripts.record_prompt_change import record_prompt_change

VAPI_API_KEY = os.getenv("VAPI_API_KEY")
ASSISTANT_NAME = "JSMB-Jill-authenticate-and-greet"


async def main():
    parser = argparse.ArgumentParser(description="Update Greeter prompt in VAPI")
    parser.add_argument("--summary", default="Greeter prompt updated", help="Description of what changed")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("UPDATING GREETER PROMPT")
    print("=" * 60)
    print()

    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Find the greeter assistant
        response = await client.get("https://api.vapi.ai/assistant", headers=headers)
        assistants = response.json()

        greeter_id = None
        for a in assistants:
            if a.get('name') == ASSISTANT_NAME:
                greeter_id = a['id']
                break

        if not greeter_id:
            print(f"ERROR: Could not find {ASSISTANT_NAME}")
            return

        print(f"Found Greeter: {greeter_id}")

        # Get new prompt from code
        greeter = GreeterAssistant()
        new_prompt = greeter.get_system_prompt()

        # Update the model config with new prompt
        response = await client.get(f"https://api.vapi.ai/assistant/{greeter_id}", headers=headers)
        current = response.json()

        model_config = current.get('model', {})
        model_config['messages'] = [{"role": "system", "content": new_prompt}]

        update_payload = {"model": model_config}

        response = await client.patch(
            f"https://api.vapi.ai/assistant/{greeter_id}",
            headers=headers,
            json=update_payload
        )

        if response.status_code == 200:
            print("✓ Greeter prompt updated successfully")

            # Record the change in the learning loop
            await record_prompt_change(
                assistant_key=ASSISTANT_NAME,
                assistant_id=greeter_id,
                change_summary=args.summary,
                change_category="prompt",
                prompt_content=new_prompt,
            )
        else:
            print(f"✗ Failed: {response.status_code}")
            print(response.text)


if __name__ == "__main__":
    asyncio.run(main())
