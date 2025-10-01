# app/main.py - Complete FastAPI application with VAPI endpoints

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import httpx
import os
from datetime import datetime
from dotenv import load_dotenv
import uuid
from datetime import datetime, date
import logging
import json
from app.vapi_voice_notes import VoiceNotesVAPISystem, add_voice_notes_management_endpoints, VAPIConfig
from app.vapi_tools_setup import VAPIToolsManager
from app.vapi_utils import vapi_tool, extract_vapi_args
from app.vapi_site_progress_setup import add_site_progress_management_endpoints

# NEW: Import skill-based architecture
from app.skills import skill_registry
from app.skills.voice_notes import VoiceNotesSkill
from app.skills.authentication import AuthenticationSkill
from app.skills.site_updates import SiteUpdatesSkill
from app.assistants import GreeterAssistant, JillVoiceNotesAssistant, SiteProgressAssistant

# Load environment variables from .env file
load_dotenv()

# Set up logging early
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Multi-Tenant Document RAG + VAPI Skills System", version="1.0.0")

# ============================================
# NEW SKILL-BASED ARCHITECTURE
# ============================================

# Register skills and assistants with the registry
if os.getenv("VAPI_API_KEY"):
    logger.info("Initializing skill-based architecture...")

    # Register Skills
    authentication_skill = AuthenticationSkill()
    skill_registry.register_skill(authentication_skill)

    voice_notes_skill = VoiceNotesSkill()
    skill_registry.register_skill(voice_notes_skill)

    site_updates_skill = SiteUpdatesSkill()
    skill_registry.register_skill(site_updates_skill)

    # Register Assistants
    greeter_assistant = GreeterAssistant()
    skill_registry.register_assistant(greeter_assistant)

    jill_assistant = JillVoiceNotesAssistant()
    skill_registry.register_assistant(jill_assistant)

    site_progress_assistant = SiteProgressAssistant()
    skill_registry.register_assistant(site_progress_assistant)

    # Register all skill routes with the app
    skill_registry.register_all_routes(app)

    logger.info(f"Registered {len(skill_registry.skills)} skills and "
               f"{len(skill_registry.assistants)} assistants")

# ============================================
# LEGACY VAPI SYSTEM (DEPRECATED - for backward compatibility)
# ============================================

if os.getenv("VAPI_API_KEY"):
    vapi_config = VAPIConfig(
        api_key=os.getenv("VAPI_API_KEY"),
        phone_number_id=os.getenv("VAPI_PHONE_NUMBER_ID")
    )
    voice_notes_system = VoiceNotesVAPISystem(
        vapi_config,
        os.getenv("WEBHOOK_BASE_URL", "https://journ3y-vapi-skills-service.up.railway.app")
    )
    add_voice_notes_management_endpoints(app, voice_notes_system)
    add_site_progress_management_endpoints(app)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# MODELS
# ============================================


class SiteValidationRequest(BaseModel):
    site_description: str
    vapi_call_id: str

class SiteUpdateStoreRequest(BaseModel):
    vapi_call_id: str
    site_id: str
    full_transcript: str
    orders_delivered: Optional[str] = None
    order_issues: Optional[str] = None
    progress_issues: Optional[str] = None
    general_updates: Optional[str] = None
    summary_text: Optional[str] = None


class VapiAuthRequest(BaseModel):
    caller_phone: str
    called_phone: Optional[str] = None
    vapi_call_id: Optional[str] = None
    intent: Optional[str] = None

class SkillInfo(BaseModel):
    skill_key: str
    skill_name: str
    vapi_assistant_id: Optional[str]
    requires_entities: bool
    entity_type: Optional[str]

class EntityInfo(BaseModel):
    id: str
    name: str
    identifier: Optional[str]
    address: Optional[str]

class UnifiedAuthResponse(BaseModel):
    authorized: bool
    session_type: Optional[str] = None  # 'internal_user' or 'external_customer'
    
    # User information (for internal users)
    user_name: Optional[str] = None
    user_role: Optional[str] = None
    
    # Customer information (for external customers)
    customer_id: Optional[str] = None
    is_returning_customer: bool = False
    called_number_name: Optional[str] = None
    
    # Available skills and routing
    available_skills: List[SkillInfo] = []
    single_skill_mode: bool = False
    greeting_message: str = ""
    next_assistant_id: Optional[str] = None
    
    # Available entities (if skill requires them)
    available_entities: List[EntityInfo] = []
    
    # Error information
    error: Optional[str] = None

class SkillSessionRequest(BaseModel):
    vapi_call_id: str
    skill_key: str
    caller_phone: str
    called_phone: Optional[str] = None
    entity_id: Optional[str] = None
    session_data: Optional[Dict] = {}

class VapiLogRequest(BaseModel):
    vapi_call_id: str
    skill_key: str
    caller_phone: str
    called_phone: Optional[str] = None
    session_type: str  # 'internal_user' or 'external_customer'
    status: str = 'completed'
    duration_seconds: Optional[int] = None
    raw_log_data: Dict = {}

class PhoneAuthRequest(BaseModel):
    caller_phone: str
    vapi_call_id: str

class PhoneAuthResponse(BaseModel):
    authorized: bool
    session_type: Optional[str] = None
    user_name: Optional[str] = None
    user_first_name: Optional[str] = None
    user_role: Optional[str] = None
    company_name: Optional[str] = None
    available_skills: List[SkillInfo] = []
    primary_skill: Optional[SkillInfo] = None
    single_skill_mode: bool = False
    greeting_message: str = ""
    next_assistant_id: Optional[str] = None
    session_context: Dict[str, Any] = {}
    message: Optional[str] = None

class VoiceNoteContextRequest(BaseModel):
    note_type: str  # 'general' or 'site_specific'
    site_description: Optional[str] = None
    vapi_call_id: str

class VoiceNoteSaveRequest(BaseModel):
    vapi_call_id: str
    site_id: Optional[str] = None
    note_content: str
    note_summary: Optional[str] = None
    note_type: str
    full_transcript: str

# ============================================
# System initialsation
# ============================================

# Initialize VAPI system
#vapi_system = VoiceNotesVAPISystem()
#tools_manager = VAPIToolsManager()

@app.post("/api/v1/vapi/setup-voice-notes-system")
async def setup_voice_notes_system():
    """
    Complete setup of the VAPI voice notes system including tools, assistants, and squad
    """
    try:
        if not os.getenv("VAPI_API_KEY"):
            return {"success": False, "error": "VAPI_API_KEY not configured"}
        
        # Create new instance for setup
        from app.vapi_voice_notes import VoiceNotesVAPISystem
        system = VoiceNotesVAPISystem()
        
        system_info = await system.setup_voice_notes_system()
        return {
            "success": True,
            "message": "Voice notes system setup complete",
            "system_info": system_info
        }
    except Exception as e:
        logger.error(f"Failed to set up voice notes system: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/api/v1/vapi/system-status")
