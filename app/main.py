# app/main.py - Complete FastAPI application with VAPI endpoints

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import httpx
import os
from datetime import datetime
from dotenv import load_dotenv  # Add this import

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="Multi-Tenant Document RAG + VAPI Skills System", version="1.0.0")

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

# ============================================
# ENVIRONMENT CHECK ENDPOINT
# ============================================

@app.get("/debug/env-check")
async def check_environment():
    """Check if environment variables are properly set"""
    return {
        "supabase_url": (os.getenv('SUPABASE_URL')[:50] + "...") if os.getenv('SUPABASE_URL') else "NOT SET",
        "supabase_service_key": "SET" if os.getenv('SUPABASE_SERVICE_KEY') else "NOT SET",
        "openai_api_key": "SET" if os.getenv('OPENAI_API_KEY') else "NOT SET",
        "google_service_account": "SET" if os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON') else "NOT SET",
        "environment": os.getenv('ENVIRONMENT', 'NOT SET'),
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)