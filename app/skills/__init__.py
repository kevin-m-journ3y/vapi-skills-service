"""
VAPI Skills Module

All skills inherit from BaseSkill and are registered with the SkillRegistry.
"""

from app.skills.base_skill import BaseSkill
from app.skills.skill_registry import SkillRegistry, skill_registry

__all__ = ["BaseSkill", "SkillRegistry", "skill_registry"]
