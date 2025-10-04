#!/usr/bin/env python3
"""
Update VAPI assistant system prompts from local assistant definitions
"""
import asyncio
import sys
import os
import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.config import settings
from app.assistants.jill_voice_notes import JillVoiceNotesAssistant
from app.assistants.greeter import GreeterAssistant

async def update_assistant_prompts():
    """Update assistant system prompts in VAPI"""

    api_key = settings.VAPI_API_KEY
    if not api_key:
        print("Error: VAPI_API_KEY not set")
        return

    base_url = "https://api.vapi.ai"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Get assistant definitions
    voice_notes = JillVoiceNotesAssistant()
    greeter = GreeterAssistant()

    assistants_to_update = [
        {
            "name": voice_notes.name,
            "system_prompt": voice_notes.get_system_prompt(),
            "first_message": voice_notes.get_first_message()
        },
        {
            "name": greeter.name,
            "system_prompt": greeter.get_system_prompt(),
            "first_message": greeter.get_first_message()
        }
    ]

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get all assistants from VAPI
        print("📋 Fetching assistants from VAPI...")
        response = await client.get(f"{base_url}/assistant", headers=headers)

        if response.status_code != 200:
            print(f"❌ Failed to fetch assistants: {response.status_code}")
            return

        vapi_assistants = response.json()
        print(f"   Found {len(vapi_assistants)} assistants\n")

        # Update each assistant
        for assistant_def in assistants_to_update:
            print(f"🔍 Looking for: {assistant_def['name']}")

            # Find matching assistant
            vapi_assistant = None
            for va in vapi_assistants:
                if va.get('name') == assistant_def['name']:
                    vapi_assistant = va
                    break

            if not vapi_assistant:
                print(f"❌ Could not find {assistant_def['name']}\n")
                continue

            assistant_id = vapi_assistant['id']
            print(f"✅ Found: {assistant_id}")

            # Get current model config to preserve provider settings
            current_model = vapi_assistant.get('model', {})

            # Update payload - preserve existing model config but update messages
            update_payload = {
                "model": {
                    **current_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": assistant_def['system_prompt']
                        }
                    ]
                }
            }

            # Add first message if it exists
            if assistant_def['first_message']:
                update_payload["firstMessage"] = assistant_def['first_message']

            print(f"🔄 Updating system prompt...")

            update_response = await client.patch(
                f"{base_url}/assistant/{assistant_id}",
                headers=headers,
                json=update_payload
            )

            if update_response.status_code == 200:
                print(f"✅ {assistant_def['name']} updated successfully!\n")
            else:
                print(f"❌ Failed: {update_response.status_code}")
                print(f"   {update_response.text}\n")

if __name__ == "__main__":
    asyncio.run(update_assistant_prompts())
