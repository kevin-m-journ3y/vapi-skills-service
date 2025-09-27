# app/vapi_voice_notes.py - Focused Voice Notes Implementation
"""
Two-agent VAPI system for Built by MK voice notes:
1. Authentication Agent - validates caller
2. Voice Notes Agent - records notes (general or site-specific)
"""

import os
import httpx
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class VAPIConfig:
    api_key: str
    base_url: str = "https://api.vapi.ai"
    phone_number_id: Optional[str] = None

class VoiceNotesVAPISystem:
    """
    Simplified VAPI system focused on voice notes functionality.
    """
    
    def __init__(self, vapi_config: VAPIConfig, webhook_base_url: str):
        self.vapi_config = vapi_config
        self.webhook_base_url = webhook_base_url
        self.client = httpx.AsyncClient(
            base_url=vapi_config.base_url,
            headers={
                "Authorization": f"Bearer {vapi_config.api_key}",
                "Content-Type": "application/json"
            },
            timeout=30.0
        )
        
        # Consistent voice configuration
        self.voice_config = {
            "model": "eleven_turbo_v2_5",
            "voiceId": "MiueK1FXuZTCItgbQwPu",
            "provider": "11labs",
            "stability": 0.5,
            "similarityBoost": 0.75
        }

    async def create_authentication_agent(self) -> Dict[str, Any]:
        """
        Creates the authentication agent that validates callers and seamlessly 
        transitions to voice notes.
        """
        assistant_payload = {
            "name": "Built by MK Auth",
            "model": {
                "provider": "openai",
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "system",
                        "content": """You are the Built by MK authentication assistant.

Your job:
1. Answer with a warm greeting: "Hello! This is Built by MK. Let me verify your access..."
2. IMMEDIATELY call authenticate_caller with the caller's phone number
3. Based on the response:
   - If authorized for voice_notes: Say "Perfect! I can see you're authorized to record voice notes. Let me connect you to our voice notes system right away." Then transfer to "Voice Notes Agent"
   - If not authorized: Say "I'm sorry, this number isn't authorized for voice notes. Please contact Built by MK administration."

Keep it brief, warm, and professional. Make the transition feel seamless.

TRANSFER: Always transfer to "Voice Notes Agent" for authorized voice_notes users."""
                    }
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "authenticate_caller",
                            "description": "Authenticate caller by phone number",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "caller_phone": {
                                        "type": "string",
                                        "description": "The caller's phone number"
                                    },
                                    "vapi_call_id": {
                                        "type": "string", 
                                        "description": "The VAPI call ID"
                                    }
                                },
                                "required": ["caller_phone", "vapi_call_id"]
                            }
                        },
                        "server": {
                            "url": f"{self.webhook_base_url}/api/v1/vapi/authenticate-by-phone"
                        }
                    }
                ]
            },
            "voice": self.voice_config,
            "firstMessage": "Hello! This is Built by MK. Let me verify your access...",
            "firstMessageMode": "assistant-speaks-first"
        }
        
        response = await self.client.post("/assistant", json=assistant_payload)
        response.raise_for_status()
        return response.json()

    async def create_voice_notes_agent(self) -> Dict[str, Any]:
        """
        Creates the voice notes agent that handles both general and site-specific notes.
        """
        assistant_payload = {
            "name": "Voice Notes Agent",
            "model": {
                "provider": "openai",
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "system",
                        "content": """You are the Built by MK voice notes assistant. You help users record voice notes.

Your process:
1. Greet warmly: "Hi! I'm ready to help you record a voice note. Is this a general company note, or is it about a specific construction site?"

2. Listen for their response:
   - If GENERAL: Say "Perfect! Go ahead and tell me what you'd like to record as a general note."
   - If SITE-SPECIFIC: Say "Great! Which construction site is this note about?" Then call identify_context with site_specific type.

3. For GENERAL notes:
   - Let them speak naturally about their note
   - When they're done, call save_voice_note with note_type "general"

4. For SITE-SPECIFIC notes:
   - First identify the site using identify_context
   - If site found: "Perfect! I've identified [site name]. Now tell me what you'd like to record about this site."
   - If site not found: "I couldn't identify that site. Available sites are: [list]. Which one did you mean, or would you prefer to record this as a general note instead?"
   - Then let them speak and call save_voice_note with the site_id

5. Always confirm: "I've recorded your note successfully. Is there anything else you'd like to add?"

Be natural, conversational, and helpful. Let them speak without interruption.
"""
                    }
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "identify_context",
                            "description": "Identify context for voice notes",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "note_type": {
                                        "type": "string",
                                        "enum": ["general", "site_specific"],
                                        "description": "Type of note"
                                    },
                                    "site_description": {
                                        "type": "string",
                                        "description": "Site description if site-specific"
                                    },
                                    "vapi_call_id": {
                                        "type": "string",
                                        "description": "VAPI call ID"
                                    }
                                },
                                "required": ["note_type", "vapi_call_id"]
                            }
                        },
                        "server": {
                            "url": f"{self.webhook_base_url}/api/v1/skills/voice-notes/identify-context"
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "save_voice_note",
                            "description": "Save the voice note",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "vapi_call_id": {"type": "string"},
                                    "site_id": {"type": "string", "description": "Site ID for site-specific notes, null for general"},
                                    "note_content": {"type": "string", "description": "The actual note content"},
                                    "note_summary": {"type": "string", "description": "Brief summary of the note"},
                                    "note_type": {"type": "string", "enum": ["general", "site_specific"]},
                                    "full_transcript": {"type": "string", "description": "Complete conversation transcript"}
                                },
                                "required": ["vapi_call_id", "note_content", "note_type", "full_transcript"]
                            }
                        },
                        "server": {
                            "url": f"{self.webhook_base_url}/api/v1/skills/voice-notes/save-note"
                        }
                    }
                ]
            },
            "voice": self.voice_config,
            "firstMessage": "Hi! I'm ready to help you record a voice note. Is this a general company note, or is it about a specific construction site?",
            "firstMessageMode": "assistant-speaks-first"
        }
        
        response = await self.client.post("/assistant", json=assistant_payload)
        response.raise_for_status()
        return response.json()

    async def create_voice_notes_squad(self, auth_agent_id: str, voice_notes_agent_id: str) -> Dict[str, Any]:
        """
        Creates a squad with seamless authentication to voice notes transition.
        """
        squad_config = {
            "name": "Built by MK Voice Notes Squad",
            "members": [
                {
                    "assistant": {
                        "assistantId": auth_agent_id
                    },
                    "assistantDestinations": [
                        {
                            "type": "assistant",
                            "assistantName": "Voice Notes Agent",
                            "message": "Perfect! Connecting you to our voice notes system..."
                        }
                    ]
                },
                {
                    "assistant": {
                        "assistantId": voice_notes_agent_id
                    }
                }
            ]
        }
        
        response = await self.client.post("/squad", json=squad_config)
        response.raise_for_status()
        return response.json()

    async def attach_phone_number(self, squad_id: str, phone_number_id: str) -> Dict[str, Any]:
        """
        Attach phone number to the squad.
        """
        phone_config = {
            "squadId": squad_id,
            "assistantId": None
        }
        
        response = await self.client.patch(f"/phone-number/{phone_number_id}", json=phone_config)
        response.raise_for_status()
        return response.json()

    async def setup_voice_notes_system(self) -> Dict[str, Any]:
        """
        Complete setup for the voice notes system.
        """
        try:
            logger.info("Creating authentication agent...")
            auth_agent = await self.create_authentication_agent()
            auth_agent_id = auth_agent["id"]
            
            logger.info("Creating voice notes agent...")
            voice_notes_agent = await self.create_voice_notes_agent()
            voice_notes_agent_id = voice_notes_agent["id"]
            
            logger.info("Creating squad...")
            squad = await self.create_voice_notes_squad(auth_agent_id, voice_notes_agent_id)
            squad_id = squad["id"]
            
            # Attach phone number if provided
            phone_setup = None
            if self.vapi_config.phone_number_id:
                logger.info(f"Attaching phone number {self.vapi_config.phone_number_id}...")
                phone_setup = await self.attach_phone_number(squad_id, self.vapi_config.phone_number_id)
            
            return {
                "status": "success",
                "system": "voice_notes",
                "squad_id": squad_id,
                "auth_agent_id": auth_agent_id,
                "voice_notes_agent_id": voice_notes_agent_id,
                "phone_number_id": self.vapi_config.phone_number_id,
                "phone_setup": phone_setup,
                "webhook_base_url": self.webhook_base_url,
                "voice_config": self.voice_config
            }
            
        except Exception as e:
            logger.error(f"Error setting up voice notes system: {e}")
            raise

    async def test_outbound_call(self, phone_number_to_call: str, squad_id: str) -> Dict[str, Any]:
        """
        Test the system with an outbound call.
        """
        call_config = {
            "assistantId": None,
            "squadId": squad_id,
            "phoneNumberId": self.vapi_config.phone_number_id,
            "customer": {
                "number": phone_number_to_call
            }
        }
        
        response = await self.client.post("/call/phone", json=call_config)
        response.raise_for_status()
        return response.json()

    async def get_recent_calls(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent calls for monitoring.
        """
        response = await self.client.get(f"/call?limit={limit}")
        response.raise_for_status()
        return response.json()

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()


# Setup function
async def setup_voice_notes_system():
    """
    Setup the complete voice notes system.
    """
    vapi_config = VAPIConfig(
        api_key=os.getenv("VAPI_API_KEY"),
        phone_number_id=os.getenv("VAPI_PHONE_NUMBER_ID")
    )
    
    webhook_base_url = os.getenv("WEBHOOK_BASE_URL", "https://journ3y-vapi-skills-service.up.railway.app")
    
    if not vapi_config.api_key:
        raise ValueError("VAPI_API_KEY environment variable is required")
    
    system = VoiceNotesVAPISystem(vapi_config, webhook_base_url)
    
    try:
        result = await system.setup_voice_notes_system()
        
        logger.info("Voice Notes System Setup Complete!")
        logger.info(f"Squad ID: {result['squad_id']}")
        logger.info(f"Auth Agent ID: {result['auth_agent_id']}")
        logger.info(f"Voice Notes Agent ID: {result['voice_notes_agent_id']}")
        logger.info(f"Voice Config: {result['voice_config']}")
        
        return result
        
    finally:
        await system.close()


# FastAPI integration
def add_voice_notes_management_endpoints(app, voice_notes_system: VoiceNotesVAPISystem):
    """
    Add management endpoints for the voice notes system.
    """
    
    @app.post("/api/v1/vapi/setup-voice-notes")
    async def setup_voice_notes():
        """Setup the voice notes system."""
        return await setup_voice_notes_system()
    
    @app.post("/api/v1/vapi/test-voice-notes-call")
    async def test_voice_notes_call(phone_number: str, squad_id: str):
        """Test voice notes with outbound call."""
        return await voice_notes_system.test_outbound_call(phone_number, squad_id)
    
    @app.get("/api/v1/vapi/voice-notes-calls")
    async def get_voice_notes_calls(limit: int = 10):
        """Get recent voice notes calls."""
        return await voice_notes_system.get_recent_calls(limit)


if __name__ == "__main__":
    import asyncio
    asyncio.run(setup_voice_notes_system())