async def get_system_status():
    """
    Get current status of the VAPI voice notes system
    """
    try:
        if not os.getenv("VAPI_API_KEY"):
            return {"success": False, "error": "VAPI_API_KEY not configured"}
        
        from app.vapi_voice_notes import VoiceNotesVAPISystem
        system = VoiceNotesVAPISystem()
        
        status = await system.get_system_status()
        return {
            "success": True,
            "status": status
        }
    except Exception as e:
        logger.error(f"Failed to get system status: {e}")
        return {
            "success": False,
            "error": str(e)
        }
    
@app.post("/api/v1/vapi/end-of-call-report")
async def handle_end_of_call_report(request: dict):
    """
    Handle end-of-call report from VAPI with full transcript
    This stores the complete call transcript in the database
    """
    try:
        logger.info(f"Received end-of-call report: {json.dumps(request, indent=2)}")

        # Extract call data
        call = request.get("message", {})
        call_id = call.get("id")
        transcript_data = call.get("transcript")
        messages = call.get("messages", [])

        if not call_id:
            logger.error("No call ID in end-of-call report")
            return {"success": False, "error": "Missing call ID"}

        # Build full transcript from messages
        full_transcript = ""
        if messages:
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "") or msg.get("message", "")
                if content:
                    if role == "user":
                        full_transcript += f"User: {content}\n"
                    elif role == "assistant":
                        full_transcript += f"Assistant: {content}\n"

        # Store transcript in vapi_logs
        async with httpx.AsyncClient() as client:
            # Update the existing vapi_log entry with transcript
            response = await client.patch(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/vapi_logs",
                headers={
                    "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                params={"vapi_call_id": f"eq.{call_id}"},
                json={
                    "transcript": full_transcript,
                    "call_duration": call.get("duration"),
                    "call_ended_at": call.get("endedAt"),
                    "raw_log_data": request  # Store full payload for reference
                }
            )

            if response.status_code in [200, 204]:
                logger.info(f"Stored transcript for call {call_id}")

                # Update any site_progress_updates with the real transcript
                update_response = await client.patch(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/site_progress_updates",
                    headers={
                        "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal"
                    },
                    params={"vapi_call_id": f"eq.{call_id}"},
                    json={"raw_transcript": full_transcript}
                )

                if update_response.status_code in [200, 204]:
                    logger.info(f"Updated site_progress_updates with real transcript for call {call_id}")

                # Also update voice_notes with real transcript
                notes_response = await client.patch(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/voice_notes",
                    headers={
                        "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal"
                    },
                    params={"vapi_call_id": f"eq.{call_id}"},
                    json={"full_transcript": full_transcript}
                )

                if notes_response.status_code in [200, 204]:
                    logger.info(f"Updated voice_notes with real transcript for call {call_id}")

                return {"success": True}
            else:
                logger.error(f"Failed to store transcript: {response.status_code} - {response.text}")
                return {"success": False, "error": "Failed to store transcript"}

    except Exception as e:
        logger.error(f"Error handling end-of-call report: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/v1/vapi/setup-tools-only")
async def setup_tools_only():
    """
    Set up only the VAPI tools (useful for testing)
    """
    try:
        if not os.getenv("VAPI_API_KEY"):
            return {"success": False, "error": "VAPI_API_KEY not configured"}
        
        # Create local instance instead of using global
        from app.vapi_tools_setup import VAPIToolsManager
        tools_manager = VAPIToolsManager()
        
        tool_ids = await tools_manager.setup_all_tools()
        return {
            "success": True,
            "message": "Tools setup complete",
            "tool_ids": tool_ids
        }
    except Exception as e:
        logger.error(f"Failed to set up tools: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.delete("/api/v1/vapi/cleanup-tools")
async def cleanup_tools():
    """
    Clean up VAPI tools (useful for testing/reset)
    """
    try:
        if not os.getenv("VAPI_API_KEY"):
            return {"success": False, "error": "VAPI_API_KEY not configured"}
        
        # Create local instance
        from app.vapi_tools_setup import VAPIToolsManager
        tools_manager = VAPIToolsManager()
        
        existing_tools = await tools_manager.get_existing_tools()
        deleted_count = 0
        
        for tool_name, tool_id in existing_tools.items():
            if tool_name in ['authenticate_caller', 'identify_context', 'save_note']:
                success = await tools_manager.delete_tool(tool_id)
                if success:
                    deleted_count += 1
        
        return {
            "success": True,
            "message": f"Deleted {deleted_count} tools",
            "deleted_tools": list(existing_tools.keys())
        }
    except Exception as e:
        logger.error(f"Failed to cleanup tools: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# ============================================
# SKILL REGISTRY ENDPOINTS
# ============================================

@app.get("/api/v1/skills/list")
async def list_skills():
    """List all registered skills and their status"""
    return {
        "success": True,
        "skills": skill_registry.list_skills(),
        "total": len(skill_registry.skills)
    }

@app.post("/api/v1/skills/setup-all")
async def setup_all_skills():
    """Set up all registered skills (create tools and assistants)"""
    results = await skill_registry.setup_all_skills()
    return {
        "success": True,
        "results": results
    }

@app.post("/api/v1/skills/{skill_key}/setup")
async def setup_skill(skill_key: str):
    """Set up a specific skill"""
    result = await skill_registry.setup_skill(skill_key)
    return result

# ============================================
# ENVIRONMENT CHECK ENDPOINT
# ============================================

@app.get("/debug/env-check")
async def check_environment():
    """Check if environment variables are properly set"""
    from app.config import settings
    return {
        "supabase_url": (os.getenv('SUPABASE_URL')[:50] + "...") if os.getenv('SUPABASE_URL') else "NOT SET",
        "supabase_service_key": "SET" if os.getenv('SUPABASE_SERVICE_KEY') else "NOT SET",
        "openai_api_key": "SET" if os.getenv('OPENAI_API_KEY') else "NOT SET",
        "google_service_account": "SET" if os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON') else "NOT SET",
        "vapi_api_key": "SET" if os.getenv('VAPI_API_KEY') else "NOT SET",
        "webhook_base_url": settings.webhook_base_url,
        "environment": settings.ENVIRONMENT,
        "python_path": os.getcwd()
    }

# ============================================
# BASIC HEALTH ENDPOINTS
# ============================================

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "vapi-skills-dispatcher"}

@app.get("/")
async def root():
    return {"message": "Multi-Tenant Document RAG + VAPI Skills System", "version": "1.0.0"}

# ============================================
# TENANT AUTHENTICATION DEPENDENCY
# ============================================

async def get_tenant_from_api_key(authorization: str = Header(None)) -> str:
    """Extract tenant ID from Bearer token with proper error handling"""
    
    # Check authorization header
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    
    api_key = authorization.replace("Bearer ", "")
    
    # Check environment variables
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_service_key = os.getenv('SUPABASE_SERVICE_KEY')
    
    if not supabase_url:
        raise HTTPException(status_code=500, detail="SUPABASE_URL environment variable not set")
    
    if not supabase_service_key:
        raise HTTPException(status_code=500, detail="SUPABASE_SERVICE_KEY environment variable not set")
    
    try:
        # Use your existing Supabase client
        async with httpx.AsyncClient() as client:
            # Set tenant context using the API key
            response = await client.post(
                f"{supabase_url}/rest/v1/rpc/authenticate_tenant_by_api_key",
                headers={
                    "apikey": supabase_service_key,
                    "Authorization": f"Bearer {supabase_service_key}",
                    "Content-Type": "application/json"
                },
                json={"api_key_input": api_key}
            )
            
            if response.status_code != 200:
                print(f"Supabase error: {response.status_code} - {response.text}")
                raise HTTPException(status_code=401, detail="Invalid API key")
            
            tenant_id = response.json()
            if not tenant_id:
                raise HTTPException(status_code=401, detail="Invalid API key")
            
            return str(tenant_id)
    
    except httpx.RequestError as e:
        print(f"Request error: {e}")
        raise HTTPException(status_code=500, detail="Database connection error")
    except Exception as e:
        print(f"Authentication error: {e}")
        raise HTTPException(status_code=500, detail="Authentication system error")

# ============================================
# VAPI AUTHENTICATION ENDPOINT
# ============================================

@app.post("/api/v1/vapi/authenticate", response_model=UnifiedAuthResponse)
async def authenticate_vapi_caller(
    request: VapiAuthRequest,
    tenant_id: str = Depends(get_tenant_from_api_key)
):
    """
    Unified VAPI authentication endpoint
    Handles both internal users (employees) and external customers
    """
    
    try:
        # Call the simplified authentication function that accepts tenant_id directly
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/authenticate_caller_with_tenant",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json"
                },
                json={
                    "caller_phone": request.caller_phone,
                    "tenant_uuid": tenant_id,
                    "called_phone": request.called_phone
                }
            )
            
            if response.status_code != 200:
                return UnifiedAuthResponse(
                    authorized=False,
                    error=f"Authentication system error: {response.text}",
                    greeting_message="I'm experiencing technical difficulties. Please try again later."
                )
            
            auth_result = response.json()
            
            if not auth_result.get("authorized", False):
                return UnifiedAuthResponse(
                    authorized=False,
                    error=auth_result.get("error", "Caller not authorized"),
                    greeting_message="I'm sorry, but I can't assist with this call. Please contact support if you believe this is an error."
                )
            
            # Route based on session type
            if auth_result["session_type"] == "internal_user":
                return await handle_internal_user_auth(auth_result, request.intent)
            elif auth_result["session_type"] == "external_customer":
                return await handle_external_customer_auth(auth_result, request.intent)
            
            return UnifiedAuthResponse(
                authorized=False,
                error="Unknown session type"
            )
            
    except Exception as e:
        print(f"VAPI authentication error: {e}")
        return UnifiedAuthResponse(
            authorized=False,
            error=f"System error: {str(e)}",
            greeting_message="I'm experiencing technical difficulties. Please try again later."
        )
    

