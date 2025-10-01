#!/usr/bin/env python3
"""
Webhook URL Update Script

Updates all VAPI tool webhook URLs to point to a new base URL.
Useful when switching between local development (Cloudflare Tunnel) and production (Railway).

Usage:
    # Update to local Cloudflare Tunnel
    python scripts/update_webhooks.py https://vapi-local-abc.trycloudflare.com

    # Update to production
    python scripts/update_webhooks.py https://journ3y-vapi-skills-service.up.railway.app

    # List current webhook URLs (dry run)
    python scripts/update_webhooks.py --list
"""

import asyncio
import sys
import os
from typing import Dict, Optional
import httpx

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.config import settings


class WebhookUpdater:
    """Updates VAPI tool webhook URLs"""

    def __init__(self):
        self.api_key = settings.VAPI_API_KEY
        if not self.api_key:
            raise ValueError("VAPI_API_KEY not set in environment variables")

        self.base_url = "https://api.vapi.ai"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def list_tools(self) -> Dict[str, Dict]:
        """List all existing tools and their webhook URLs"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/tool",
                headers=self.headers
            )

            if response.status_code == 200:
                tools = response.json()
                tool_map = {}
                for tool in tools:
                    tool_name = tool.get('function', {}).get('name', 'unknown')
                    tool_map[tool_name] = {
                        'id': tool['id'],
                        'webhook_url': tool.get('server', {}).get('url', 'N/A')
                    }
                return tool_map
            else:
                print(f"Error fetching tools: {response.status_code} - {response.text}")
                return {}

    async def update_tool_webhook(self, tool_id: str, tool_name: str, new_base_url: str, endpoint: str) -> bool:
        """Update a single tool's webhook URL"""
        new_webhook_url = f"{new_base_url}{endpoint}"

        async with httpx.AsyncClient() as client:
            # VAPI requires a PATCH to update tool
            response = await client.patch(
                f"{self.base_url}/tool/{tool_id}",
                headers=self.headers,
                json={
                    "server": {
                        "url": new_webhook_url
                    }
                }
            )

            if response.status_code == 200:
                print(f"✓ Updated {tool_name}: {new_webhook_url}")
                return True
            else:
                print(f"✗ Failed to update {tool_name}: {response.status_code} - {response.text}")
                return False

    async def update_all_webhooks(self, new_base_url: str) -> None:
        """Update all known tool webhooks to new base URL"""

        # Known tool endpoints
        tool_endpoints = {
            'authenticate_caller': '/api/v1/vapi/authenticate-by-phone',
            'identify_context': '/api/v1/skills/voice-notes/identify-context',
            'save_note': '/api/v1/skills/voice-notes/save-note'
        }

        print(f"\nUpdating webhooks to base URL: {new_base_url}")
        print("-" * 60)

        # Get existing tools
        existing_tools = await self.list_tools()

        if not existing_tools:
            print("No tools found or error fetching tools")
            return

        # Update each tool
        updated_count = 0
        for tool_name, endpoint in tool_endpoints.items():
            if tool_name in existing_tools:
                tool_id = existing_tools[tool_name]['id']
                success = await self.update_tool_webhook(tool_id, tool_name, new_base_url, endpoint)
                if success:
                    updated_count += 1
            else:
                print(f"⚠ Tool '{tool_name}' not found in VAPI")

        print("-" * 60)
        print(f"Updated {updated_count}/{len(tool_endpoints)} tools")

    async def print_current_webhooks(self) -> None:
        """Print current webhook URLs for all tools"""
        print("\nCurrent VAPI Tool Webhook URLs:")
        print("-" * 60)

        tools = await self.list_tools()

        if not tools:
            print("No tools found")
            return

        for tool_name, info in tools.items():
            print(f"{tool_name:25} → {info['webhook_url']}")
            print(f"  ID: {info['id']}")

        print("-" * 60)
        print(f"Total tools: {len(tools)}")


async def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    updater = WebhookUpdater()

    # Handle --list flag
    if sys.argv[1] == "--list":
        await updater.print_current_webhooks()
        return

    # Get new base URL from argument
    new_base_url = sys.argv[1].rstrip('/')  # Remove trailing slash

    # Validate URL format
    if not new_base_url.startswith('https://'):
        print("Error: Base URL must start with https://")
        sys.exit(1)

    # Show current state first
    await updater.print_current_webhooks()

    # Confirm update
    print(f"\nAbout to update all webhooks to: {new_base_url}")

    # Check for --yes flag
    auto_confirm = '--yes' in sys.argv or '-y' in sys.argv

    if auto_confirm:
        print("Auto-confirming with --yes flag")
        confirm = 'y'
    else:
        confirm = input("Continue? (y/N): ")

    if confirm.lower() != 'y':
        print("Cancelled")
        return

    # Perform update
    await updater.update_all_webhooks(new_base_url)


if __name__ == "__main__":
    asyncio.run(main())
