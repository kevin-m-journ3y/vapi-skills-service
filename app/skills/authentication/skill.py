"""
Authentication Skill

Provides phone-based authentication for VAPI assistants.
This skill can be reused across multiple assistants.
"""

from typing import Dict
from fastapi import FastAPI
import httpx
import logging

from app.skills.base_skill import BaseSkill
from app.config import settings

logger = logging.getLogger(__name__)


class AuthenticationSkill(BaseSkill):
    """
    Authentication Skill - Verify callers by phone number

    This skill provides:
    - authenticate_caller: Verify user by phone number

    This is a reusable skill that can be used by any assistant requiring
    phone-based authentication.
    """

    def __init__(self):
        super().__init__(
            skill_key="authentication",
            name="Authentication",
            description="Phone-based caller authentication"
        )
        self.vapi_api_key = settings.VAPI_API_KEY
        self.vapi_base_url = "https://api.vapi.ai"
        self.webhook_base_url = settings.webhook_base_url

        if not self.vapi_api_key:
            raise ValueError("VAPI_API_KEY not configured")

    async def create_tools(self) -> Dict[str, str]:
        """
        Create VAPI authentication tool

        Returns:
            Dict with tool names mapped to VAPI tool IDs
        """
        logger.info("Creating VAPI tools for Authentication skill...")

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
        Authentication skill does not create assistants.
        It only provides tools that assistants can use.

        Raises:
            NotImplementedError: This skill doesn't create assistants
        """
        raise NotImplementedError(
            "AuthenticationSkill does not create assistants. "
            "It provides tools for assistants to use."
        )

    def register_routes(self, app: FastAPI, prefix: str = ""):
        """
        Register authentication endpoints with FastAPI

        Args:
            app: FastAPI application instance
            prefix: Optional URL prefix (e.g., "/api/v1")
        """
        from app.skills.authentication.endpoints import router

        app.include_router(router, prefix=prefix)
        logger.info(f"Registered Authentication routes with prefix: {prefix}")
