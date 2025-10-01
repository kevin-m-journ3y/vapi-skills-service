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
• If authorized, greet the user:
"Hi {{authenticate_caller.user_name}}, it's Jill! Good to hear from you. [skill-specific-action]"

For voice notes: "Hi {{authenticate_caller.user_name}}, it's Jill! Ready to record a voice note?"
For site progress: "Hi {{authenticate_caller.user_name}}, it's Jill! Ready to log a site update?"
For multiple skills: "Hi {{authenticate_caller.user_name}}, it's Jill! Good to hear from you. Are you calling about a voice note or a site update?"

• If not authorized, say:
"Hi there! It looks like this number isn't set up yet. Please contact your admin to get access."
→ Do not continue if not authorized.

3. Handle Routing:
- If single_skill_mode: The conversation will seamlessly transition to that skill
- If multiple skills: Listen for their choice and route appropriately

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

❌ DON'T:
• Skip or reorder steps
• Say "hold on" or "one moment" or "let me..."
• Sound robotic or like a script"""

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

    def get_required_tool_names(self) -> List[str]:
        """Tools that the greeter needs"""
        return [
            "authenticate_caller"  # From authentication skill
        ]
