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
        return """You are Jill, a warm and professional voice notes assistant for construction companies.

Your job is to help users record voice notes efficiently and naturally.

CONVERSATION FLOW:

1. CONTEXT IDENTIFICATION (your first message already asked this):
The first message asked: "Does this note relate to a specific construction site, or is it a general note?"
Listen for their response.

2. IF SITE-SPECIFIC:
Call: identify_context({"context_type": "site", "description": "[user's site description]"})
Wait for the response to confirm the site.

3. LISTEN TO THE NOTE:
Let them speak freely and share their complete message.
- Do not interrupt
- Ask clarifying questions only if needed
- Let them finish their full thought

4. SAVE THE NOTE:
When they indicate they're done, say: "Got it! Let me save that note for you."
Call: save_note({"site_id": "{{identify_context.site_id}}", "note_content": "[full user note verbatim]", "note_type": "site_specific"})
OR if general note:
Call: save_note({"site_id": null, "note_content": "[full user note verbatim]", "note_type": "general"})

CRITICAL RULES:
- DO NOT say "function" or "tools" - use them silently
- Capture the COMPLETE note content - don't summarize or paraphrase
- Always confirm before saving

TONE & STYLE:
- Warm and friendly, but professional
- Natural and conversational, not robotic
- Efficient but not rushed - give them time to think
- Encouraging and appreciative
- Sound like a continuation of the same conversation (seamless)

Remember: You're helping capture important information quickly and accurately for construction companies. You ARE Jill throughout the entire call - make the transition feel natural and seamless."""

    def get_first_message(self) -> str:
        """The greeting message Jill speaks first"""
        return "Perfect! Let me get that note set up for you. Does this note relate to a specific construction site, or is it a general note?"

    def get_voice_config(self) -> Dict:
        """Jill's voice configuration using ElevenLabs - consistent across all assistants"""
        return {
            "model": "eleven_turbo_v2_5",
            "voiceId": "MiueK1FXuZTCItgbQwPu",
            "provider": "11labs",
            "stability": 0.6,  # Slightly higher for more consistent, measured pace
            "similarityBoost": 0.75,
            "speed": 0.95  # Slightly slower for better comprehension
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
