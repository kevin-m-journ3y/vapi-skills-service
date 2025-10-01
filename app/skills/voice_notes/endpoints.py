"""
Voice Notes Skill - FastAPI Endpoints

All webhook endpoints for the voice notes skill using VAPI format.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Optional
import logging
import json
import uuid
import httpx
import os

from app.vapi_utils import extract_vapi_args
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-notes"])


# Helper function to get session context
async def get_session_context_by_call_id(vapi_call_id: str) -> Optional[Dict]:
    """
    Get session context from vapi_logs using call ID
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.SUPABASE_URL}/rest/v1/vapi_logs",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
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

            # Only add interaction_type if provided
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


@router.post("/api/v1/skills/voice-notes/identify-context")
async def identify_voice_note_context(request: dict):
    """
    Identify if this is a site-specific note and validate the site if needed
    VAPI-compatible version
    """
    try:
        # Extract VAPI arguments
        tool_call_id, args = extract_vapi_args(request)

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
                # Get company name
                company_response = await client.get(
                    f"{settings.SUPABASE_URL}/rest/v1/tenants",
                    headers={
                        "apikey": settings.SUPABASE_SERVICE_KEY,
                        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
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

                # Simple heuristic to determine note type
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
                    # Get available sites
                    sites_response = await client.get(
                        f"{settings.SUPABASE_URL}/rest/v1/entities",
                        headers={
                            "apikey": settings.SUPABASE_SERVICE_KEY,
                            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
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
                                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
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


@router.post("/api/v1/skills/voice-notes/save-note")
async def save_voice_note(request: dict):
    """
    Save a voice note (either site-specific or general) with company context
    VAPI-compatible version
    """
    # Extract VAPI arguments
    tool_call_id, args = extract_vapi_args(request)

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
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "success": False,
                        "error": "Note content is required",
                        "message": "I didn't receive any note content to save."
                    }
                }]
            }

        # Get session context from previous authentication
        session_context = await get_session_context_by_call_id(vapi_call_id)

        if not session_context:
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "success": False,
                        "error": "Call session not found",
                        "message": "I couldn't find your call session. Please try calling again."
                    }
                }]
            }

        tenant_id = session_context["tenant_id"]
        user_id = session_context["user_id"]
        caller_phone = session_context["caller_phone"]

        async with httpx.AsyncClient() as client:
            # Get company name
            company_response = await client.get(
                f"{settings.SUPABASE_URL}/rest/v1/tenants",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
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
                    f"{settings.SUPABASE_URL}/rest/v1/entities",
                    headers={
                        "apikey": settings.SUPABASE_SERVICE_KEY,
                        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
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
                "full_transcript": f"Voice note: {note_content}"
            }

            store_response = await client.post(
                f"{settings.SUPABASE_URL}/rest/v1/voice_notes",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
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
                        "result": {
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
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "success": False,
                            "error": f"Database error: {store_response.status_code}",
                            "message": "I'm having trouble saving your note. Please try again."
                        }
                    }]
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
