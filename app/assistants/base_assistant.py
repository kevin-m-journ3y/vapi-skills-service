"""
Base Assistant

Abstract base class for all VAPI assistants.
Assistants orchestrate skills and define conversation flow.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import httpx
import logging

from app.config import settings

logger = logging.getLogger(__name__)


class BaseAssistant(ABC):
    """
    Base class for VAPI assistants

    Assistants define:
    - Personality and system prompts
    - Voice configuration
    - Which tools/skills to use
    - Conversation flow and greeting
    """

    def __init__(
        self,
        assistant_key: str,
        name: str,
        description: str,
        required_skills: List[str]
    ):
        """
        Initialize assistant

        Args:
            assistant_key: Unique identifier for this assistant
            name: Human-readable name
            description: What this assistant does
            required_skills: List of skill keys this assistant needs
        """
        self.assistant_key = assistant_key
        self.name = name
        self.description = description
        self.required_skills = required_skills
        self.assistant_id: Optional[str] = None
        self.vapi_api_key = settings.VAPI_API_KEY
        self.vapi_base_url = "https://api.vapi.ai"

        if not self.vapi_api_key:
            raise ValueError("VAPI_API_KEY not configured")

    @abstractmethod
    def get_system_prompt(self) -> str:
        """
        Get the system prompt for this assistant

        Returns:
            System prompt text
        """
        pass

    @abstractmethod
    def get_first_message(self) -> str:
        """
        Get the greeting message for this assistant

        Returns:
            First message text
        """
        pass

    @abstractmethod
    def get_voice_config(self) -> Dict:
        """
        Get voice configuration for this assistant

        Returns:
            Voice config dictionary
        """
        pass

    @abstractmethod
    def get_model_config(self) -> Dict:
        """
        Get model configuration (provider, model name, etc.)

        Returns:
            Model config dictionary
        """
        pass

    def get_required_tool_names(self) -> List[str]:
        """
        Get list of tool names this assistant needs.
        Override this if needed, or implement in subclass.

        Returns:
            List of tool function names
        """
        return []

    async def create(self, tool_ids: Dict[str, str]) -> str:
        """
        Create VAPI assistant with specified tools

        Args:
            tool_ids: Dictionary mapping tool names to VAPI tool IDs

        Returns:
            VAPI assistant ID
        """
        logger.info(f"Creating VAPI assistant: {self.name}...")

        # Get required tool IDs
        required_tool_names = self.get_required_tool_names()
        assistant_tool_ids = []
        for tool_name in required_tool_names:
            if tool_name in tool_ids:
                assistant_tool_ids.append(tool_ids[tool_name])
            else:
                raise ValueError(f"Required tool '{tool_name}' not found in provided tool_ids")

        # Build assistant config
        model_config = self.get_model_config()
        model_config["messages"] = [
            {
                "role": "system",
                "content": self.get_system_prompt()
            }
        ]
        model_config["toolIds"] = assistant_tool_ids

        assistant_config = {
            "name": self.assistant_key,
            "model": model_config,
            "voice": self.get_voice_config(),
            "firstMessage": self.get_first_message(),
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
                self.assistant_id = assistant['id']
                logger.info(f"Created assistant: {self.name} ({self.assistant_id})")
                return self.assistant_id
            else:
                logger.error(f"Failed to create assistant: {response.status_code} - {response.text}")
                raise Exception(f"Assistant creation failed: {response.text}")

    async def setup(self, all_tool_ids: Dict[str, str]) -> Dict:
        """
        Set up this assistant (create it if needed)

        Args:
            all_tool_ids: All available tool IDs from registered skills

        Returns:
            Setup information dictionary
        """
        try:
            assistant_id = await self.create(all_tool_ids)
            return {
                "assistant_key": self.assistant_key,
                "name": self.name,
                "assistant_id": assistant_id,
                "required_skills": self.required_skills
            }
        except Exception as e:
            logger.error(f"Failed to setup assistant {self.name}: {str(e)}")
            raise
