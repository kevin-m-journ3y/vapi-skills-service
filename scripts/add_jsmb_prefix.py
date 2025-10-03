#!/usr/bin/env python3
"""
Add JSMB-Jill prefix to tool names for easy identification in VAPI
"""
import asyncio
import sys
import os
import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.config import settings

async def rename_tools():
    """Rename tools to add JSMB-Jill prefix"""

    api_key = settings.VAPI_API_KEY
    if not api_key:
        print("Error: VAPI_API_KEY not set")
        return

    base_url = "https://api.vapi.ai"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Tools to rename
    tool_renames = {
        'authenticate_caller': 'JSMB-Jill-authenticate_caller',
        'identify_context': 'JSMB-Jill-identify_context',
        'save_note': 'JSMB-Jill-save_note',
        'identify_site_for_update': 'JSMB-Jill-identify_site_for_update',
        'save_site_progress_update': 'JSMB-Jill-save_site_progress_update'
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get all tools
        print("📋 Fetching tools...")
        response = await client.get(f"{base_url}/tool", headers=headers)

        if response.status_code != 200:
            print(f"❌ Failed to fetch tools: {response.status_code}")
            return

        tools = response.json()
        print(f"   Found {len(tools)} tools\n")

        # Rename each tool
        for tool in tools:
            current_name = tool.get('function', {}).get('name')
            tool_id = tool.get('id')

            if current_name in tool_renames:
                new_name = tool_renames[current_name]

                print(f"🔄 Renaming: {current_name} → {new_name}")

                # Update the function name
                tool['function']['name'] = new_name

                # Create clean payload
                update_payload = {
                    "function": tool['function'],
                    "server": tool.get('server', {}),
                    "async": tool.get('async', False),
                    "messages": tool.get('messages', [])
                }

                # Update the tool
                update_response = await client.patch(
                    f"{base_url}/tool/{tool_id}",
                    headers=headers,
                    json=update_payload
                )

                if update_response.status_code == 200:
                    print(f"   ✅ Updated successfully\n")
                else:
                    print(f"   ❌ Failed: {update_response.status_code} - {update_response.text}\n")

        print("✨ Done!")

if __name__ == "__main__":
    asyncio.run(rename_tools())
