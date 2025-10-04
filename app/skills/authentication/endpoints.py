"""
Authentication Skill Endpoints

Handles authentication-related webhook endpoints for VAPI.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
import logging
import httpx
import os

from app.vapi_utils import extract_vapi_args
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


# Helper function to log VAPI interactions
async def log_vapi_interaction(vapi_call_id: str, interaction_type: str = None,
                                user_id: str = None, tenant_id: str = None,
                                caller_phone: str = None, details: dict = None):
    """Log VAPI interactions for debugging and audit"""
    try:
        async with httpx.AsyncClient() as client:
            log_data = {
                "vapi_call_id": vapi_call_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "caller_phone": caller_phone,
                "raw_log_data": details or {},
            }

            if interaction_type:
                log_data["interaction_type"] = interaction_type

            response = await client.post(
                f"{settings.SUPABASE_URL}/rest/v1/vapi_logs",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                json=log_data
            )

            if response.status_code != 201:
                logger.error(f"Failed to log VAPI interaction: {response.status_code} - {response.text}")

    except Exception as e:
        logger.error(f"Failed to log VAPI interaction: {e}")


@router.post("/api/v1/vapi/authenticate-by-phone")
async def authenticate_by_phone(request: dict):
    """Authenticate caller by phone number - VAPI Server Tool format"""

    # Extract call ID and phone from VAPI request structure
    vapi_call_id = None
    caller_phone = None

    if "message" in request and "call" in request["message"]:
        call_data = request["message"]["call"]
        vapi_call_id = call_data.get("id")

        # Try to get phone from call metadata
        # VAPI provides customer.number in the call object
        if "customer" in call_data and "number" in call_data["customer"]:
            caller_phone = call_data["customer"]["number"]
            logger.info(f"Extracted phone from VAPI call metadata: {caller_phone}")

    tool_call_id, args = extract_vapi_args(request)

    try:
        # Fallback to args if not found in metadata
        if not caller_phone:
            caller_phone = args.get("caller_phone")

        if not vapi_call_id:
            vapi_call_id = args.get("vapi_call_id", "unknown")

        # Validate phone number is provided
        if not caller_phone or caller_phone.strip() == "":
            # In production, require a valid phone number
            # For local testing, set TEST_DEFAULT_PHONE environment variable
            test_phone = os.getenv("TEST_DEFAULT_PHONE")
            if test_phone:
                caller_phone = test_phone
                logger.info(f"No phone in call metadata or args, using test default: {caller_phone}")
            else:
                logger.error("No phone number provided and TEST_DEFAULT_PHONE not set")
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "authorized": False,
                            "message": "Phone number is required for authentication"
                        }
                    }]
                }

        logger.info(f"Authenticating phone: {caller_phone}, call: {vapi_call_id}, toolCallId: {tool_call_id}")

        # Authenticate user
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.SUPABASE_URL}/rest/v1/users",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
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

            # Note: Log will be updated after we fetch skills and sites

            # Get skills
            skills_response = await client.get(
                f"{settings.SUPABASE_URL}/rest/v1/user_skills",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
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

            # Get all active sites for this tenant
            sites_response = await client.get(
                f"{settings.SUPABASE_URL}/rest/v1/entities",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
                },
                params={
                    "tenant_id": f"eq.{user['tenant_id']}",
                    "entity_type": "eq.sites",
                    "is_active": "eq.true",
                    "select": "id,name,identifier,address"
                }
            )

            available_sites = []
            if sites_response.status_code == 200:
                sites = sites_response.json()
                for site in sites:
                    available_sites.append({
                        "site_id": site['id'],
                        "site_name": site['name'],
                        "site_identifier": site.get('identifier'),
                        "site_address": site.get('address')
                    })

            # Generate greeting
            first_name = user['name'].split()[0] if user['name'] else "there"

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

            logger.info(f"Successfully authenticated {user['name']} with {len(available_skills)} skills and {len(available_sites)} sites")

            # Log this authentication with full context for session
            await log_vapi_interaction(
                vapi_call_id=vapi_call_id,
                interaction_type="authentication",
                user_id=user['id'],
                tenant_id=user['tenant_id'],
                caller_phone=caller_phone,
                details={
                    "user_name": user['name'],
                    "user_role": user.get('role'),
                    "tenant_name": user['tenants']['name'],
                    "tenant_id": user['tenant_id'],
                    "auth_success": True,
                    "available_skills": available_skills,
                    "available_sites": available_sites,
                    "site_count": len(available_sites)
                }
            )

            # Return VAPI-compatible response with enriched context
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "authorized": True,
                        "user_id": user['id'],
                        "user_name": user['name'],
                        "first_name": first_name,
                        "user_role": user.get('role', 'user'),
                        "tenant_id": user['tenant_id'],
                        "tenant_name": user['tenants']['name'],
                        "phone_number": user['phone_number'],
                        "greeting_message": greeting,
                        "available_skills": available_skills,
                        "skill_count": len(available_skills),
                        "single_skill_mode": len(available_skills) == 1,
                        "available_sites": available_sites,
                        "site_count": len(available_sites)
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