# ============================================
# ADD PHONE-ONLY AUTHENTICATION ENDPOINT
# ============================================

# The issue might be that VAPI Server Tools expect a different response format
# than OpenAI Function Tools. Let me try the Server Tool format:

@app.post("/api/v1/vapi/authenticate-by-phone")
async def authenticate_by_phone(request: dict):
    """Authenticate caller - VAPI Server Tool format"""
    
    # Extract call ID from VAPI request structure
    vapi_call_id = None
    if "message" in request and "call" in request["message"]:
        vapi_call_id = request["message"]["call"]["id"]
    
    tool_call_id, args = extract_vapi_args(request)
    
    try:
        # Extract arguments with fallbacks
        caller_phone = args.get("caller_phone")
        
        if not vapi_call_id:
            vapi_call_id = args.get("vapi_call_id", "unknown")
        
        # TEST MODE fallback
        if not caller_phone or caller_phone.strip() == "":
            caller_phone = "+61412345678"
            logger.info(f"No phone provided, defaulting to test number: {caller_phone}")
        
        logger.info(f"Authenticating phone: {caller_phone}, call: {vapi_call_id}, toolCallId: {tool_call_id}")
        
        # Your existing authentication logic...
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "phone_number": f"eq.{caller_phone}",
                    "is_active": "eq.true",
                    "select": "id,name,phone_number,tenant_id,tenants(name)"
                }
            )
            
            if response.status_code != 200:
                logger.error(f"Supabase error: {response.status_code}")
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "authorized": False,
                            "message": "System error during authentication"
                        }
                    }]
                }
            
            users = response.json()
            if not users:
                logger.info("No users found for phone number")
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "authorized": False,
                            "message": "Phone number not found or not authorized"
                        }
                    }]
                }
            
            user = users[0]
            logger.info(f"Found user: {user}")
            
            # Log this authentication for session context
            await log_vapi_interaction(
                vapi_call_id=vapi_call_id,
                interaction_type="authentication",
                user_id=user['id'],
                tenant_id=user['tenant_id'],
                caller_phone=caller_phone,
                details={
                    "user_name": user['name'],
                    "tenant_name": user['tenants']['name'],
                    "auth_success": True
                }
            )
            
            # Get skills (your existing logic)
            skills_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/user_skills",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "user_id": f"eq.{user['id']}",
                    "is_enabled": "eq.true",
                    "select": "skills(skill_key,name,description,vapi_assistant_id)"
                }
            )
            
            user_skills = skills_response.json() if skills_response.status_code == 200 else []
            available_skills = []
            for user_skill in user_skills:
                skill = user_skill.get('skills', {})
                available_skills.append({
                    "skill_key": skill.get('skill_key'),
                    "skill_name": skill.get('name'),
                    "skill_description": skill.get('description', skill.get('name')),
                    "vapi_assistant_id": skill.get('vapi_assistant_id')
                })
            
            # Generate greeting
            first_name = user['name'].split()[0] if user['name'] else "there"
            
            if len(available_skills) == 1:
                greeting = f"Hi {first_name}! Ready for voice notes? Let me connect you right away."
            else:
                skill_names = [skill.get('skill_name', 'Unknown') for skill in available_skills]
                if len(skill_names) == 2:
                    greeting = f"Hi {first_name}! I can help you with {skill_names[0]} or {skill_names[1]}. What would you like to do?"
                else:
                    skills_text = ", ".join(skill_names[:-1]) + f", or {skill_names[-1]}"
                    greeting = f"Hi {first_name}! I can help you with {skills_text}. What would you like to do?"
            
            logger.info(f"Successfully authenticated {user['name']} with {len(available_skills)} skills")
            
            # Return VAPI-compatible response
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "authorized": True,
                        "user_id": user['id'],
                        "user_name": user['name'],
                        "first_name": first_name,
                        "tenant_name": user['tenants']['name'],
                        "phone_number": user['phone_number'],
                        "greeting_message": greeting,
                        "available_skills": available_skills,
                        "skill_count": len(available_skills),
                        "single_skill_mode": len(available_skills) == 1
                    }
                }]
            }
            
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return {
            "results": [{
                "toolCallId": tool_call_id,
                "result": {
                    "authorized": False,
                    "message": "Authentication system error",
                    "error": str(e)
                }
            }]
        }
    
