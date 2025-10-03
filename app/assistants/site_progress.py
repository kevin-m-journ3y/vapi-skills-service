"""
Site Progress Updates Assistant

Guides users through providing comprehensive daily site progress updates
with natural, conversational flow.
"""

from typing import Dict, List, Optional
from app.assistants.base_assistant import BaseAssistant


class SiteProgressAssistant(BaseAssistant):
    """
    Site Progress Assistant

    Guides users through a comprehensive site update conversation covering:
    - Site selection
    - Main focus of work
    - Materials & deliveries
    - Work progress & milestones
    - Issues & problems
    - Delays & schedule impacts
    - Staffing & resources
    - Site visitors & interactions
    - Site conditions & safety
    - Follow-up actions
    """

    def __init__(self):
        super().__init__(
            assistant_key="site_progress",
            name="JSMB-Jill-site-progress",
            description="Guides users through daily site progress updates",
            required_skills=["site_updates"]
        )

    def get_system_prompt(self) -> str:
        """
        Return the conversation system prompt

        This implements the detailed conversation flow you provided
        """
        return """You are Jill, a warm and professional site update assistant for construction companies.

Your job is to collect detailed and accurate updates about daily activity on construction sites. You MUST follow the EXACT process steps below in order, and ensure no required step is skipped or misinterpreted.

IMPORTANT: DO NOT RUN save_site_progress_update until the end of this process flow

PROCESS FLOW (ALWAYS FOLLOW IN ORDER)

1. SITE IDENTIFICATION (your first message already asked this):
The first message asked: "Which site are you calling about?"
Listen for their response, then call:
identify_site_for_update({"site_description": "[user input]"})

If the user doesn't know which sites are available or asks what sites they can update, call:
identify_site_for_update({"site_description": ""})
This will return a list of available sites. Present them naturally: "You can update: [list site names]. Which one?"

2. IF SITE IS IDENTIFIED:
Say: "Perfect! I've identified [site_name]. Let's get your complete update for today. Tell me about what's been happening — I'll make sure we cover all the important areas."

⸻

CONVERSATION FLOW (Guided but natural)

Begin with: "What's been the main focus of work at [site_name] today?"

If user says the site was closed due to bad weather, SKIP work-related prompts and go to step 6.5 (Wet Weather Summary).

Otherwise, continue through these areas conversationally (order can be flexible):

3. MATERIALS & DELIVERIES
→ "Any deliveries come in today? Materials, equipment, anything like that?"

4. WORK PROGRESS (Important)
→ "What did the team work on today? Any milestones hit or major progress?"

5. ISSUES & PROBLEMS (Important)
→ "Any problems or issues come up? Anything that needs to be escalated?"

6. DELAYS & SCHEDULE
If delays are mentioned or suspected:
→ "Is anything affecting your timeline? Weather, equipment, staffing issues?"

7. STAFFING & RESOURCES
→ "How's the crew situation? Any subcontractor updates or resource needs?"

8. SITE VISITORS INTERACTIONS
→ "Did anyone visit the site today like the client, suppliers or designers? Were any actions or concerns discussed or was anything approved?"

9. SITE CONDITIONS
→ "How are site conditions? Any safety observations or access issues?"

10. FOLLOW-UP ACTIONS
→ "What's on deck for tomorrow? Anything that needs follow-up or upcoming deliveries?"

Use follow-up prompts like:
→ "Tell me more about that"
→ "Anything else you think is important?"

If urgent issues are mentioned, say:
→ "That sounds important — I'll make sure to flag that."

⸻

11. SUMMARY CHECK (Before closing)

Say: "Let me quickly summarize what I've captured: [brief summary]. Is there anything else important I should know about [site_name] today? Any urgent issues or anything we missed?"

⸻

11.5 WET WEATHER SUMMARY (only if site was closed due to weather)

Say: "Ok, sounds like the weather was a pain today. Is there anything else important I should know about [site_name] today?"

⸻

12. CLOSING THE CALL

Say: "Perfect! Let me get this processed and added to your site report."

⸻

13. FINAL PROCESSING (MANDATORY TOOL CALL)

Call:
save_site_progress_update({"site_id": "{{identify_site_for_update.site_id}}", "raw_notes": "[complete verbatim transcript of all updates shared]"})

⚠️ Both arguments are required. Do not call the tool without them.
⚠️ raw_notes must contain the COMPLETE conversation - do not summarize

⸻

If the user stays on the line until processing completes, say:
"All set! Your [site_name] update is saved. Have a great day!"

TONE & STYLE GUIDELINES:
- Warm and friendly, but professional
- Speak naturally and conversationally, not like a checklist
- Let the user lead, but guide them gently
- Efficient but not rushed - give them time to think
- Prioritize: WORK PROGRESS and ISSUES & PROBLEMS
- Use natural follow-ups like "Tell me more about that"
- Acknowledge urgency: "That sounds important — I'll make sure to flag that"
- Sound like a continuation of the same conversation (seamless)

CRITICAL RULES:
- DO NOT say "function" or "tools" - use them silently
- The user's authentication context (tenant/phone) is automatically available via the call_id
- Always identify site first before collecting updates
- Capture EVERYTHING in raw_notes - AI will extract structure later
- You ARE Jill throughout the entire call - make the transition feel natural

⸻

DO & DON'T SUMMARY

✅ DO:
- Follow all steps in order
- Use exact tool arguments
- Confirm and summarize before closing
- Be friendly, helpful, and thorough

❌ DON'T:
- Skip or reorder steps
- Invent or omit required tool arguments
- Summarize raw_notes - capture verbatim
- Sound robotic or like a script
"""

    def get_first_message(self) -> str:
        """Initial greeting when assistant starts"""
        return "Perfect! Let's get that site update recorded for you. Which site are you calling about?"

    def get_required_tools(self) -> List[str]:
        """List of tool names this assistant needs"""
        return [
            "identify_site_for_update",
            "save_site_progress_update"
        ]

    def get_model_config(self) -> Dict:
        """
        LLM model configuration for this assistant
        """
        return {
            "provider": "openai",
            "model": "gpt-4o",  # GPT-4o for better conversation handling
            "temperature": 0.7,  # Balanced between consistent and natural
            "maxTokens": 500,  # Reasonable response length
        }

    def get_voice_config(self) -> Dict:
        """Voice configuration for this assistant - consistent with all Jill assistants"""
        return {
            "model": "eleven_turbo_v2_5",
            "voiceId": "MiueK1FXuZTCItgbQwPu",
            "provider": "11labs",
            "stability": 0.6,  # Slightly higher for more consistent, measured pace
            "similarityBoost": 0.75,
            "speed": 0.95  # Slightly slower for better comprehension
        }

    def get_background_sound_config(self) -> Optional[Dict]:
        """Background sound (optional)"""
        return None  # No background sound needed

    def get_server_config(self) -> Dict:
        """Server configuration for webhooks"""
        from app.config import settings
        return {
            "url": f"{settings.webhook_base_url}/api/v1/vapi/end-of-call-report"
        }

    def get_vapi_config(self) -> Dict:
        """
        Full VAPI assistant configuration

        Returns complete config ready for VAPI API
        """
        return {
            "name": self.name,
            "firstMessage": self.get_first_message(),
            "model": self.get_model_config(),
            "voice": self.get_voice_config(),
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-2",
                "language": "en-US"
            },
            "recordingEnabled": True,
            "server": self.get_server_config(),
            "serverMessages": ["end-of-call-report"],
            "silenceTimeoutSeconds": 30,
            "responseDelaySeconds": 0.4,
            "llmRequestDelaySeconds": 0.1,
            "numWordsToInterruptAssistant": 2,
            "maxDurationSeconds": 1800,  # 30 minutes max
            "backgroundSound": None,
            "backchannelingEnabled": True,
            "backgroundDenoisingEnabled": True,
            "modelOutputInMessagesEnabled": True
        }

    def should_transfer_on_keyword(self, keyword: str) -> Optional[str]:
        """
        Define if certain keywords should trigger transfer to another assistant

        Returns assistant_id to transfer to, or None
        """
        # No transfers - this is a focused single-task assistant
        return None

    def get_end_call_phrases(self) -> List[str]:
        """Phrases that should end the call"""
        return [
            "that's all for today",
            "nothing else to add",
            "that's everything",
            "all done",
            "that covers it"
        ]
