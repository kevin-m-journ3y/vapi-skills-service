"""
Skill Registry - Central management for all VAPI skills and assistants

The registry maintains all registered skills and assistants and provides methods to:
- Register new skills and assistants
- Set up all skills (create tools) and assistants
- Retrieve skill and assistant information
- Register all skill routes with FastAPI
"""

from typing import Dict, List, Optional, TYPE_CHECKING
from fastapi import FastAPI
import logging
from app.skills.base_skill import BaseSkill

if TYPE_CHECKING:
    from app.assistants.base_assistant import BaseAssistant

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Central registry for managing VAPI skills and assistants.

    Usage:
        registry = SkillRegistry()
        registry.register_skill(VoiceNotesSkill())
        registry.register_skill(AuthenticationSkill())
        registry.register_assistant(JillVoiceNotesAssistant())
        await registry.setup_all()
        registry.register_all_routes(app)
    """

    def __init__(self):
        self.skills: Dict[str, BaseSkill] = {}
        self.assistants: Dict[str, "BaseAssistant"] = {}
        logger.info("Initialized SkillRegistry")

    def register(self, skill: BaseSkill) -> None:
        """
        Register a skill with the registry (legacy method).

        Args:
            skill: An instance of a skill that inherits from BaseSkill
        """
        self.register_skill(skill)

    def register_skill(self, skill: BaseSkill) -> None:
        """
        Register a skill with the registry.

        Args:
            skill: An instance of a skill that inherits from BaseSkill
        """
        if skill.skill_key in self.skills:
            logger.warning(f"Skill {skill.skill_key} already registered, replacing")

        self.skills[skill.skill_key] = skill
        logger.info(f"Registered skill: {skill.name} ({skill.skill_key})")

    def register_assistant(self, assistant: "BaseAssistant") -> None:
        """
        Register an assistant with the registry.

        Args:
            assistant: An instance of an assistant that inherits from BaseAssistant
        """
        if assistant.assistant_key in self.assistants:
            logger.warning(f"Assistant {assistant.assistant_key} already registered, replacing")

        self.assistants[assistant.assistant_key] = assistant
        logger.info(f"Registered assistant: {assistant.name} ({assistant.assistant_key})")

    def get_skill(self, skill_key: str) -> Optional[BaseSkill]:
        """
        Get a skill by its key.

        Args:
            skill_key: The unique identifier for the skill

        Returns:
            The skill instance, or None if not found
        """
        return self.skills.get(skill_key)

    def list_skills(self) -> List[Dict]:
        """
        Get information about all registered skills.

        Returns:
            List of skill information dictionaries
        """
        return [skill.get_info() for skill in self.skills.values()]

    async def setup_all_skills(self) -> Dict[str, Dict]:
        """
        Set up all registered skills by creating their tools (legacy method).

        Returns:
            Dictionary mapping skill keys to their setup information
        """
        return await self.setup_all()

    async def setup_all(self) -> Dict[str, Dict]:
        """
        Set up all registered skills and assistants.

        First creates all skill tools, then creates assistants using those tools.

        Returns:
            Dictionary with 'skills' and 'assistants' setup information
        """
        logger.info(f"Setting up {len(self.skills)} skills and {len(self.assistants)} assistants...")

        # Step 1: Set up all skills (create tools)
        skill_results = {}
        all_tool_ids = {}

        for skill_key, skill in self.skills.items():
            try:
                # Just create tools, not assistants
                tool_ids = await skill.create_tools()
                skill.tool_ids = tool_ids
                all_tool_ids.update(tool_ids)

                skill_results[skill_key] = {
                    "success": True,
                    "tool_ids": tool_ids
                }
                logger.info(f"Successfully set up skill: {skill.name} (created {len(tool_ids)} tools)")
            except Exception as e:
                logger.error(f"Failed to set up skill {skill.name}: {e}", exc_info=True)
                skill_results[skill_key] = {
                    "success": False,
                    "error": str(e)
                }

        # Step 2: Set up all assistants (create assistants with tools)
        assistant_results = {}

        for assistant_key, assistant in self.assistants.items():
            try:
                setup_info = await assistant.setup(all_tool_ids)
                assistant_results[assistant_key] = {
                    "success": True,
                    "info": setup_info
                }
                logger.info(f"Successfully set up assistant: {assistant.name}")
            except Exception as e:
                logger.error(f"Failed to set up assistant {assistant.name}: {e}", exc_info=True)
                assistant_results[assistant_key] = {
                    "success": False,
                    "error": str(e)
                }

        successful_skills = sum(1 for r in skill_results.values() if r["success"])
        successful_assistants = sum(1 for r in assistant_results.values() if r["success"])

        logger.info(f"Setup complete: {successful_skills}/{len(self.skills)} skills, "
                   f"{successful_assistants}/{len(self.assistants)} assistants")

        return {
            "skills": skill_results,
            "assistants": assistant_results,
            "all_tool_ids": all_tool_ids
        }

    def register_all_routes(self, app: FastAPI, prefix: str = "") -> None:
        """
        Register routes for all skills with the FastAPI application.

        Args:
            app: FastAPI application instance
            prefix: Optional URL prefix for all routes (e.g., "/api/v1")
        """
        logger.info(f"Registering routes for {len(self.skills)} skills...")

        for skill in self.skills.values():
            try:
                skill.register_routes(app, prefix)
                logger.info(f"Registered routes for skill: {skill.name}")
            except Exception as e:
                logger.error(f"Failed to register routes for {skill.name}: {e}", exc_info=True)

    async def setup_skill(self, skill_key: str) -> Dict:
        """
        Set up a specific skill by its key.

        Args:
            skill_key: The unique identifier for the skill

        Returns:
            Setup information for the skill
        """
        skill = self.get_skill(skill_key)
        if not skill:
            return {
                "success": False,
                "error": f"Skill {skill_key} not found"
            }

        try:
            setup_info = await skill.setup()
            return {
                "success": True,
                "info": setup_info
            }
        except Exception as e:
            logger.error(f"Failed to set up skill {skill_key}: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def get_assistant_ids(self) -> Dict[str, Optional[str]]:
        """
        Get all assistant IDs for registered skills.

        Returns:
            Dictionary mapping skill keys to their assistant IDs
        """
        return {
            skill_key: skill.assistant_id
            for skill_key, skill in self.skills.items()
        }

    def get_skills_for_squad(self) -> List[Dict]:
        """
        Get skill information formatted for VAPI squad creation.

        Returns:
            List of skill info suitable for squad member configuration
        """
        return [
            {
                "skill_key": skill.skill_key,
                "skill_name": skill.name,
                "assistant_id": skill.assistant_id
            }
            for skill in self.skills.values()
            if skill.assistant_id is not None
        ]


# Global registry instance
skill_registry = SkillRegistry()
