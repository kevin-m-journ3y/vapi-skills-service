"""
Jill Voice Notes Assistant

Professional voice notes assistant for construction companies.
"""

from typing import Dict, List
import logging

from app.assistants.base_assistant import BaseAssistant

logger = logging.getLogger(__name__)


class JillVoiceNotesAssistant(BaseAssistant):
    """
    Jill - Voice Notes Assistant

    A warm, professional assistant that helps construction company users
    record general and site-specific voice notes efficiently.
    """

    def __init__(self):
        super().__init__(
            assistant_key="jill-voice-notes",
            name="JSMB-Jill-voice-notes",
            description="Professional voice notes assistant for construction companies",
            required_skills=["authentication", "voice_notes"]
        )

    def get_system_prompt(self) -> str:
        """System prompt defining Jill's personality and behavior"""
        return """You are Jill, a professional voice notes assistant for construction companies.

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

    def get_first_message(self) -> str:
        """The greeting message Jill speaks first"""
        return "Hi! I'm ready to record your voice note. What would you like to record?"

    def get_voice_config(self) -> Dict:
        """Jill's voice configuration using ElevenLabs"""
        return {
            "model": "eleven_turbo_v2_5",
            "voiceId": "MiueK1FXuZTCItgbQwPu",
            "provider": "11labs",
            "stability": 0.5,
            "similarityBoost": 0.75
        }

    def get_model_config(self) -> Dict:
        """Model configuration for Jill (GPT-4)"""
        return {
            "provider": "openai",
            "model": "gpt-4"
        }

    def get_required_tool_names(self) -> List[str]:
        """Tools that Jill needs to function"""
        return [
            "authenticate_caller",  # From authentication skill
            "identify_context",     # From voice_notes skill
            "save_note"            # From voice_notes skill
        ]
