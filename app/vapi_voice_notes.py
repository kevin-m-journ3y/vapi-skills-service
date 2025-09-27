# app/vapi_voice_notes.py - Fixed VAPI Squad Creation
import httpx
import json
import logging
from typing import Dict, Any, Optional
from pydantic import BaseModel
import os
from app.config import settings

logger = logging.getLogger(__name__)

class VAPIConfig(BaseModel):
    """Configuration for VAPI voice notes system"""
    api_key: str
    webhook_base_url: str
    phone_number_id: Optional[str] = None
    
    class Config:
        env_prefix = "VAPI_"

class VoiceNotesVAPISystem:
    def __init__(self):
        self.api_key = settings.VAPI_API_KEY
        self.base_url = "https://api.vapi.ai"
        self.webhook_base = settings.WEBHOOK_BASE_URL or "https://journ3y-vapi-skills-service.up.railway.app"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def create_auth_agent(self) -> str:
        """Create the authentication agent"""
        logger.info("Creating authentication agent...")
        
        agent_config = {
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
                            "url": f"{self.webhook_base}/api/v1/vapi/authenticate-by-phone"
                        }
                    }
                ]
            },
            "voice": {
                "model": "eleven_turbo_v2_5",
                "voiceId": "MiueK1FXuZTCItgbQwPu",
                "provider": "11labs",
                "stability": 0.5,
                "similarityBoost": 0.75
            },
            "firstMessage": "Hello! This is Built by MK. Let me verify your access...",
            "firstMessageMode": "assistant-speaks-first"
        }

        logger.info(f"Creating assistant with payload: {agent_config}")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/assistant",
                headers=self.headers,
                json=agent_config
            )
            
            logger.info(f"Assistant creation response: {response.status_code}")
            logger.info(f"Assistant creation response body: {response.text}")
            
            response.raise_for_status()
            result = response.json()
            return result["id"]

    async def create_voice_notes_agent(self) -> str:
        """Create the voice notes recording agent"""
        logger.info("Creating voice notes agent...")
        
        agent_config = {
            "name": "Voice Notes Agent",
            "model": {
                "provider": "openai",
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "system",
                        "content": """You are Jill, the Built by MK voice notes assistant.

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

                    Remember: You're helping capture important information quickly and accurately."""
                    }
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "identify_context",
                            "description": "Identify if note is site-specific and which site",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "site_description": {
                                        "type": "string",
                                        "description": "Site description if mentioned (address, nickname, etc.)"
                                    },
                                    "vapi_call_id": {
                                        "type": "string",
                                        "description": "The VAPI call ID"
                                    }
                                },
                                "required": ["vapi_call_id"]
                            }
                        },
                        "server": {
                            "url": f"{self.webhook_base}/api/v1/skills/voice-notes/identify-context"
                        }
                    },
                    {
                        "type": "function",
                        "function": {
                            "name": "save_note",
                            "description": "Save the voice note with context",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "vapi_call_id": {
                                        "type": "string",
                                        "description": "The VAPI call ID"
                                    },
                                    "note_content": {
                                        "type": "string",
                                        "description": "The main content of the voice note"
                                    },
                                    "note_type": {
                                        "type": "string",
                                        "description": "Type of note: 'general' or 'site_specific'"
                                    },
                                    "site_id": {
                                        "type": "string",
                                        "description": "Site ID if this is site-specific (optional)"
                                    },
                                    "full_transcript": {
                                        "type": "string",
                                        "description": "Complete conversation transcript"
                                    }
                                },
                                "required": ["vapi_call_id", "note_content", "note_type", "full_transcript"]
                            }
                        },
                        "server": {
                            "url": f"{self.webhook_base}/api/v1/skills/voice-notes/save-note"
                        }
                    }
                ]
            },
            "voice": {
                "model": "eleven_turbo_v2_5",
                "voiceId": "MiueK1FXuZTCItgbQwPu",
                "provider": "11labs",
                "stability": 0.5,
                "similarityBoost": 0.75
            },
            "firstMessage": "Hi! I'm ready to record your voice note. What would you like to record?",
            "firstMessageMode": "assistant-speaks-first"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/assistant",
                headers=self.headers,
                json=agent_config
            )
            
            response.raise_for_status()
            result = response.json()
            return result["id"]

    async def create_voice_notes_squad(self, auth_agent_id: str, voice_notes_agent_id: str) -> str:
        """Create the voice notes squad with corrected structure"""
        logger.info("Creating squad...")
        
        # Fixed squad configuration - using assistant objects instead of assistantId
        squad_config = {
            "name": "Built by MK Voice Notes Squad",
            "members": [
                {
                    "assistant": auth_agent_id,  # Use the ID directly, not in an object
                    "assistantDestinations": [
                        {
                            "type": "assistant",
                            "assistantName": "Voice Notes Agent",
                            "message": "Perfect! Connecting you to our voice notes system..."
                        }
                    ]
                },
                {
                    "assistant": voice_notes_agent_id  # Use the ID directly
                }
            ]
        }

        logger.info(f"Creating squad with config: {squad_config}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/squad",
                headers=self.headers,
                json=squad_config
            )
            
            logger.info(f"Squad creation response: {response.status_code}")
            logger.info(f"Squad creation response body: {response.text}")
            
            if response.status_code == 400:
                # Try alternative structure if the first attempt fails
                logger.info("First squad structure failed, trying alternative...")
                
                alternative_config = {
                    "name": "Built by MK Voice Notes Squad",
                    "members": [
                        {
                            "assistantId": auth_agent_id,
                            "assistantDestinations": [
                                {
                                    "type": "assistant", 
                                    "assistantName": "Voice Notes Agent",
                                    "message": "Perfect! Connecting you to our voice notes system..."
                                }
                            ]
                        },
                        {
                            "assistantId": voice_notes_agent_id
                        }
                    ]
                }
                
                logger.info(f"Trying alternative config: {alternative_config}")
                
                response = await client.post(
                    f"{self.base_url}/squad",
                    headers=self.headers,
                    json=alternative_config
                )
                
                logger.info(f"Alternative squad response: {response.status_code}")
                logger.info(f"Alternative squad response body: {response.text}")
            
            response.raise_for_status()
            result = response.json()
            return result["id"]

    async def setup_voice_notes_system(self) -> Dict[str, Any]:
        """Set up the complete voice notes system"""
        try:
            # Create both agents
            auth_agent_id = await self.create_auth_agent()
            voice_notes_agent_id = await self.create_voice_notes_agent()
            
            # Create squad
            squad_id = await self.create_voice_notes_squad(auth_agent_id, voice_notes_agent_id)
            
            return {
                "success": True,
                "auth_agent_id": auth_agent_id,
                "voice_notes_agent_id": voice_notes_agent_id,
                "squad_id": squad_id,
                "message": "Voice notes system setup complete!"
            }
            
        except Exception as e:
            logger.error(f"Error setting up voice notes system: {e}")
            raise


