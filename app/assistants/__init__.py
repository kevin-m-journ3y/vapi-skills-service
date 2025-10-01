"""VAPI Assistants

This module contains assistant definitions that orchestrate skills.
Assistants define personality, voice, conversation flow, and which tools/skills to use.
"""

from .base_assistant import BaseAssistant
from .greeter import GreeterAssistant
from .jill_voice_notes import JillVoiceNotesAssistant
from .site_progress import SiteProgressAssistant

__all__ = ['BaseAssistant', 'GreeterAssistant', 'JillVoiceNotesAssistant', 'SiteProgressAssistant']
