#!/usr/bin/env python3
"""
Update VAPI assistant with server webhook configuration
"""
import asyncio
import sys
import os
import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.config import settings

async def update_assistant_server():
    """Update Site Progress assistant with server URL"""

    api_key = settings.VAPI_API_KEY
    if not api_key:
        print("Error: VAPI_API_KEY not set")
        return

    base_url = "https://api.vapi.ai"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    server_url = f"{settings.webhook_base_url}/api/v1/vapi/end-of-call-report"

    print(f"\n🔧 Updating Site Progress assistant with server URL:")
    print(f"   {server_url}\n")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get all assistants
        print("📋 Fetching assistants...")
        response = await client.get(f"{base_url}/assistant", headers=headers)

        if response.status_code != 200:
            print(f"❌ Failed to fetch assistants: {response.status_code}")
            return

        assistants = response.json()
        print(f"   Found {len(assistants)} assistants\n")

        # Find assistants that need server webhooks
        assistants_to_update = [
            'JSMB-Jill-site-progress',
            'JSMB-Jill-voice-notes'
        ]

        for assistant_name in assistants_to_update:
            target_assistant = None
            for assistant in assistants:
                if assistant.get('name') == assistant_name:
                    target_assistant = assistant
                    break

            if not target_assistant:
                print(f"❌ Could not find {assistant_name} assistant")
                continue

            assistant_id = target_assistant['id']
            print(f"✅ Found {assistant_name}: {assistant_id}")

            # Update with server configuration
            print(f"🔄 Updating {assistant_name} with server webhook...")

            update_payload = {
                "server": {
                    "url": server_url
                },
                "serverMessages": ["end-of-call-report"]
            }

            update_response = await client.patch(
                f"{base_url}/assistant/{assistant_id}",
                headers=headers,
                json=update_payload
            )

            if update_response.status_code == 200:
                print(f"✅ {assistant_name} updated successfully!\n")
            else:
                print(f"❌ Failed: {update_response.status_code}")
                print(f"   {update_response.text}\n")

        print(f"\n📞 Assistants will now send end-of-call reports to:")
        print(f"   {server_url}")

if __name__ == "__main__":
    asyncio.run(update_assistant_server())