async def setup_voice_notes_system() -> Dict[str, Any]:
    """Setup function for the voice notes system"""
    system = VoiceNotesVAPISystem()
    result = await system.setup_voice_notes_system()
    return result


# Store system instance for phone number attachment later
_vapi_system_instance = None

async def get_vapi_system() -> VoiceNotesVAPISystem:
    """Get or create VAPI system instance"""
    global _vapi_system_instance
    if _vapi_system_instance is None:
        _vapi_system_instance = VoiceNotesVAPISystem()
    return _vapi_system_instance


def add_voice_notes_management_endpoints(app):
    """Add VAPI voice notes management endpoints to FastAPI app"""
    
    @app.post("/api/v1/vapi/setup-voice-notes")
    async def setup_voice_notes():
        """Setup the complete VAPI voice notes system"""
        try:
            result = await setup_voice_notes_system()
            return result
        except Exception as e:
            logger.error(f"Setup failed: {e}")
            return {"success": False, "error": str(e)}

    @app.post("/api/v1/vapi/attach-phone")
    async def attach_phone_to_squad(request: dict):
        """Attach a phone number to the voice notes squad"""
        try:
            phone_number_id = request["phone_number_id"]
            squad_id = request["squad_id"]
            
            system = await get_vapi_system()
            
            # Attach phone number to squad
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    f"{system.base_url}/phone-number/{phone_number_id}",
                    headers=system.headers,
                    json={"assistantId": squad_id}
                )
                
                if response.status_code == 200:
                    return {
                        "success": True,
                        "message": f"Phone number {phone_number_id} attached to squad {squad_id}"
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Failed to attach phone: {response.status_code} - {response.text}"
                    }
                    
        except Exception as e:
            logger.error(f"Phone attachment failed: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/v1/vapi/status")
    async def get_vapi_status():
        """Get status of VAPI system components"""
        try:
            system = await get_vapi_system()
            
            # Check if we can access VAPI API
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{system.base_url}/assistant",
                    headers=system.headers
                )
                
                if response.status_code == 200:
                    assistants = response.json()
                    bmk_assistants = [a for a in assistants if "Built by MK" in a.get("name", "")]
                    
                    return {
                        "success": True,
                        "vapi_connected": True,
                        "bmk_assistants": len(bmk_assistants),
                        "total_assistants": len(assistants),
                        "webhook_base": system.webhook_base
                    }
                else:
                    return {
                        "success": False,
                        "vapi_connected": False,
                        "error": f"VAPI API error: {response.status_code}"
                    }
                    
        except Exception as e:
            logger.error(f"Status check failed: {e}")
            return {
                "success": False,
                "vapi_connected": False,
                "error": str(e)
            }

    @app.delete("/api/v1/vapi/cleanup")
    async def cleanup_vapi_assistants():
        """Clean up Built by MK VAPI assistants (for testing)"""
        try:
            system = await get_vapi_system()
            
            async with httpx.AsyncClient() as client:
                # Get all assistants
                response = await client.get(
                    f"{system.base_url}/assistant",
                    headers=system.headers
                )
                
                if response.status_code == 200:
                    assistants = response.json()
                    bmk_assistants = [a for a in assistants if "Built by MK" in a.get("name", "")]
                    
                    deleted_count = 0
                    for assistant in bmk_assistants:
                        delete_response = await client.delete(
                            f"{system.base_url}/assistant/{assistant['id']}",
                            headers=system.headers
                        )
                        if delete_response.status_code == 200:
                            deleted_count += 1
                    
                    return {
                        "success": True,
                        "message": f"Deleted {deleted_count} Built by MK assistants"
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Failed to fetch assistants: {response.status_code}"
                    }
                    
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            return {"success": False, "error": str(e)}