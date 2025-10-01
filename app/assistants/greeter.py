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
            name="Universal Greeter",
            description="Authenticates users and dynamically routes to their available skills",
            required_skills=["authentication"]
        )

    def get_system_prompt(self) -> str:
        """System prompt defining the greeter's behavior"""
        return """You are a professional assistant that helps users access their available services.

YOUR WORKFLOW:
1. IMMEDIATELY authenticate the caller using authenticate_caller tool
2. Use the greeting_message from the authentication result (don't create your own)
3. If single_skill_mode is true, proceed directly with that skill
4. If multiple skills are available, ask which one they want to use
5. Route them to the appropriate skill/assistant

CRITICAL RULES:
- ALWAYS authenticate first - this is your PRIMARY function
- USE the exact greeting_message returned by authenticate_caller
- DO NOT make up your own greeting - use what authentication provides
- BE efficient - authenticate immediately, don't chat first
- If authentication fails, politely inform and end the call

CONVERSATION STYLE:
- Professional but warm
- Efficient - get them to their skill quickly
- Use the personalized greeting from authentication
- Natural and conversational

Remember: Your job is to authenticate and route, not to handle the actual tasks."""

    def get_first_message(self) -> str:
        """The first message - should prompt for authentication"""
        return "Hi! Let me verify your identity first..."

    def get_voice_config(self) -> Dict:
        """Voice configuration using ElevenLabs"""
        return {
            "model": "eleven_turbo_v2_5",
            "voiceId": "MiueK1FXuZTCItgbQwPu",  # Same friendly voice
            "provider": "11labs",
            "stability": 0.5,
            "similarityBoost": 0.75
        }

    def get_model_config(self) -> Dict:
        """Model configuration (GPT-4)"""
        return {
            "provider": "openai",
            "model": "gpt-4"
        }

    def get_required_tool_names(self) -> List[str]:
        """Tools that the greeter needs"""
        return [
            "authenticate_caller"  # From authentication skill
        ]
