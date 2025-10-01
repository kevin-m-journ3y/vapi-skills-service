"""
Voice Notes Skill

Allows users to record general or site-specific voice notes through natural conversation.
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

    This skill provides:
    - authenticate_caller: Verify user by phone number
    - identify_context: Determine if note is general or site-specific
    - save_note: Store the voice note in the database
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
            "authenticate_caller": {
                "type": "function",
                "function": {
                    "name": "authenticate_caller",
                    "description": "Authenticate the caller using their phone number to verify they are authorized",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "caller_phone": {
                                "type": "string",
                                "description": "The caller's phone number"
                            }
                        },
                        "required": ["caller_phone"]
                    }
                },
                "server": {
                    "url": f"{self.webhook_base_url}/api/v1/vapi/authenticate-by-phone"
                }
            },
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
        Create VAPI assistant for voice notes skill

        Args:
            tool_ids: Dictionary of tool names to VAPI tool IDs

        Returns:
            VAPI assistant ID
        """
        logger.info("Creating VAPI assistant for Voice Notes skill...")

        assistant_config = {
            "name": "JSMB-Jill-voice-notes",
            "model": {
                "provider": "openai",
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "system",
                        "content": """You are Jill, a professional voice notes assistant for construction companies.

Your job is to help users record voice notes efficiently and naturally.

CONVERSATION FLOW:
1. Greet warmly: "Hi! I'm ready to record your voice note. What would you like to record?"
2. Ask if this note relates to a specific construction site or is general
3. If site-specific, identify which site using identify_context
4. Listen to their complete note/message
5. When they're finished, confirm and save using save_note

CONVERSATION STYLE:
- Natural, warm, and efficient
- Let them speak freely - don't interrupt
- Ask clarifying questions only if needed
- Signal when you're ready to save: "Got it! Let me save that note for you."

Remember: You're helping capture important information quickly and accurately for any construction company."""
                    }
                ],
                "toolIds": [
                    tool_ids["identify_context"],
                    tool_ids["save_note"]
                ]
            },
            "voice": {
                "model": "eleven_turbo_v2_5",
                "voiceId": "MiueK1FXuZTCItgbQwPu",
                "provider": "11labs",
                "stability": 0.5,
                "similarityBoost": 0.75
            },
            "firstMessage": "Hi! I'm ready to record your voice note. What would you like to record?",
            "firstMessageMode": "assistant-speaks-first"
        }

        headers = {
            "Authorization": f"Bearer {self.vapi_api_key}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.vapi_base_url}/assistant",
                headers=headers,
                json=assistant_config
            )

            if response.status_code == 201:
                assistant = response.json()
                logger.info(f"Created assistant: {assistant['id']}")
                return assistant['id']
            else:
                logger.error(f"Failed to create assistant: {response.status_code} - {response.text}")
                raise Exception(f"Assistant creation failed: {response.text}")

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