async def log_vapi_interaction(vapi_call_id: str, interaction_type: str = None, 
                             user_id: str = None, tenant_id: str = None,
                             caller_phone: str = None, details: dict = None):
    """Log VAPI interactions for debugging and audit with improved error handling"""
    try:
        async with httpx.AsyncClient() as client:
            log_data = {
                "vapi_call_id": vapi_call_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "caller_phone": caller_phone,
                "raw_log_data": details or {},
                "created_at": datetime.utcnow().isoformat()
            }
            
            # Only add interaction_type if the column exists
            if interaction_type:
                log_data["interaction_type"] = interaction_type
            
            response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/vapi_logs",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                json=log_data
            )
            
            if response.status_code != 201:
                logger.error(f"Failed to log VAPI interaction: {response.status_code} - {response.text}")
                
    except Exception as e:
        logger.error(f"Failed to log VAPI interaction: {e}")


# Helper function to get session context for voice notes endpoints
async def get_session_context_by_call_id(vapi_call_id: str) -> Optional[Dict]:
    """
    Get session context from vapi_logs using call ID with improved reliability
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/vapi_logs",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "vapi_call_id": f"eq.{vapi_call_id}",
                    "interaction_type": "eq.authentication",
                    "select": "tenant_id,user_id,caller_phone,raw_log_data",
                    "limit": "1",
                    "order": "created_at.desc"
                }
            )
            
            if response.status_code == 200:
                logs = response.json()
                if logs:
                    log_entry = logs[0]
                    return {
                        "tenant_id": log_entry["tenant_id"],
                        "user_id": log_entry["user_id"],
                        "caller_phone": log_entry["caller_phone"],
                        "user_name": log_entry["raw_log_data"].get("user_name"),
                        "tenant_name": log_entry["raw_log_data"].get("tenant_name")
                    }
            
            logger.warning(f"No session context found for call ID: {vapi_call_id}")
            return None
    
    except Exception as e:
        logger.error(f"Error getting session context for call {vapi_call_id}: {str(e)}")
        return None

# ============================================
# ADD SESSION CONTEXT HELPER FUNCTION
# ============================================
"""
async def get_session_context_by_call_id(vapi_call_id: str) -> Optional[Dict]:
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/vapi_logs",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "vapi_call_id": f"eq.{vapi_call_id}",
                    "select": "tenant_id,user_id,caller_phone,raw_log_data",
                    "limit": "1",
                    "order": "created_at.desc"
                }
            )
            
            if response.status_code == 200:
                logs = response.json()
                return logs[0] if logs else None
            
            return None
    
    except Exception as e:
        logger.error(f"Error getting session context for call {vapi_call_id}: {str(e)}")
        return None
