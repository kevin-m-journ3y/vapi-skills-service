"""
Base Skill Class for VAPI Skills System

All skills (Voice Notes, Site Updates, Project Summary, etc.) inherit from this base class.
This ensures consistent structure and makes adding new skills straightforward.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, List
from fastapi import FastAPI
import logging

logger = logging.getLogger(__name__)


class BaseSkill(ABC):
    """
    Abstract base class for VAPI skills.

    Each skill must implement:
    - create_tools(): Create VAPI tools and return tool IDs
    - create_assistant(): Create VAPI assistant using tool IDs
    - register_routes(): Register FastAPI endpoints for the skill
    """

    def __init__(self, skill_key: str, name: str, description: str):
        """
        Initialize a skill.

        Args:
            skill_key: Unique identifier for this skill (e.g., "voice_notes")
            name: Human-readable name (e.g., "Voice Notes")
            description: Brief description of what this skill does
        """
        self.skill_key = skill_key
        self.name = name
        self.description = description
        self.tool_ids: Dict[str, str] = {}
        self.assistant_id: Optional[str] = None

        logger.info(f"Initialized skill: {self.name} ({self.skill_key})")

    @abstractmethod
    async def create_tools(self) -> Dict[str, str]:
        """
        Create VAPI tools for this skill.

        Returns:
            Dict mapping tool names to their VAPI tool IDs
            Example: {"identify_context": "tool_abc123", "save_note": "tool_def456"}
        """
        pass

    @abstractmethod
    async def create_assistant(self, tool_ids: Dict[str, str]) -> str:
        """
        Create VAPI assistant for this skill.

        Args:
            tool_ids: Dictionary of tool names to VAPI tool IDs

        Returns:
            VAPI assistant ID
        """
        pass

    @abstractmethod
    def register_routes(self, app: FastAPI, prefix: str = ""):
        """
        Register FastAPI routes for this skill's webhook endpoints.

        Args:
            app: FastAPI application instance
            prefix: Optional URL prefix (e.g., "/api/v1")
        """
        pass

    async def setup(self) -> Dict[str, str]:
        """
        Complete setup for this skill: create tools and assistant.

        Returns:
            Dictionary with setup information
        """
        logger.info(f"Setting up skill: {self.name}")

        # Create tools
        self.tool_ids = await self.create_tools()
        logger.info(f"Created {len(self.tool_ids)} tools for {self.name}: {list(self.tool_ids.keys())}")

        # Create assistant
        self.assistant_id = await self.create_assistant(self.tool_ids)
        logger.info(f"Created assistant for {self.name}: {self.assistant_id}")

        return {
            "skill_key": self.skill_key,
            "skill_name": self.name,
            "tool_ids": self.tool_ids,
            "assistant_id": self.assistant_id
        }

    def get_info(self) -> Dict[str, any]:
        """
        Get information about this skill.

        Returns:
            Dictionary with skill metadata
        """
        return {
            "skill_key": self.skill_key,
            "name": self.name,
            "description": self.description,
            "tool_count": len(self.tool_ids),
            "tools": list(self.tool_ids.keys()),
            "assistant_id": self.assistant_id,
            "is_ready": self.assistant_id is not None
        }
