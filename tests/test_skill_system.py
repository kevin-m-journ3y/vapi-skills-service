"""
Unit tests for skill-based architecture
Tests BaseSkill, SkillRegistry, and skill instantiation
"""

import pytest
import asyncio
from app.skills.base_skill import BaseSkill
from app.skills.skill_registry import SkillRegistry
from app.skills.voice_notes import VoiceNotesSkill


class TestBaseSkill:
    """Test BaseSkill abstract class"""

    def test_base_skill_cannot_instantiate_directly(self):
        """BaseSkill is abstract and should not be instantiable"""
        with pytest.raises(TypeError):
            BaseSkill("test", "Test Skill", "Test description")

    def test_voice_notes_skill_instantiation(self):
        """VoiceNotesSkill should instantiate correctly"""
        skill = VoiceNotesSkill()
        assert skill.skill_key == "voice_notes"
        assert skill.name == "Voice Notes"
        assert skill.description == "Record general or site-specific voice notes"
        assert skill.tool_ids == {}
        assert skill.assistant_id is None

    def test_skill_get_info(self):
        """get_info() should return skill metadata"""
        skill = VoiceNotesSkill()
        info = skill.get_info()

        assert info["skill_key"] == "voice_notes"
        assert info["name"] == "Voice Notes"
        assert info["description"] == "Record general or site-specific voice notes"
        assert info["tool_count"] == 0
        assert info["tools"] == []
        assert info["assistant_id"] is None
        assert info["is_ready"] is False


class TestSkillRegistry:
    """Test SkillRegistry functionality"""

    def test_registry_initialization(self):
        """Registry should initialize empty"""
        registry = SkillRegistry()
        assert len(registry.skills) == 0

    def test_register_skill(self):
        """Should be able to register a skill"""
        registry = SkillRegistry()
        skill = VoiceNotesSkill()

        registry.register(skill)

        assert len(registry.skills) == 1
        assert "voice_notes" in registry.skills
        assert registry.get_skill("voice_notes") == skill

    def test_register_duplicate_skill_replaces(self):
        """Registering same skill key should replace"""
        registry = SkillRegistry()
        skill1 = VoiceNotesSkill()
        skill2 = VoiceNotesSkill()

        registry.register(skill1)
        registry.register(skill2)

        assert len(registry.skills) == 1
        assert registry.get_skill("voice_notes") == skill2

    def test_get_nonexistent_skill(self):
        """Getting non-existent skill should return None"""
        registry = SkillRegistry()
        assert registry.get_skill("nonexistent") is None

    def test_list_skills(self):
        """list_skills() should return info for all skills"""
        registry = SkillRegistry()
        skill = VoiceNotesSkill()
        registry.register(skill)

        skills = registry.list_skills()

        assert len(skills) == 1
        assert skills[0]["skill_key"] == "voice_notes"
        assert skills[0]["name"] == "Voice Notes"

    def test_get_assistant_ids(self):
        """get_assistant_ids() should return dict of skill keys to assistant IDs"""
        registry = SkillRegistry()
        skill = VoiceNotesSkill()
        registry.register(skill)

        assistant_ids = registry.get_assistant_ids()

        assert "voice_notes" in assistant_ids
        assert assistant_ids["voice_notes"] is None  # Not set up yet

    def test_get_skills_for_squad(self):
        """get_skills_for_squad() should return only skills with assistant_id"""
        registry = SkillRegistry()
        skill = VoiceNotesSkill()
        registry.register(skill)

        # Before setup - no assistant_id
        squad_skills = registry.get_skills_for_squad()
        assert len(squad_skills) == 0

        # After manually setting assistant_id
        skill.assistant_id = "test_assistant_id"
        squad_skills = registry.get_skills_for_squad()
        assert len(squad_skills) == 1
        assert squad_skills[0]["skill_key"] == "voice_notes"
        assert squad_skills[0]["assistant_id"] == "test_assistant_id"


class TestVoiceNotesSkill:
    """Test VoiceNotesSkill specific functionality"""

    def test_skill_has_required_methods(self):
        """Skill should implement all required methods"""
        skill = VoiceNotesSkill()

        assert hasattr(skill, "create_tools")
        assert hasattr(skill, "create_assistant")
        assert hasattr(skill, "register_routes")
        assert callable(skill.create_tools)
        assert callable(skill.create_assistant)
        assert callable(skill.register_routes)

    def test_skill_has_vapi_config(self):
        """Skill should have VAPI configuration"""
        skill = VoiceNotesSkill()

        assert hasattr(skill, "vapi_api_key")
        assert hasattr(skill, "vapi_base_url")
        assert hasattr(skill, "webhook_base_url")
        assert skill.vapi_base_url == "https://api.vapi.ai"


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
