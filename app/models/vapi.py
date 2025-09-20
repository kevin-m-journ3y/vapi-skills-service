from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class VapiAuthRequest(BaseModel):
    caller_phone: str
    called_phone: str  
    call_id: str
    intent: Optional[str] = None

class SkillInfo(BaseModel):
    skill_key: str
    name: str
    description: str
    vapi_assistant_id: Optional[str]
    requires_entities: bool
    entity_type: Optional[str]
    config: Optional[Dict] = {}

class UnifiedAuthResponse(BaseModel):
    authorized: bool
    session_type: Optional[str] = None
    
    # User information
    user_name: Optional[str] = None
    tenant_name: Optional[str] = None
    
    # Customer information  
    customer_id: Optional[str] = None
    is_returning_customer: bool = False
    
    # Phone number information
    called_number_name: Optional[str] = None
    agent_name: Optional[str] = None
    
    # Available skills and routing
    available_skills: List[SkillInfo] = []
    single_skill_mode: bool = False
    greeting_message: str = ""
    next_assistant_id: Optional[str] = None
    
    # Session context
    session_context: Dict[str, Any] = {}