"""

# ============================================
# ADD VOICE NOTES SKILL ENDPOINTS
# ============================================

@app.post("/api/v1/skills/voice-notes/identify-context")
async def identify_voice_note_context(request: dict):
    """
    Identify if this is a site-specific note and validate the site if needed
    VAPI-compatible version handling format manually
    """
    try:
        # Extract VAPI arguments manually
        tool_call_id = "unknown"
        args = {}
        
        if "message" in request and "toolCalls" in request["message"]:
            tool_calls = request["message"]["toolCalls"]
            if len(tool_calls) > 0:
                tool_call = tool_calls[0]
                tool_call_id = tool_call.get("id", "unknown")
                args = tool_call["function"]["arguments"]
        else:
            args = request

        # Extract call ID from the full request structure
        vapi_call_id = None
        if "message" in request and "call" in request["message"]:
            vapi_call_id = request["message"]["call"]["id"]
            logger.info(f"Extracted call ID in identify_context: {vapi_call_id}")
        
        # Use tool_call_id as fallback if no call ID found
        if not vapi_call_id:
            vapi_call_id = tool_call_id
            logger.info(f"Using tool_call_id as fallback in identify_context: {vapi_call_id}")
        
        user_input = args.get("user_input", "")
        
        # Get session context from previous authentication
        session_context = await get_session_context_by_call_id(vapi_call_id)
        
        if not session_context:
            result = {
                "context_identified": False, 
                "error": "Call session not found. Please try calling again.",
                "message": "I couldn't find your call session. Please try calling again."
            }
        else:
            tenant_id = session_context["tenant_id"]
            
            async with httpx.AsyncClient() as client:
                # Get company name for better user experience
                company_response = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                    },
                    params={
                        "id": f"eq.{tenant_id}",
                        "select": "name"
                    }
                )
                
                company_name = "your company"
                if company_response.status_code == 200:
                    company_data = company_response.json()
                    if company_data:
                        company_name = company_data[0]["name"]
                
                # Simple heuristic to determine note type from user input
                site_keywords = ["site", "project", "construction", "building", "house", "office"]
                is_site_specific = any(keyword in user_input.lower() for keyword in site_keywords)
                
                if not is_site_specific:
                    result = {
                        "context_identified": True,
                        "note_type": "general",
                        "message": f"I'll record a general note for {company_name}.",
                        "company_name": company_name,
                        "site_id": None
                    }
                else:
                    # If potentially site-specific, get available sites
                    sites_response = await client.get(
                        f"{os.getenv('SUPABASE_URL')}/rest/v1/entities",
                        headers={
                            "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                            "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                        },
                        params={
                            "tenant_id": f"eq.{tenant_id}",
                            "entity_type": "eq.sites",
                            "is_active": "eq.true",
                            "select": "id,name,identifier,address"
                        }
                    )
                    
                    if sites_response.status_code != 200 or not sites_response.json():
                        result = {
                            "context_identified": True,
                            "note_type": "general",
                            "message": f"I'll record a general note for {company_name}. No active sites found.",
                            "company_name": company_name,
                            "site_id": None
                        }
                    else:
                        sites = sites_response.json()
                        
                        # Use OpenAI to match user input to available sites
                        site_list = "\n".join([
                            f"- ID: {site['id']}, Name: {site['name']}, Identifier: {site.get('identifier', 'None')}, Address: {site.get('address', 'None')}"
                            for site in sites
                        ])
                        
                        prompt = f"""
                        Available construction sites for {company_name}:
                        {site_list}

                        User said: "{user_input}"

                        Which site are they referring to? You MUST use the exact ID from the list above. Return JSON only:
                        {{
                          "site_found": true/false,
                          "site_id": "exact UUID from the ID field above if found, null if not found",
                          "site_name": "exact name if found",
                          "confidence": "high/medium/low"
                        }}

                        IMPORTANT: The site_id MUST be the exact UUID from the ID field, not a shortened version.
                        """
                        
                        # Call OpenAI API for site matching
                        openai_response = await client.post(
                            "https://api.openai.com/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
                                "Content-Type": "application/json"
                            },
                            json={
                                "model": "gpt-3.5-turbo",
                                "max_tokens": 500,
                                "messages": [{"role": "user", "content": prompt}]
                            }
                        )
                                        
                        if openai_response.status_code != 200:
                            logger.error(f"OpenAI API error: {openai_response.status_code} - {openai_response.text}")
                            result = {
                                "context_identified": True,
                                "note_type": "general",
                                "message": f"I'll record a general note for {company_name}. AI site matching unavailable.",
                                "company_name": company_name,
                                "site_id": None
                            }
                        else:
                            # Parse OpenAI response
                            openai_result = openai_response.json()
                            site_match_text = openai_result["choices"][0]["message"]["content"]
                            
                            # Parse JSON from OpenAI response
                            import json
                            try:
                                site_match = json.loads(site_match_text)
                            except json.JSONDecodeError as e:
                                logger.error(f"JSON parsing error: {e}. Response was: {site_match_text}")
                                result = {
                                    "context_identified": True,
                                    "note_type": "general",
                                    "message": f"I'll record a general note for {company_name}.",
                                    "company_name": company_name,
                                    "site_id": None
                                }
                            else:
                                # Validate that the returned site_id actually exists
                                if site_match.get("site_found"):
                                    matched_site_id = site_match["site_id"]
                                    matching_site = next((site for site in sites if site["id"] == matched_site_id), None)
                                    
                                    if matching_site:
                                        result = {
                                            "context_identified": True,
                                            "note_type": "site_specific",
                                            "site_id": matching_site["id"],
                                            "site_name": matching_site["name"],
                                            "site_identifier": matching_site.get("identifier"),
                                            "site_address": matching_site.get("address"),
                                            "message": f"I'll record a note for {matching_site['name']} at {company_name}.",
                                            "company_name": company_name
                                        }
                                    else:
                                        result = {
                                            "context_identified": True,
                                            "note_type": "general",
                                            "message": f"I'll record a general note for {company_name}.",
                                            "company_name": company_name,
                                            "site_id": None
                                        }
                                else:
                                    # Site not found - default to general
                                    result = {
                                        "context_identified": True,
                                        "note_type": "general",
                                        "message": f"I'll record a general note for {company_name}.",
                                        "company_name": company_name,
                                        "site_id": None
                                    }
        
        # Return VAPI format
        return {
            "results": [{
                "toolCallId": tool_call_id,
                "result": result
            }]
        }
        
    except Exception as e:
        logger.error(f"Context identification error: {str(e)}")
        return {
            "results": [{
                "toolCallId": "unknown",
                "result": {
                    "context_identified": False, 
                    "error": f"System error: {str(e)}",
                    "message": "I'm having trouble processing that. Let me record this as a general note."
                }
            }]
        }



@app.post("/api/v1/skills/voice-notes/save-note")
#@vapi_tool
async def save_voice_note(request: dict):
    """
    Save a voice note (either site-specific or general) with company context
    """

    # DEBUG: Log the full request structure
    logger.info(f"=== FULL VAPI REQUEST ===")
    logger.info(f"{json.dumps(request, indent=2)}")
    logger.info(f"=== END REQUEST ===")

    logger.info(f"Full VAPI request structure: {json.dumps(request, indent=2)}")

    """Save voice note - VAPI compatible"""
    
    # Extract VAPI arguments manually (like in identify_context)
    tool_call_id = "unknown"
    args = {}
    
    if "message" in request and "toolCalls" in request["message"]:
        tool_calls = request["message"]["toolCalls"]
        if len(tool_calls) > 0:
            tool_call = tool_calls[0]
            tool_call_id = tool_call.get("id", "unknown")
            args = tool_call["function"]["arguments"]
    else:
        args = request
    
    # Extract call ID from the full request structure
    vapi_call_id = None
    if "message" in request and "call" in request["message"]:
        vapi_call_id = request["message"]["call"]["id"]
        logger.info(f"Extracted call ID: {vapi_call_id}")

    try:
        if not vapi_call_id:
            vapi_call_id = args.get("vapi_call_id", "unknown")
        note_content = args.get("note_text", "")
        note_type = args.get("note_type", "general")
        site_id = args.get("site_id")
        priority = args.get("priority", "medium")

        # Use tool_call_id as a fallback identifier
        if not vapi_call_id:
            vapi_call_id = tool_call_id
            logger.info(f"Using tool_call_id as call identifier: {vapi_call_id}")
        
        if not note_content:
            return {
                "success": False, 
                "error": "Note content is required",
                "message": "I didn't receive any note content to save."
            }
        
        # Get session context from previous authentication
        session_context = await get_session_context_by_call_id(vapi_call_id)
        
        if not session_context:
            return {
                "success": False, 
                "error": "Call session not found",
                "message": "I couldn't find your call session. Please try calling again."
            }
        
        tenant_id = session_context["tenant_id"]
        user_id = session_context["user_id"]
        caller_phone = session_context["caller_phone"]
        
        async with httpx.AsyncClient() as client:
            # Get company name
            company_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "id": f"eq.{tenant_id}",
                    "select": "name"
                }
            )
            
            company_name = "Unknown Company"
            if company_response.status_code == 200:
                try:
                    company_data = company_response.json()
                    if company_data:
                        company_name = company_data[0]["name"]
                except:
                    pass
            
            # Get site name if site-specific
            site_name = None
            if site_id:
                site_response = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/entities",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                    },
                    params={
                        "id": f"eq.{site_id}",
                        "select": "name"
                    }
                )
                if site_response.status_code == 200:
                    try:
                        site_data = site_response.json()
                        if site_data:
                            site_name = site_data[0]["name"]
                    except:
                        pass
            
            # Generate unique ID for this note
            import uuid
            note_id = str(uuid.uuid4())
            
            # Create note summary (first 100 chars)
            note_summary = note_content[:100] + "..." if len(note_content) > 100 else note_content
            
            # Store in voice_notes table
            voice_note_data = {
                "id": note_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "site_id": site_id,
                "vapi_call_id": vapi_call_id,
                "phone_number": caller_phone,
                "note_type": note_type,
                "note_content": note_content,
                "note_summary": note_summary,
                #"priority": priority,
                "full_transcript": f"Voice note: {note_content}"
            }
            
            store_response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/voice_notes",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                json=voice_note_data
            )
            
            if store_response.status_code == 201:
                note_location = f" for {site_name}" if site_name else " (general)"
                logger.info(f"Voice note saved for {company_name}{note_location}: {vapi_call_id}")
                
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result":{
                            "success": True,
                            "note_id": note_id,
                            "message": f"Perfect! I've saved your voice note{note_location}.",
                            "company_name": company_name,
                            "site_name": site_name,
                            "note_type": note_type
                        }
                    }]
                }
            else:
                logger.error(f"Failed to store voice note: {store_response.status_code} - {store_response.text}")
                return {
                    "success": False, 
                    "error": f"Database error: {store_response.status_code}",
                    "message": "I'm having trouble saving your note. Please try again."
                }
    
    except Exception as e:
        logger.error(f"Voice note storage error: {str(e)}")
        return {
            "results": [{
                "toolCallId": tool_call_id,
                "result": {
                    "success": False, 
                    "error": f"Storage error: {str(e)}",
                    "message": "I'm having trouble saving your note. Please try again."
                }
            }]
        }
    

@app.get("/api/v1/skills/voice-notes/get-notes")
async def get_voice_notes(
    note_type: Optional[str] = None,  # 'general' or 'site_specific'
    site_id: Optional[str] = None,
    limit: int = 10,
    tenant_id: str = Depends(get_tenant_from_api_key)
):
    """
    Get voice notes for a tenant, optionally filtered by type or site
    """
    
    try:
        async with httpx.AsyncClient() as client:
            # Build query parameters
            params = {
                "tenant_id": f"eq.{tenant_id}",
                "select": "id,note_type,note_content,note_summary,full_transcript,created_at,users(name),entities(name,identifier,address)",
                "order": "created_at.desc",
                "limit": str(limit)
            }
            
            # Add filters if specified
            if note_type:
                params["note_type"] = f"eq.{note_type}"
            
            if site_id:
                params["site_id"] = f"eq.{site_id}"
            
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/voice_notes",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params=params
            )
            
            if response.status_code == 200:
                notes = response.json()
                
                # Format the response
                formatted_notes = []
                for note in notes:
                    formatted_note = {
                        "id": note["id"],
                        "note_type": note["note_type"],
                        "content": note["note_content"],
                        "summary": note["note_summary"],
                        "created_at": note["created_at"],
                        "user_name": note.get("users", {}).get("name") if note.get("users") else None
                    }
                    
                    # Add site info for site-specific notes
                    if note["note_type"] == "site_specific" and note.get("entities"):
                        site_info = note["entities"]
                        formatted_note["site"] = {
                            "name": site_info.get("name"),
                            "identifier": site_info.get("identifier"),
                            "address": site_info.get("address")
                        }
                    
                    formatted_notes.append(formatted_note)
                
                return {
                    "success": True,
                    "notes": formatted_notes,
                    "total": len(formatted_notes),
                    "filters": {
                        "note_type": note_type,
                        "site_id": site_id
                    }
                }
            else:
                return {"success": False, "error": f"Database error: {response.text}"}
    
    except Exception as e:
        logger.error(f"Error retrieving voice notes: {str(e)}")
        return {"success": False, "error": f"Query error: {str(e)}"}


# Add a user-specific endpoint that uses phone authentication
@app.post("/api/v1/skills/voice-notes/get-my-notes") 
async def get_my_voice_notes(
    request: dict  # Should contain vapi_call_id to get user context
):
    """
    Get voice notes for the authenticated user (from phone-only auth)
    """
    vapi_call_id = request.get("vapi_call_id")
    note_type = request.get("note_type")  # optional filter
    limit = request.get("limit", 10)
    
    try:
        # Get session context from phone authentication
        session_context = await get_session_context_by_call_id(vapi_call_id)
        
        if not session_context:
            return {"success": False, "error": "Call session not found"}
        
        tenant_id = session_context["tenant_id"]
        user_id = session_context["user_id"]
        
        async with httpx.AsyncClient() as client:
            # Build query parameters for user's notes
            params = {
                "tenant_id": f"eq.{tenant_id}",
                "user_id": f"eq.{user_id}",
                "select": "id,note_type,note_content,note_summary,created_at,entities(name,identifier)",
                "order": "created_at.desc",
                "limit": str(limit)
            }
            
            if note_type:
                params["note_type"] = f"eq.{note_type}"
            
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/voice_notes",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params=params
            )
            
            if response.status_code == 200:
                notes = response.json()
                
                # Separate general and site-specific notes
                general_notes = []
                site_notes = []
                
                for note in notes:
                    formatted_note = {
                        "id": note["id"],
                        "content": note["note_content"],
                        "summary": note["note_summary"],
                        "created_at": note["created_at"]
                    }
                    
                    if note["note_type"] == "general":
                        general_notes.append(formatted_note)
                    elif note["note_type"] == "site_specific":
                        if note.get("entities"):
                            formatted_note["site_name"] = note["entities"]["name"]
                            formatted_note["site_identifier"] = note["entities"].get("identifier")
                        site_notes.append(formatted_note)
                
                return {
                    "success": True,
                    "general_notes": general_notes,
                    "site_specific_notes": site_notes,
                    "total_general": len(general_notes),
                    "total_site_specific": len(site_notes)
                }
            else:
                return {"success": False, "error": f"Database error: {response.text}"}
    
    except Exception as e:
        logger.error(f"Error retrieving user notes: {str(e)}")
        return {"success": False, "error": f"Query error: {str(e)}"}

# ============================================
# INTERNAL USER HANDLER
# ============================================

async def handle_internal_user_auth(auth_result: Dict, intent: Optional[str]) -> UnifiedAuthResponse:
    """Handle authentication for internal users (employees)"""
    
    user_data = auth_result["user_data"]
    user_name = user_data["name"]
    user_role = user_data["role"]
    first_name = user_name.split()[0]
    
    # Process available skills
    skills_data = user_data.get("skills") or []
    available_skills = [
        SkillInfo(
            skill_key=skill["skill_key"],
            skill_name=skill["skill_name"],
            vapi_assistant_id=skill["vapi_assistant_id"],
            requires_entities=skill["requires_entities"],
            entity_type=skill["entity_type"]
        )
        for skill in skills_data
    ]
    
    if not available_skills:
        return UnifiedAuthResponse(
            authorized=True,
            session_type="internal_user",
            user_name=user_name,
            user_role=user_role,
            greeting_message=f"Hi {first_name}! I don't see any active capabilities for your account. Please contact your administrator."
        )
    
    # Single skill mode
    if len(available_skills) == 1:
        skill = available_skills[0]
        
        # Get entities if skill requires them
        entities = []
        if skill.requires_entities:
            entities = await get_available_entities(user_data["tenant_id"], skill.entity_type)
        
        return UnifiedAuthResponse(
            authorized=True,
            session_type="internal_user",
            user_name=user_name,
            user_role=user_role,
            available_skills=available_skills,
            available_entities=entities,
            single_skill_mode=True,
            greeting_message=f"Hi {first_name}! Ready to {skill.skill_name.lower()}?",
            next_assistant_id=skill.vapi_assistant_id
        )
    
    # Multiple skills - offer menu (simplified for now)
    skill_list = ", ".join([skill.skill_name.lower() for skill in available_skills])
    return UnifiedAuthResponse(
        authorized=True,
        session_type="internal_user",
        user_name=user_name,
        user_role=user_role,
        available_skills=available_skills,
        greeting_message=f"Hi {first_name}! What would you like to do today? I can help you with: {skill_list}."
    )

# ============================================
# EXTERNAL CUSTOMER HANDLER
# ============================================

async def handle_external_customer_auth(auth_result: Dict, intent: Optional[str]) -> UnifiedAuthResponse:
    """Handle authentication for external customers"""
    
    phone_data = auth_result["phone_data"]
    customer_data = auth_result["customer_data"]
    
    called_number_name = phone_data["name"]
    is_returning = customer_data.get("is_returning", False)
    customer_id = customer_data.get("id")
    
    # Process available skills
    skills_data = phone_data.get("skills") or []
    available_skills = [
        SkillInfo(
            skill_key=skill["skill_key"],
            skill_name=skill["skill_name"],
            vapi_assistant_id=skill["vapi_assistant_id"],
            requires_entities=skill["requires_entities"],
            entity_type=skill["entity_type"]
        )
        for skill in skills_data
    ]
    
    if not available_skills:
        return UnifiedAuthResponse(
            authorized=False,
            greeting_message=f"Thank you for calling {called_number_name}. Our system is currently unavailable. Please try again later."
        )
    
    # Generate greeting
    if is_returning:
        greeting = f"Hello! Thank you for calling {called_number_name}. Great to hear from you again."
    else:
        greeting = f"Hello! Thank you for calling {called_number_name}."
    
    # Single skill mode (common for customer lines)
    if len(available_skills) == 1:
        skill = available_skills[0]
        
        return UnifiedAuthResponse(
            authorized=True,
            session_type="external_customer",
            customer_id=customer_id,
            is_returning_customer=is_returning,
            called_number_name=called_number_name,
            available_skills=available_skills,
            single_skill_mode=True,
            greeting_message=f"{greeting} How can I help you today?",
            next_assistant_id=skill.vapi_assistant_id
        )
    
    # Multiple skills
    return UnifiedAuthResponse(
        authorized=True,
        session_type="external_customer",
        customer_id=customer_id,
        is_returning_customer=is_returning,
        called_number_name=called_number_name,
        available_skills=available_skills,
        greeting_message=f"{greeting} How can I help you today?"
    )

# ============================================
# HELPER FUNCTIONS
# ============================================

async def get_available_entities(tenant_id: str, entity_type: str) -> List[EntityInfo]:
    """Get available entities (sites/projects) for a tenant"""
    
    try:
        async with httpx.AsyncClient() as client:
            # Query entities directly with tenant_id filter
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/entities",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                },
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "entity_type": f"eq.{entity_type}",
                    "is_active": "eq.true",
                    "select": "id,name,identifier,address"
                }
            )
            
            if response.status_code == 200:
                entities_data = response.json()
                return [
                    EntityInfo(
                        id=entity["id"],
                        name=entity["name"],
                        identifier=entity.get("identifier"),
                        address=entity.get("address")
                    )
                    for entity in entities_data
                ]
            else:
                print(f"Error fetching entities: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Error fetching entities: {e}")
    
    return []

# ============================================
# SKILL SESSION MANAGEMENT
# ============================================

@app.post("/api/v1/vapi/start-session")
async def start_skill_session(
    request: SkillSessionRequest,
    tenant_id: str = Depends(get_tenant_from_api_key)
):
    """Start a skill session and return session ID"""
    
    try:
        # Create session record
        session_data = {
            "tenant_id": tenant_id,
            "vapi_call_id": request.vapi_call_id,
            "skill_key": request.skill_key,
            "caller_phone": request.caller_phone,
            "called_phone": request.called_phone,
            "entity_id": request.entity_id,
            "session_type": "external_customer" if request.called_phone else "internal_user",
            "status": "in_progress",
            "raw_log_data": {
                "session_started": datetime.utcnow().isoformat(),
                "initial_data": request.session_data
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/vapi_logs",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json"
                },
                json=session_data
            )
            
            if response.status_code == 201:
                session = response.json()
                return {"session_id": session[0]["id"], "status": "started"}
            
            raise HTTPException(status_code=500, detail="Failed to create session")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting session: {str(e)}")

# ============================================
# VAPI LOG STORAGE
# ============================================

@app.post("/api/v1/vapi/log")
async def store_vapi_log(
    request: VapiLogRequest,
    tenant_id: str = Depends(get_tenant_from_api_key)
):
    """Store complete VAPI log data"""
    
    try:
        # Find user or customer ID based on session type
        user_id = None
        customer_id = None
        
        if request.session_type == "internal_user":
            # Look up user by phone
            async with httpx.AsyncClient() as client:
                user_response = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                    },
                    params={
                        "tenant_id": f"eq.{tenant_id}",
                        "phone_number": f"eq.{request.caller_phone}",
                        "select": "id"
                    }
                )
                if user_response.status_code == 200:
                    users = user_response.json()
                    if users:
                        user_id = users[0]["id"]
        
        elif request.session_type == "external_customer":
            # Look up customer by phone
            async with httpx.AsyncClient() as client:
                customer_response = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/external_customers",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                    },
                    params={
                        "tenant_id": f"eq.{tenant_id}",
                        "phone_number": f"eq.{request.caller_phone}",
                        "select": "id"
                    }
                )
                if customer_response.status_code == 200:
                    customers = customer_response.json()
                    if customers:
                        customer_id = customers[0]["id"]
        
        # Store the log
        log_data = {
            "tenant_id": tenant_id,
            "vapi_call_id": request.vapi_call_id,
            "skill_key": request.skill_key,
            "caller_phone": request.caller_phone,
            "called_phone": request.called_phone,
            "user_id": user_id,
            "customer_id": customer_id,
            "session_type": request.session_type,
            "status": request.status,
            "duration_seconds": request.duration_seconds,
            "raw_log_data": request.raw_log_data
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/vapi_logs",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json"
                },
                json=log_data
            )
            
            if response.status_code == 201:
                return {"status": "logged", "log_id": response.json()[0]["id"]}
            
            raise HTTPException(status_code=500, detail="Failed to store log")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error storing log: {str(e)}")

# ============================================
# GET ENTITIES ENDPOINT
# ============================================

@app.get("/api/v1/vapi/entities/{entity_type}")
async def get_entities(
    entity_type: str,
    tenant_id: str = Depends(get_tenant_from_api_key)
):
    """Get available entities for a tenant"""
    
    entities = await get_available_entities(tenant_id, entity_type)
    return {
        "entities": entities, 
        "entity_type": entity_type,
        "tenant_id": tenant_id,
        "total_count": len(entities)
    }

# ============================================
# YOUR EXISTING DOCUMENT RAG ENDPOINTS
# ============================================
# Add your existing document search and processing endpoints here
# They should work alongside the VAPI endpoints

# ============================================
# DEBUG ENDPOINTS
# ============================================

# Add these debug endpoints to your main.py to troubleshoot the authentication

@app.get("/debug/test-tenant-auth/{api_key}")
async def test_tenant_authentication(api_key: str):
    """Test tenant authentication directly"""
    
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_service_key = os.getenv('SUPABASE_SERVICE_KEY')
    
    try:
        async with httpx.AsyncClient() as client:
            # Test the RPC function call
            response = await client.post(
                f"{supabase_url}/rest/v1/rpc/authenticate_tenant_by_api_key",
                headers={
                    "apikey": supabase_service_key,
                    "Authorization": f"Bearer {supabase_service_key}",
                    "Content-Type": "application/json"
                },
                json={"api_key_input": api_key}
            )
            
            return {
                "status_code": response.status_code,
                "response_text": response.text,
                "response_json": response.json() if response.status_code == 200 else None,
                "headers": dict(response.headers)
            }
    
    except Exception as e:
        return {
            "error": str(e),
            "type": type(e).__name__
        }

@app.get("/debug/test-caller-auth/{caller_phone}")
async def test_caller_authentication(caller_phone: str, called_phone: str = None):
    """Test caller authentication directly"""
    
    # First set tenant context
    tenant_id = None
    try:
        async with httpx.AsyncClient() as client:
            # Authenticate tenant first
            tenant_response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/authenticate_tenant_by_api_key",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json"
                },
                json={"api_key_input": "bmk-dev-key-2024"}
            )
            
            if tenant_response.status_code == 200:
                tenant_id = tenant_response.json()
            
            # Now test caller authentication
            caller_response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/authenticate_caller",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json"
                },
                json={
                    "caller_phone": caller_phone,
                    "called_phone": called_phone
                }
            )
            
            return {
                "tenant_auth": {
                    "status_code": tenant_response.status_code,
                    "tenant_id": tenant_id
                },
                "caller_auth": {
                    "status_code": caller_response.status_code,
                    "response_text": caller_response.text,
                    "response_json": caller_response.json() if caller_response.status_code == 200 else None
                }
            }
    
    except Exception as e:
        return {
            "error": str(e),
            "type": type(e).__name__,
            "tenant_id": tenant_id
        }

@app.get("/debug/check-users")
async def check_users_table():
    """Check what users exist in the database"""
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                },
                params={
                    "select": "id,phone_number,name,role,tenant_id,is_active"
                }
            )
            
            return {
                "status_code": response.status_code,
                "users": response.json() if response.status_code == 200 else None,
                "error": response.text if response.status_code != 200 else None
            }
    
    except Exception as e:
        return {
            "error": str(e),
            "type": type(e).__name__
        }

@app.get("/debug/check-tenants")
async def check_tenants_table():
    """Check what tenants exist in the database"""
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                },
                params={
                    "select": "id,name,api_key"
                }
            )
            
            return {
                "status_code": response.status_code,
                "tenants": response.json() if response.status_code == 200 else None,
                "error": response.text if response.status_code != 200 else None
            }
    
    except Exception as e:
        return {
            "error": str(e),
            "type": type(e).__name__
        }

@app.get("/debug/check-functions")
async def check_database_functions():
    """Check if our custom functions exist in the database"""
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/pg_get_functiondef",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json"
                },
                json={"function_oid": "authenticate_tenant_by_api_key"}
            )
            
            return {
                "status_code": response.status_code,
                "response": response.text,
                "note": "This might fail - checking if functions exist"
            }
    
    except Exception as e:
        # Try a simpler approach
        try:
            async with httpx.AsyncClient() as client:
                # Try calling the function with a test value
                response = await client.post(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/authenticate_tenant_by_api_key",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                        "Content-Type": "application/json"
                    },
                    json={"api_key_input": "test"}
                )
                
                return {
                    "function_exists": True,
                    "test_response_code": response.status_code,
                    "test_response": response.text[:200]
                }
        except:
            return {
                "error": str(e),
                "function_exists": False
            }
@app.get("/debug/test-caller-auth-fixed/{caller_phone}")
async def test_caller_authentication_fixed(caller_phone: str, called_phone: str = None):
    """Test caller authentication with proper tenant context setting"""
    
    try:
        async with httpx.AsyncClient() as client:
            # 1. Authenticate tenant first
            tenant_response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/authenticate_tenant_by_api_key",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json"
                },
                json={"api_key_input": "bmk-dev-key-2024"}
            )
            
            if tenant_response.status_code != 200:
                return {"error": "Tenant authentication failed"}
            
            tenant_id = tenant_response.json()
            
            # 2. Set tenant context explicitly
            context_response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/set_tenant_context",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json"
                },
                json={"tenant_uuid": tenant_id}
            )
            
            # 3. Now test caller authentication
            caller_response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/authenticate_caller",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json"
                },
                json={
                    "caller_phone": caller_phone,
                    "called_phone": called_phone
                }
            )
            
            return {
                "tenant_auth": {
                    "status_code": tenant_response.status_code,
                    "tenant_id": tenant_id
                },
                "context_setting": {
                    "status_code": context_response.status_code,
                    "response": context_response.text
                },
                "caller_auth": {
                    "status_code": caller_response.status_code,
                    "response_text": caller_response.text,
                    "response_json": caller_response.json() if caller_response.status_code == 200 else None
                }
            }
    
    except Exception as e:
        return {
            "error": str(e),
            "type": type(e).__name__
        }

@app.get("/debug/check-entities")
async def debug_check_entities(tenant_id: str = Depends(get_tenant_from_api_key)):
    """Debug: Check what entities exist in the database"""
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/entities",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                },
                params={
                    "select": "id,tenant_id,entity_type,name,identifier,address,is_active"
                }
            )
            
            return {
                "status_code": response.status_code,
                "all_entities": response.json() if response.status_code == 200 else None,
                "error": response.text if response.status_code != 200 else None,
                "current_tenant_id": tenant_id
            }
    
    except Exception as e:
        return {
            "error": str(e),
            "type": type(e).__name__,
            "current_tenant_id": tenant_id
        }
    
# Add this debug endpoint to your main.py
@app.get("/debug/check-voice-notes-table")
async def check_voice_notes_table():
    """Check if voice_notes table exists and what its structure is"""
    
    try:
        async with httpx.AsyncClient() as client:
            # Try to query the table structure
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/voice_notes",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "limit": "1"  # Just get one row to see structure
                }
            )
            
            return {
                "table_exists": response.status_code == 200,
                "status_code": response.status_code,
                "response_text": response.text,
                "error_details": None if response.status_code == 200 else response.text
            }
    
    except Exception as e:
        return {
            "table_exists": False,
            "error": str(e),
            "type": type(e).__name__
        }

# Also add this endpoint to test the session context retrieval
@app.get("/debug/check-session-context/{vapi_call_id}")
async def debug_session_context(vapi_call_id: str):
    """Debug: Check what session context exists for a call ID"""
    
    try:
        session_context = await get_session_context_by_call_id(vapi_call_id)
        
        return {
            "found": session_context is not None,
            "session_context": session_context
        }
    
    except Exception as e:
        return {
            "error": str(e),
            "type": type(e).__name__
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)