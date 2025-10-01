"""
Voice Notes Skill

Provides tools for recording general or site-specific voice notes.
This skill only defines tools - it does not create assistants.
"""

from typing import Dict, Optional
from fastapi import FastAPI
import httpx
import logging

from app.skills.base_skill import BaseSkill
from app.config import settings

logger = logging.getLogger(__name__)


class VoiceNotesSkill(BaseSkill):
    """
    Voice Notes Skill - Record general and site-specific voice notes

    This skill provides tools only:
    - identify_context: Determine if note is general or site-specific
    - save_note: Store the voice note in the database

    Note: This skill does not create assistants. Use an assistant definition
    to orchestrate these tools.
    """

    def __init__(self):
        super().__init__(
            skill_key="voice_notes",
            name="Voice Notes",
            description="Record general or site-specific voice notes"
        )
        self.vapi_api_key = settings.VAPI_API_KEY
        self.vapi_base_url = "https://api.vapi.ai"
        self.webhook_base_url = settings.webhook_base_url

        if not self.vapi_api_key:
            raise ValueError("VAPI_API_KEY not configured")

    async def create_tools(self) -> Dict[str, str]:
        """
        Create VAPI tools for voice notes skill

        Returns:
            Dict with tool names mapped to VAPI tool IDs
        """
        logger.info("Creating VAPI tools for Voice Notes skill...")

        tools_config = {
            "identify_context": {
                "type": "function",
                "function": {
                    "name": "identify_context",
                    "description": "Identify whether the voice note is general or site-specific based on user input",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "user_input": {
                                "type": "string",
                                "description": "The user's description of what their note is about"
                            },
                            "vapi_call_id": {
                                "type": "string",
                                "description": "The VAPI call identifier"
                            }
                        },
                        "required": ["user_input", "vapi_call_id"]
                    }
                },
                "server": {
                    "url": f"{self.webhook_base_url}/api/v1/skills/voice-notes/identify-context"
                }
            },
            "save_note": {
                "type": "function",
                "function": {
                    "name": "save_note",
                    "description": "Save the voice note with all collected information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "note_text": {
                                "type": "string",
                                "description": "The transcribed voice note content"
                            },
                            "note_type": {
                                "type": "string",
                                "enum": ["general", "site_specific"],
                                "description": "Whether this is a general note or site-specific note"
                            },
                            "site_id": {
                                "type": "string",
                                "description": "Site ID if this is a site-specific note (null for general notes)"
                            },
                            "priority": {
                                "type": "string",
                                "enum": ["low", "medium", "high", "urgent"],
                                "description": "Priority level of the note"
                            },
                            "vapi_call_id": {
                                "type": "string",
                                "description": "The VAPI call identifier"
                            }
                        },
                        "required": ["note_text", "note_type", "vapi_call_id"]
                    }
                },
                "server": {
                    "url": f"{self.webhook_base_url}/api/v1/skills/voice-notes/save-note"
                }
            }
        }

        tool_ids = {}
        headers = {
            "Authorization": f"Bearer {self.vapi_api_key}",
            "Content-Type": "application/json"
        }

        # Check for existing tools first
        existing_tools = await self._get_existing_tools(headers)

        async with httpx.AsyncClient() as client:
            for tool_name, tool_config in tools_config.items():
                # Skip if tool already exists
                if tool_name in existing_tools:
                    tool_ids[tool_name] = existing_tools[tool_name]
                    logger.info(f"Using existing tool: {tool_name} ({tool_ids[tool_name]})")
                    continue

                # Create new tool
                response = await client.post(
                    f"{self.vapi_base_url}/tool",
                    headers=headers,
                    json=tool_config
                )

                if response.status_code == 201:
                    tool = response.json()
                    tool_ids[tool_name] = tool['id']
                    logger.info(f"Created tool: {tool_name} ({tool_ids[tool_name]})")
                else:
                    logger.error(f"Failed to create tool {tool_name}: {response.status_code} - {response.text}")
                    raise Exception(f"Tool creation failed for {tool_name}: {response.text}")

        return tool_ids

    async def _get_existing_tools(self, headers: Dict) -> Dict[str, str]:
        """Get existing tools to avoid duplicates"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.vapi_base_url}/tool",
                headers=headers
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

    async def create_assistant(self, tool_ids: Dict[str, str]) -> str:
        """
        Voice Notes skill does not create assistants.
        It only provides tools that assistants can use.

        Raises:
            NotImplementedError: This skill doesn't create assistants
        """
        raise NotImplementedError(
            "VoiceNotesSkill does not create assistants. "
            "It provides tools for assistants to use. "
            "Use an assistant definition (e.g., JillVoiceNotesAssistant) instead."
        )

    def register_routes(self, app: FastAPI, prefix: str = ""):
        """
        Register voice notes endpoints with FastAPI

        Args:
            app: FastAPI application instance
            prefix: Optional URL prefix (e.g., "/api/v1")
        """
        from app.skills.voice_notes.endpoints import router

        app.include_router(router, prefix=prefix)
        logger.info(f"Registered Voice Notes routes with prefix: {prefix}")
