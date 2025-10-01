"""
Authentication Skill Endpoints

Handles authentication-related webhook endpoints for VAPI.
"""

from fastapi import APIRouter, Request, HTTPException
from typing import Dict, Any
import logging
import httpx

from app.vapi_utils import extract_vapi_args
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/v1/vapi/authenticate-by-phone")
async def authenticate_by_phone(request: Request) -> Dict[str, Any]:
    """
    Authenticate caller by phone number

    Verifies that the caller's phone number is registered in the system.
    Returns user information if authenticated.
    """
    try:
        data = await request.json()
        logger.info(f"Received authenticate-by-phone request: {data}")

        # Extract the caller_phone parameter from VAPI format
        caller_phone = extract_vapi_args(data).get('caller_phone')

        if not caller_phone:
            logger.error("No caller_phone provided in request")
            return {
                "results": [{
                    "toolCallId": data.get("message", {}).get("toolCallId"),
                    "result": "Error: No phone number provided"
                }]
            }

        # Query Supabase for user with this phone number
        logger.info(f"Authenticating phone: {caller_phone}")

        async with httpx.AsyncClient() as client:
            # Query users table via Supabase REST API
            headers = {
                "apikey": settings.SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
                "Content-Type": "application/json"
            }

            response = await client.get(
                f"{settings.SUPABASE_URL}/rest/v1/users",
                headers=headers,
                params={
                    "phone": f"eq.{caller_phone}",
                    "select": "id,name,company_name,phone,tenant_id,tenants(name)"
                }
            )

            if response.status_code == 200:
                users = response.json()
                if users and len(users) > 0:
                    user = users[0]
                    logger.info(f"User authenticated: {user.get('id')}")

                    # Get user's available skills
                    skills_response = await client.get(
                        f"{settings.SUPABASE_URL}/rest/v1/user_skills",
                        headers=headers,
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
                        if skill:
                            available_skills.append({
                                "skill_key": skill.get('skill_key'),
                                "skill_name": skill.get('name'),
                                "skill_description": skill.get('description', skill.get('name')),
                                "vapi_assistant_id": skill.get('vapi_assistant_id')
                            })

                    # Generate dynamic greeting based on available skills
                    first_name = user.get('name', 'there').split()[0] if user.get('name') else "there"

                    if len(available_skills) == 0:
                        greeting = f"Hi {first_name}! I don't have any skills configured for you yet. Please contact support."
                    elif len(available_skills) == 1:
                        skill_name = available_skills[0].get('skill_name', 'Unknown')
                        greeting = f"Hi {first_name}! Ready for {skill_name}? Let's get started."
                    else:
                        skill_names = [skill.get('skill_name', 'Unknown') for skill in available_skills]
                        if len(skill_names) == 2:
                            greeting = f"Hi {first_name}! I can help you with {skill_names[0]} or {skill_names[1]}. What would you like to do?"
                        else:
                            skills_text = ", ".join(skill_names[:-1]) + f", or {skill_names[-1]}"
                            greeting = f"Hi {first_name}! I can help you with {skills_text}. What would you like to do?"

                    logger.info(f"Successfully authenticated {user.get('name')} with {len(available_skills)} skills")

                    return {
                        "results": [{
                            "toolCallId": data.get("message", {}).get("toolCallId"),
                            "result": {
                                "authorized": True,
                                "user_id": user['id'],
                                "user_name": user.get('name'),
                                "first_name": first_name,
                                "company_name": user.get('company_name'),
                                "tenant_name": user.get('tenants', {}).get('name') if user.get('tenants') else None,
                                "phone_number": user.get('phone'),
                                "greeting_message": greeting,
                                "available_skills": available_skills,
                                "skill_count": len(available_skills),
                                "single_skill_mode": len(available_skills) == 1
                            }
                        }]
                    }

            logger.warning(f"Authentication failed for phone: {caller_phone}")
            return {
                "results": [{
                    "toolCallId": data.get("message", {}).get("toolCallId"),
                    "result": {
                        "authorized": False,
                        "message": "Authentication failed: Phone number not registered"
                    }
                }]
            }

    except Exception as e:
        logger.error(f"Error in authenticate-by-phone: {str(e)}", exc_info=True)
        return {
            "results": [{
                "toolCallId": data.get("message", {}).get("toolCallId", "unknown"),
                "result": f"Error during authentication: {str(e)}"
            }]
        }
