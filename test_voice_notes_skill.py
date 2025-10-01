#!/usr/bin/env python3
"""
Test script to verify VoiceNotesSkill works correctly
"""

import asyncio
import sys
from app.skills.voice_notes import VoiceNotesSkill
from app.skills import skill_registry


async def test_voice_notes_skill():
    """Test the VoiceNotesSkill setup"""
    print("=" * 60)
    print("Testing VoiceNotesSkill")
    print("=" * 60)

    try:
        # Create skill instance
        print("\n1. Creating VoiceNotesSkill instance...")
        skill = VoiceNotesSkill()
        print(f"   ✓ Skill created: {skill.name} ({skill.skill_key})")
        print(f"   Webhook base URL: {skill.webhook_base_url}")

        # Register with registry
        print("\n2. Registering with skill registry...")
        skill_registry.register(skill)
        print(f"   ✓ Registered")

        # List registered skills
        print("\n3. Listing registered skills...")
        skills = skill_registry.list_skills()
        for s in skills:
            print(f"   - {s['name']} ({s['skill_key']}): ready={s['is_ready']}")

        print("\n" + "=" * 60)
        print("✓ VoiceNotesSkill test passed!")
        print("=" * 60)

        return True

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_voice_notes_skill())
    sys.exit(0 if success else 1)
