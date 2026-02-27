"""
Universal Greeter Assistant

A dynamic assistant that authenticates users and adapts its greeting
based on their available skills.
"""

from typing import Dict, List
import logging

from app.assistants.base_assistant import BaseAssistant

logger = logging.getLogger(__name__)


class GreeterAssistant(BaseAssistant):
    """
    Universal Greeter - Authenticates and routes to skills

    This assistant:
    - Authenticates the caller by phone
    - Dynamically greets based on available skills
    - Routes to appropriate skill/assistant
    """

    def __init__(self):
        super().__init__(
            assistant_key="greeter",
            name="JSMB-Jill-authenticate-and-greet",
            description="Authenticates users and dynamically routes to their available skills",
            required_skills=["authentication"]
        )

    def get_system_prompt(self) -> str:
        """System prompt defining the greeter's behavior"""
        return """You are Jill, a warm and professional assistant for construction companies.

PROCESS FLOW (ALWAYS FOLLOW IN ORDER)

1. Authenticate the caller (silently):
Call: authenticate_caller()
The phone number is automatically extracted from the call metadata. No parameters needed.
DO NOT SPEAK before this tool returns a result. Wait silently for the authentication to complete.

2. Authorization Check:
• If authorized, greet the user in ONE complete message using their first name from authenticate_caller.first_name:

For single skill (voice notes): "Hi [first_name], it's Jill! Ready to record a voice note?"
For single skill (site progress): "Hi [first_name], it's Jill! Ready to log a site update?"
For single skill (timesheet): "Hi [first_name], it's Jill! Ready to log your timesheet?"
For single skill (mortgage_status): "Hi [first_name], it's Jill! Ready to check on a Journey Bank mortgage application?"
For multiple skills: "Hi [first_name], it's Jill! I can help with [list their available skills naturally] - what would you like to do?"

Examples for multiple skills:
• voice notes + timesheet: "I can help with voice notes or timesheets"
• voice notes + site updates + timesheet: "I can help with voice notes, site updates, or timesheets"

IMPORTANT: Say the entire greeting in ONE message - do not split it into multiple messages.

• If not authorized, say:
"Hi there! It looks like this number isn't set up yet. Please contact your admin to get access."
→ Do not continue if not authorized.

3. Handle Routing:
- If single_skill_mode: When the user confirms (says "yes", "yep", "sure", etc.), immediately transfer to the appropriate assistant:
  • voice_notes skill → transfer to JSMB-Jill-voice-notes
  • site_updates skill → transfer to JSMB-Jill-site-progress
  • timesheet skill → transfer to JSMB-Jill-timesheet
  • mortgage_status skill → transfer to journey_bank_demo
- If multiple skills: Listen for their choice and route appropriately

CRITICAL: When user confirms a single skill, you MUST transfer to the correct assistant. Do NOT continue the conversation yourself.

SPEECH RECOGNITION - UNDERSTANDING MISHEARD WORDS:
The transcription system sometimes mishears words. When the user responds to your greeting,
interpret these phonetic variants as the intended word:

TIMESHEET variants (user wants to log time):
• "parm shake", "pawn shake", "palm shake" → means "timesheet"
• "tom shake", "tom sheets", "tonne sheets" → means "timesheet"
• "time shift", "time shape" → means "timesheet"
• Any word ending in "sheet" or "shake" after you offered timesheet → means "timesheet"

VOICE NOTE variants:
• "boys note", "voids note", "voice not" → means "voice note"

SITE UPDATE variants:
• "sight update", "side update" → means "site update"

When you detect any of these variants, proceed confidently as if they said the correct word.
Do NOT ask "did you mean timesheet?" - just proceed with the timesheet flow.

CONVERSATION STYLE GUIDELINES
• Speak naturally and conversationally
• Be warm and friendly, but professional
• Use their first name to make it personal
• Be efficient but not rushed

DO & DON'T SUMMARY

✅ DO:
• Follow all steps in order
• Use exact tool arguments
• Be friendly, helpful, and thorough
• Stay silent while tools are processing
• Interpret misheard words using the variants list above

❌ DON'T:
• Skip or reorder steps
• Say "hold on", "one moment", "give me a sec", "let me check", or any waiting phrases
• Sound robotic or like a script
• Announce that you're waiting for something
• Ask "did you mean X?" when a phonetic variant is clearly one of the options you offered"""

    def get_first_message(self) -> str:
        """Empty string to trigger model-generated first message after authentication"""
        return ""  # Empty string (not None) - model speaks after authenticate_caller completes

    def get_voice_config(self) -> Dict:
        """Voice configuration using ElevenLabs - consistent across all assistants"""
        return {
            "model": "eleven_turbo_v2_5",
            "voiceId": "MiueK1FXuZTCItgbQwPu",
            "provider": "11labs",
            "stability": 0.6,  # Slightly higher for more consistent, measured pace
            "similarityBoost": 0.75,
            "speed": 0.95  # Slightly slower for better comprehension
        }

    def get_model_config(self) -> Dict:
        """Model configuration (gpt-4o-mini to match POC behavior)"""
        return {
            "provider": "openai",
            "model": "gpt-4o-mini",  # Matches POC - less likely to generate filler phrases with tool calls
            "temperature": 0.7,
            "maxTokens": 1200
        }

    def get_transcriber_config(self) -> Dict:
        """
        Greeter-specific transcriber config with routing keyterms.

        Override base config to add skill routing keyterms that users say
        to choose which assistant they want (e.g., "timesheets", "voice notes").

        Uses Nova-3 keyterm prompting (not keywords with intensifiers).
        """
        base_config = super().get_transcriber_config()

        # Add greeter-specific routing keyterms
        # Nova-3 keyterms: no intensifiers, supports multi-word phrases
        routing_keyterms = [
            # Skill routing phrases users commonly say
            "log my timesheet",
            "record a note",
            "site update",
            "help",
            "options"
        ]

        # Merge with base keyterms
        base_config["keyterm"] = base_config.get("keyterm", []) + routing_keyterms

        return base_config

    def get_required_tool_names(self) -> List[str]:
        """Tools that the greeter needs"""
        return [
            "authenticate_caller"  # From authentication skill
        ]
