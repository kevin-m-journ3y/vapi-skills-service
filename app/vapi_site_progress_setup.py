# app/vapi_site_progress_setup.py
import httpx
import json
import logging
from typing import Dict, Any, Optional
import os

logger = logging.getLogger(__name__)

class VAPISiteProgressManager:
    def __init__(self):
        self.api_key = os.getenv('VAPI_API_KEY')
        self.base_url = "https://api.vapi.ai"
        self.webhook_base_url = os.getenv('WEBHOOK_BASE_URL')

        if not self.api_key:
            raise ValueError("VAPI_API_KEY environment variable is required")
        if not self.webhook_base_url:
            raise ValueError("WEBHOOK_BASE_URL environment variable is required")

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def create_identify_site_tool(self) -> str:
        """Create the identify_site_for_update tool and return its ID"""

        tool_data = {
            "type": "function",
            "function": {
                "name": "identify_site_for_update",
                "description": "Gets the list of available sites for this user, or identifies which construction site the user wants to update based on their description. Call without site_description to get the list, then call again with site_description after user responds.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "site_description": {
                            "type": "string",
                            "description": "The site name or description from the user (e.g., 'Ocean White House', 'the ocean project'). Leave empty to get the list of available sites."
                        }
                    },
                    "required": []
                }
            },
            "server": {
                "url": f"{self.webhook_base_url}/site-updates/identify-site"
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/tool",
                headers=self.headers,
                json=tool_data
            )

            if response.status_code == 201:
                tool = response.json()
                logger.info(f"Created identify_site_for_update tool: {tool['id']}")
                return tool['id']
            else:
                logger.error(f"Failed to create identify_site_for_update tool: {response.status_code} - {response.text}")
                raise Exception(f"Tool creation failed: {response.text}")

    async def create_save_site_progress_tool(self) -> str:
        """Create the save_site_progress_update tool and return its ID"""

        tool_data = {
            "type": "function",
            "function": {
                "name": "save_site_progress_update",
                "description": "Saves a daily site progress update with AI-extracted intelligence from raw voice notes",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "site_id": {
                            "type": "string",
                            "description": "The UUID of the construction site"
                        },
                        "raw_notes": {
                            "type": "string",
                            "description": "The complete raw voice notes from the user describing site progress, deliveries, issues, and updates"
                        }
                    },
                    "required": ["site_id", "raw_notes"]
                }
            },
            "server": {
                "url": f"{self.webhook_base_url}/site-updates/save-update"
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/tool",
                headers=self.headers,
                json=tool_data
            )

            if response.status_code == 201:
                tool = response.json()
                logger.info(f"Created save_site_progress_update tool: {tool['id']}")
                return tool['id']
            else:
                logger.error(f"Failed to create save_site_progress_update tool: {response.status_code} - {response.text}")
                raise Exception(f"Tool creation failed: {response.text}")

    async def get_existing_tools(self) -> Dict[str, str]:
        """Get existing tools by name to avoid duplicates"""

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/tool",
                headers=self.headers
            )

            if response.status_code == 200:
                tools = response.json()
                tool_map = {}
                for tool in tools:
                    if tool.get('function', {}).get('name'):
                        tool_map[tool['function']['name']] = tool['id']
                return tool_map
            else:
                logger.warning(f"Failed to get existing tools: {response.status_code}")
                return {}

    async def setup_site_progress_tools(self) -> Dict[str, str]:
        """Set up all site progress tools and return their IDs"""

        # Check for existing tools first
        existing_tools = await self.get_existing_tools()
        tool_ids = {}

        # Create or get identify_site_for_update tool
        if 'identify_site_for_update' in existing_tools:
            tool_ids['identify_site_for_update'] = existing_tools['identify_site_for_update']
            logger.info(f"Using existing identify_site_for_update tool: {tool_ids['identify_site_for_update']}")
        else:
            tool_ids['identify_site_for_update'] = await self.create_identify_site_tool()

        # Create or get save_site_progress_update tool
        if 'save_site_progress_update' in existing_tools:
            tool_ids['save_site_progress_update'] = existing_tools['save_site_progress_update']
            logger.info(f"Using existing save_site_progress_update tool: {tool_ids['save_site_progress_update']}")
        else:
            tool_ids['save_site_progress_update'] = await self.create_save_site_progress_tool()

        logger.info(f"Site progress tools ready: {tool_ids}")
        return tool_ids

    async def create_site_progress_assistant(self, tool_ids: Dict[str, str]) -> str:
        """Create the Site Progress Assistant"""
        logger.info("Creating Site Progress Assistant...")

        assistant_config = {
            "name": "JSMB-Jill-site-progress",
            "model": {
                "provider": "openai",
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "system",
                        "content": """You are Jill, a professional site progress assistant for construction companies.

Your job is to help site managers quickly log daily site progress updates through natural conversation.

SITE IDENTIFICATION PROCESS:
1. First message: "Hi! Ready to log your site progress for today. Which site are you updating?"
2. When they respond, call identify_site_for_update with their site_description
3. If they say they don't know or ask which sites they can update:
   - Call identify_site_for_update WITHOUT site_description (empty string)
   - The tool will return a sites_list array
   - Present the sites naturally: "You can update: [list site names]. Which one?"
4. Once site_identified is true from the tool, proceed to collect updates

COLLECTING UPDATES:
After site is identified, collect information naturally:
- Ask: "What updates do you have for [Site Name] today?"
- Let them speak freely about deliveries, issues, progress
- Listen for ALL details they mention
- When they finish, call save_site_progress_update with site_id and raw_notes containing everything they said

CONVERSATION STYLE:
- Warm, efficient, professional
- Natural - not like a form
- Don't interrupt their flow
- Confirm: "Got it! Your update for [Site Name] has been recorded."

CRITICAL:
- The user's authentication context (tenant/phone) is automatically available via the call_id
- Always get site first before collecting updates
- Capture everything in raw_notes - AI will extract structure later
- If site not found, offer the list of available sites

Remember: Fast capture of important site information for busy professionals."""
                    }
                ],
                "toolIds": [
                    tool_ids["identify_site_for_update"],
                    tool_ids["save_site_progress_update"]
                ]
            },
            "voice": {
                "model": "eleven_turbo_v2_5",
                "voiceId": "MiueK1FXuZTCItgbQwPu",
                "provider": "11labs",
                "stability": 0.5,
                "similarityBoost": 0.75
            },
            "firstMessage": "Hi! Ready to log your site progress for today. Which site are you updating?",
            "firstMessageMode": "assistant-speaks-first"
        }

        logger.info(f"Creating Site Progress Assistant with payload: {json.dumps(assistant_config, indent=2)}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/assistant",
                headers=self.headers,
                json=assistant_config
            )

            logger.info(f"Site Progress Assistant creation response: {response.status_code}")
            logger.info(f"Site Progress Assistant creation response body: {response.text}")

            response.raise_for_status()
            result = response.json()
            return result["id"]

    async def update_squad_with_site_progress(
        self,
        squad_id: str,
        auth_agent_id: str,
        voice_notes_agent_id: str,
        site_progress_agent_id: str
    ) -> str:
        """Update existing squad to include Site Progress Assistant"""
        logger.info("Updating squad with Site Progress Assistant...")

        squad_config = {
            "name": "JSMB-Jill-multi-skill-squad",
            "members": [
                {
                    "assistant": auth_agent_id,
                    "assistantDestinations": [
                        {
                            "type": "assistant",
                            "assistantName": "JSMB-Jill-voice-notes",
                            "message": "Perfect! Connecting you to voice notes..."
                        },
                        {
                            "type": "assistant",
                            "assistantName": "JSMB-Jill-site-progress",
                            "message": "Great! Let me help you log that site progress update..."
                        }
                    ]
                },
                {
                    "assistant": voice_notes_agent_id
                },
                {
                    "assistant": site_progress_agent_id
                }
            ]
        }

        logger.info(f"Updating squad {squad_id} with config: {json.dumps(squad_config, indent=2)}")

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self.base_url}/squad/{squad_id}",
                headers=self.headers,
                json=squad_config
            )

            logger.info(f"Squad update response: {response.status_code}")
            logger.info(f"Squad update response body: {response.text}")

            response.raise_for_status()
            result = response.json()
            return result["id"]

    async def setup_complete_site_progress_system(
        self,
        existing_squad_id: Optional[str] = None,
        existing_auth_agent_id: Optional[str] = None,
        existing_voice_notes_agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Set up the complete site progress system"""
        try:
            # Create tools
            tool_ids = await self.setup_site_progress_tools()

            # Create Site Progress Assistant
            site_progress_agent_id = await self.create_site_progress_assistant(tool_ids)

            result = {
                "success": True,
                "site_progress_agent_id": site_progress_agent_id,
                "tool_ids": tool_ids,
                "message": "Site Progress system setup complete!"
            }

            # Update squad if IDs provided
            if existing_squad_id and existing_auth_agent_id and existing_voice_notes_agent_id:
                squad_id = await self.update_squad_with_site_progress(
                    existing_squad_id,
                    existing_auth_agent_id,
                    existing_voice_notes_agent_id,
                    site_progress_agent_id
                )
                result["squad_id"] = squad_id
                result["message"] = "Site Progress system setup complete and added to squad!"

            return result

        except Exception as e:
            logger.error(f"Error setting up site progress system: {e}")
            raise


def add_site_progress_management_endpoints(app):
    """Add VAPI site progress management endpoints to FastAPI app"""

    @app.post("/api/v1/vapi/setup-site-progress")
    async def setup_site_progress(request: dict = None):
        """Setup the Site Progress VAPI system"""
        try:
            manager = VAPISiteProgressManager()

            # Allow optional squad update
            kwargs = {}
            if request:
                if "squad_id" in request:
                    kwargs["existing_squad_id"] = request["squad_id"]
                if "auth_agent_id" in request:
                    kwargs["existing_auth_agent_id"] = request["auth_agent_id"]
                if "voice_notes_agent_id" in request:
                    kwargs["existing_voice_notes_agent_id"] = request["voice_notes_agent_id"]

            result = await manager.setup_complete_site_progress_system(**kwargs)
            return result
        except Exception as e:
            logger.error(f"Setup failed: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/v1/vapi/site-progress-status")
    async def get_site_progress_status():
        """Get status of Site Progress VAPI components"""
        try:
            manager = VAPISiteProgressManager()

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{manager.base_url}/assistant",
                    headers=manager.headers
                )

                if response.status_code == 200:
                    assistants = response.json()
                    site_progress_assistants = [
                        a for a in assistants
                        if "JSMB-Jill-site-progress" in a.get("name", "")
                    ]

                    return {
                        "success": True,
                        "site_progress_assistants": len(site_progress_assistants),
                        "assistants": site_progress_assistants,
                        "webhook_base": manager.webhook_base_url
                    }
                else:
                    return {
                        "success": False,
                        "error": f"VAPI API error: {response.status_code}"
                    }

        except Exception as e:
            logger.error(f"Status check failed: {e}")
            return {"success": False, "error": str(e)}
