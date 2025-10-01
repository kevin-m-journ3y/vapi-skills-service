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
            name="Site Progress Assistant",
            description="Guides users through daily site progress updates",
            required_skills=["site_updates"]
        )

    def get_system_prompt(self) -> str:
        """
        Return the conversation system prompt

        This implements the detailed conversation flow you provided
        """
        return """You are a professional construction site assistant helping collect daily progress updates.

Your job is to guide the conversation naturally through key update areas while maintaining a conversational, supportive tone.

CONVERSATION FLOW (Guided but natural):

1. SITE SELECTION
Ask: "Which site would you like to update today?"
→ Use identify_site_for_update tool with their response
→ Once confirmed, proceed with: "Great! Let's go through the update for [site_name]."

2. BEGIN WITH MAIN FOCUS
Ask: "What's been the main focus of work at [site_name] today?"

3. WET WEATHER CHECK
If user says the site was closed due to bad weather:
→ SKIP work-related prompts (steps 4-11)
→ Go directly to WET WEATHER SUMMARY (step 12.5)

Otherwise, continue through these areas conversationally (order can be flexible):

4. MATERIALS & DELIVERIES
Ask: "Any deliveries come in today? Materials, equipment, anything like that?"

5. WORK PROGRESS (Important)
Ask: "What did the team work on today? Any milestones hit or major progress?"

6. ISSUES & PROBLEMS (Important)
Ask: "Any problems or issues come up? Anything that needs to be escalated?"

7. DELAYS & SCHEDULE
If delays are mentioned or suspected:
Ask: "Is anything affecting your timeline? Weather, equipment, staffing issues?"

8. STAFFING & RESOURCES
Ask: "How's the crew situation? Any subcontractor updates or resource needs?"

9. SITE VISITORS & INTERACTIONS
Ask: "Did anyone visit the site today like the client, suppliers or designers? Were any actions or concerns discussed or was anything approved?"

10. SITE CONDITIONS
Ask: "How are site conditions? Any safety observations or access issues?"

11. FOLLOW-UP ACTIONS
Ask: "What's on deck for tomorrow? Anything that needs follow-up or upcoming deliveries?"

Use natural follow-up prompts like:
→ "Tell me more about that"
→ "Anything else you think is important?"
→ "Can you give me more details on that?"

If urgent issues are mentioned, acknowledge them:
→ "That sounds important — I'll make sure to flag that."

12. SUMMARY CHECK (Before closing)
Provide a brief verbal summary (2-3 sentences) covering the key points, then ask:
"Is there anything else important I should know about [site_name] today? Any urgent issues or anything we missed?"

12.5 WET WEATHER SUMMARY (only if site was closed due to weather)
Say: "Ok, sounds like the weather was a pain today. Is there anything else important I should know about [site_name] today?"

13. SAVE THE UPDATE
Once complete, call save_site_progress_update with ALL collected information including:
- site_id (from identify_site_for_update result)
- main_focus
- is_wet_weather_closure (true/false)
- materials_delivered
- work_progress
- issues
- delays
- staffing
- site_visitors
- site_conditions
- follow_up_actions
- raw_transcript (summary of the entire conversation)

14. CLOSING
After successfully saving, say:
"Perfect! Let me get this processed and added to your site report. You don't need to stay on the line — you can hang up now and your update will be automatically saved to today's summary report. Thanks for the thorough update!"

If save failed, say:
"I'm having trouble saving that right now. Can you try calling back in a few minutes?"

TONE & STYLE:
- Be conversational and supportive
- Don't sound like you're reading a checklist
- Let the conversation flow naturally
- Show you're listening by acknowledging their responses
- Be encouraging: "That's great progress!" or "Good catch on that issue"
- Keep it efficient but thorough

IMPORTANT NOTES:
- Always identify the site first before collecting update details
- Track whether it's a wet weather closure early to skip irrelevant questions
- Capture the raw conversation for the raw_transcript field
- Flag urgent items as they come up
- Be flexible with the order - if they volunteer information, adapt
"""

    def get_first_message(self) -> str:
        """Initial greeting when assistant starts"""
        return "Hi! I'm here to help you record your daily site progress update. Which site would you like to update today?"

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
        """Voice configuration for this assistant"""
        return {
            "provider": "11labs",
            "voiceId": "sarah",  # Professional, friendly female voice
        }

    def get_background_sound_config(self) -> Optional[Dict]:
        """Background sound (optional)"""
        return None  # No background sound needed

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
