# app/vapi_voice_notes.py - Generic Multi-Client VAPI System
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
    webhook_base_url: Optional[str] = None
    phone_number_id: Optional[str] = None
    
    class Config:
        env_prefix = "VAPI_"
        
    def __init__(self, **data):
        # Set default webhook_base_url if not provided
        if 'webhook_base_url' not in data or data['webhook_base_url'] is None:
            data['webhook_base_url'] = "https://journ3y-vapi-skills-service.up.railway.app"
        super().__init__(**data)

class VoiceNotesVAPISystem:
    def __init__(self, config: Optional[VAPIConfig] = None, webhook_base_url: Optional[str] = None):
        # Handle both old and new initialization patterns
        if config:
            self.api_key = config.api_key
            self.webhook_base = webhook_base_url or config.webhook_base_url or "https://journ3y-vapi-skills-service.up.railway.app"
        else:
            # Fallback to environment variables
            self.api_key = settings.VAPI_API_KEY
            self.webhook_base = webhook_base_url or settings.WEBHOOK_BASE_URL or "https://journ3y-vapi-skills-service.up.railway.app"
            
        self.base_url = "https://api.vapi.ai"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def create_auth_agent(self, tool_ids: Dict[str, str]) -> str:
        """Create the generic authentication and greeting agent"""
        logger.info("Creating generic authentication agent...")
        
        agent_config = {
            "name": "JSMB-Jill-authenticate-and-greet",
            "model": {
                "provider": "openai",
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "system",
                        "content": """You are Jill, a professional business assistant for construction companies.

                        Your job:
                        1. Answer with a warm greeting: "Hello! This is Jill. Let me verify your access..."
                        2. IMMEDIATELY call authenticate_caller with the caller's phone number and call ID
                        3. Based on the authentication response:
                        - If authorized: Greet them personally using their name from the response
                        - If they have multiple skills: Ask what they'd like to do based on available_skills
                        - If they have one skill: Directly transfer to that skill's agent
                        - If not authorized: Politely explain they're not authorized and suggest contacting their administrator

                        GREETING EXAMPLES:
                        - Multiple skills: "Hi [Name]! I can help you with [skill1] or [skill2]. What would you like to do today?"
                        - Single skill: "Hi [Name]! Ready to [skill_description]? Let me connect you right away."
                        - Not authorized: "I'm sorry, this number isn't authorized. Please contact your company administrator."

                        Keep it warm, professional, and efficient. Always use the person's name when available.

                        TRANSFER: Transfer to the appropriate skill agent based on user choice or single available skill."""
                    }
                ],
                "toolIds": [tool_ids["authenticate_caller"]]  # Use toolIds array instead of tools array
            },
            "voice": {
                "model": "eleven_turbo_v2_5",
                "voiceId": "MiueK1FXuZTCItgbQwPu",
                "provider": "11labs",
                "stability": 0.5,
                "similarityBoost": 0.75
            },
            "firstMessage": "Hello! This is Jill. Let me verify your access...",
            "firstMessageMode": "assistant-speaks-first"
        }

        logger.info(f"Creating assistant with payload: {json.dumps(agent_config, indent=2)}")
        
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

    async def create_voice_notes_agent(self, tool_ids: Dict[str, str]) -> str:
        """Create the generic voice notes recording agent"""
        logger.info("Creating generic voice notes agent...")
        
        agent_config = {
            "name": "JSMB-Jill-voice-notes",
            "model": {
                "provider": "openai",
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "system",
                        "content": """You are Jill, a professional voice notes assistant for construction companies.

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

                        Remember: You're helping capture important information quickly and accurately for any construction company."""
                    }
                ],
                "toolIds": [
                    tool_ids["identify_context"],
                    tool_ids["save_note"]
                ]  # Use toolIds array instead of tools array
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

        logger.info(f"Creating voice notes agent with payload: {json.dumps(agent_config, indent=2)}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/assistant",
                headers=self.headers,
                json=agent_config
            )
            
            logger.info(f"Voice notes agent creation response: {response.status_code}")
            logger.info(f"Voice notes agent creation response body: {response.text}")
            
            response.raise_for_status()
            result = response.json()
            return result["id"]

    async def create_voice_notes_squad(self, auth_agent_id: str, voice_notes_agent_id: str) -> str:
        """Create the generic voice notes squad with corrected structure"""
        logger.info("Creating squad...")
        
        # Fixed squad configuration - using assistant objects instead of assistantId
        squad_config = {
            "name": "JSMB-Jill-multi-skill-squad",
            "members": [
                {
                    "assistant": auth_agent_id,  # Use the ID directly, not in an object
                    "assistantDestinations": [
                        {
                            "type": "assistant",
                            "assistantName": "JSMB-Jill-voice-notes",
                            "message": "Perfect! Connecting you to voice notes..."
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
                    "name": "JSMB-Jill-multi-skill-squad",
                    "members": [
                        {
                            "assistantId": auth_agent_id,
                            "assistantDestinations": [
                                {
                                    "type": "assistant", 
                                    "assistantName": "JSMB-Jill-voice-notes",
                                    "message": "Perfect! Connecting you to voice notes..."
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
            # First create tools using VAPIToolsManager
            from app.vapi_tools_setup import VAPIToolsManager
            tools_manager = VAPIToolsManager()
            tool_ids = await tools_manager.setup_all_tools()
            
            # Create agents with tool IDs
            auth_agent_id = await self.create_auth_agent(tool_ids)
            voice_notes_agent_id = await self.create_voice_notes_agent(tool_ids)
            
            # Create squad
            squad_id = await self.create_voice_notes_squad(auth_agent_id, voice_notes_agent_id)
            
            return {
                "success": True,
                "auth_agent_id": auth_agent_id,
                "voice_notes_agent_id": voice_notes_agent_id,
                "squad_id": squad_id,
                "tool_ids": tool_ids,
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


def add_voice_notes_management_endpoints(app, voice_notes_system: Optional[VoiceNotesVAPISystem] = None):
    """Add VAPI voice notes management endpoints to FastAPI app"""
    
    async def get_system() -> VoiceNotesVAPISystem:
        """Get the voice notes system instance"""
        if voice_notes_system:
            return voice_notes_system
        else:
            return await get_vapi_system()
    
    @app.post("/api/v1/vapi/setup-voice-notes")
    async def setup_voice_notes():
        """Setup the complete VAPI voice notes system"""
        try:
            system = await get_system()
            result = await system.setup_voice_notes_system()
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
            
            system = await get_system()
            
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
            system = await get_system()
            
            # Check if we can access VAPI API
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{system.base_url}/assistant",
                    headers=system.headers
                )
                
                if response.status_code == 200:
                    assistants = response.json()
                    jsmb_assistants = [a for a in assistants if "JSMB-Jill" in a.get("name", "")]
                    
                    return {
                        "success": True,
                        "vapi_connected": True,
                        "jsmb_assistants": len(jsmb_assistants),
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
        """Clean up JSMB-Jill VAPI assistants (for testing)"""
        try:
            system = await get_system()
            
            async with httpx.AsyncClient() as client:
                # Get all assistants
                response = await client.get(
                    f"{system.base_url}/assistant",
                    headers=system.headers
                )
                
                if response.status_code == 200:
                    assistants = response.json()
                    jsmb_assistants = [a for a in assistants if "JSMB-Jill" in a.get("name", "") or "Built by MK" in a.get("name", "")]
                    
                    deleted_count = 0
                    for assistant in jsmb_assistants:
                        delete_response = await client.delete(
                            f"{system.base_url}/assistant/{assistant['id']}",
                            headers=system.headers
                        )
                        if delete_response.status_code == 200:
                            deleted_count += 1
                    
                    return {
                        "success": True,
                        "message": f"Deleted {deleted_count} JSMB-Jill assistants"
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Failed to fetch assistants: {response.status_code}"
                    }
                    
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            return {"success": False, "error": str(e)}