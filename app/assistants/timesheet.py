"""
Jill Timesheet Assistant

Professional timesheet assistant for construction companies.
"""

from typing import Dict, List
import logging

from app.assistants.base_assistant import BaseAssistant
from app.assistants.timesheet_prompt_v2 import TIMESHEET_SYSTEM_PROMPT_V2

logger = logging.getLogger(__name__)


class TimesheetAssistant(BaseAssistant):
    """
    Jill - Timesheet Assistant

    A warm, professional assistant that helps construction company users
    log their work hours at sites efficiently through conversation.
    """

    def __init__(self):
        super().__init__(
            assistant_key="timesheet",
            name="JSMB-Jill-timesheet",
            description="Professional timesheet assistant for construction companies",
            required_skills=["authentication", "timesheet"]
        )

    def get_system_prompt(self) -> str:
        """System prompt defining Jill's personality and behavior for timesheet logging"""
        return TIMESHEET_SYSTEM_PROMPT_V2

    def get_first_message(self) -> str:
        """Ask which site - prompts user response so model gets a turn to call tools.

        In squad transfers, the model only gets a turn after user responds to firstMessage.
        We ask which site, then call get_signon_data as the first tool call.
        If sign-on data exists, it overrides whatever the user said.
        """
        return "Which site did you work at today? Or say admin if it was office work."

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
        """Model configuration for Jill (GPT-4o-mini for cost efficiency)"""
        return {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "temperature": 0.7,
            "maxTokens": 1200
        }

    def get_required_tool_names(self) -> List[str]:
        """Tools that Jill needs to function"""
        return [
            "authenticate_caller",                # From authentication skill
            "identify_site_for_timesheet",        # From timesheet skill
            "save_timesheet_entry",               # From timesheet skill
            "confirm_and_save_all",               # From timesheet skill
            "get_recent_timesheets",              # From timesheet skill - for history
            "check_date_for_conflicts",           # From timesheet skill - for historical dates
            "update_timesheet_entry"              # From timesheet skill - for updating entries
        ]
