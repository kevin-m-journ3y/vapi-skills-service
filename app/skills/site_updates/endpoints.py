"""
Site Updates Skill - FastAPI Endpoints

Webhook endpoints for site progress updates using VAPI format.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Optional
import logging
import json
import httpx
import uuid

from app.vapi_utils import extract_vapi_args
from app.config import settings
from app.skills.site_updates.processors import get_processor

logger = logging.getLogger(__name__)

router = APIRouter(tags=["site-updates"])


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


@router.post("/api/v1/skills/site-updates/identify-site")
async def identify_site_for_update(request: dict):
    """
    Identify which site the user wants to provide an update for
    Uses AI to match user's description to available sites in their tenant

    Can be called without site_description to get the list of available sites
    """
    try:
        # Extract VAPI arguments
        tool_call_id, args = extract_vapi_args(request)

        # Extract call ID from the full request structure
        vapi_call_id = None
        if "message" in request and "call" in request["message"]:
            vapi_call_id = request["message"]["call"]["id"]

        if not vapi_call_id:
            vapi_call_id = tool_call_id

        site_description = args.get("site_description", "")

        logger.info(f"Identifying site for update. Call: {vapi_call_id}, Input: {site_description}")

        # Get session context
        session_context = await get_session_context_by_call_id(vapi_call_id)

        if not session_context:
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "site_identified": False,
                        "error": "Session not found. Please authenticate first.",
                        "message": "I couldn't find your session. Please try calling again."
                    }
                }]
            }

        tenant_id = session_context["tenant_id"]

        async with httpx.AsyncClient() as client:
            # Get available sites for this tenant
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
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "site_identified": False,
                            "message": "I couldn't find any active sites for your account. Please contact support."
                        }
                    }]
                }

            sites = sites_response.json()

            # If no site_description provided, return the list of available sites
            if not site_description or site_description.strip() == "":
                site_list_for_assistant = [
                    {
                        "site_id": site['id'],
                        "site_name": site['name'],
                        "site_identifier": site.get('identifier'),
                        "site_address": site.get('address')
                    }
                    for site in sites
                ]

                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "site_identified": False,
                            "sites_list": site_list_for_assistant,
                            "message": f"You have {len(sites)} sites available for updates."
                        }
                    }]
                }

            # Use OpenAI to match user input to available sites
            site_list = "\n".join([
                f"- ID: {site['id']}, Name: {site['name']}, Identifier: {site.get('identifier', 'None')}, Address: {site.get('address', 'None')}"
                for site in sites
            ])

            prompt = f"""
Available construction sites:
{site_list}

User said: "{site_description}"

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
                    "model": "gpt-4o-mini",
                    "max_tokens": 500,
                    "messages": [{"role": "user", "content": prompt}]
                }
            )

            if openai_response.status_code != 200:
                logger.error(f"OpenAI API error: {openai_response.status_code} - {openai_response.text}")
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "site_identified": False,
                            "message": "I'm having trouble matching that to a site. Could you be more specific?"
                        }
                    }]
                }

            # Parse OpenAI response
            openai_result = openai_response.json()
            site_match_text = openai_result["choices"][0]["message"]["content"]

            # Parse JSON from OpenAI response
            try:
                site_match = json.loads(site_match_text)
            except json.JSONDecodeError as e:
                logger.error(f"JSON parsing error: {e}. Response was: {site_match_text}")
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "site_identified": False,
                            "message": "I'm having trouble understanding which site you mean. Can you tell me the site name?"
                        }
                    }]
                }

            # Validate that the returned site_id actually exists
            if site_match.get("site_found"):
                matched_site_id = site_match["site_id"]
                matching_site = next((site for site in sites if site["id"] == matched_site_id), None)

                if matching_site:
                    logger.info(f"Successfully identified site: {matching_site['name']}")
                    return {
                        "results": [{
                            "toolCallId": tool_call_id,
                            "result": {
                                "site_identified": True,
                                "site_id": matching_site["id"],
                                "site_name": matching_site["name"],
                                "site_identifier": matching_site.get("identifier"),
                                "site_address": matching_site.get("address"),
                                "message": f"Great! Let's record an update for {matching_site['name']}."
                            }
                        }]
                    }

            # Site not found - ask for clarification
            site_names = [site['name'] for site in sites]
            if len(site_names) == 1:
                suggestion = f"Did you mean {site_names[0]}?"
            elif len(site_names) == 2:
                suggestion = f"Did you mean {site_names[0]} or {site_names[1]}?"
            else:
                suggestion = f"Your available sites are: {', '.join(site_names)}."

            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "site_identified": False,
                        "message": f"I couldn't match that to a site. {suggestion}"
                    }
                }]
            }

    except Exception as e:
        logger.error(f"Site identification error: {str(e)}")
        return {
            "results": [{
                "toolCallId": tool_call_id if 'tool_call_id' in locals() else "unknown",
                "result": {
                    "site_identified": False,
                    "error": f"System error: {str(e)}",
                    "message": "I'm having trouble processing that. Please try again."
                }
            }]
        }


@router.post("/api/v1/skills/site-updates/save-update")
async def save_site_progress_update(request: dict):
    """
    Save a complete site progress update with AI processing
    """
    tool_call_id, args = extract_vapi_args(request)

    # Extract call ID and messages from VAPI request
    vapi_call_id = None
    messages = []
    if "message" in request and "call" in request["message"]:
        vapi_call_id = request["message"]["call"]["id"]
        messages = request["message"]["call"].get("messages", [])

    try:
        if not vapi_call_id:
            vapi_call_id = args.get("vapi_call_id", tool_call_id)

        site_id = args.get("site_id")

        if not site_id:
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "success": False,
                        "error": "Site ID is required",
                        "message": "I need to know which site this update is for."
                    }
                }]
            }

        logger.info(f"Saving site progress update for site: {site_id}, call: {vapi_call_id}")
        logger.info(f"Received {len(messages)} messages in request")

        # Get session context
        session_context = await get_session_context_by_call_id(vapi_call_id)

        if not session_context:
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "success": False,
                        "error": "Session not found",
                        "message": "I couldn't find your session. Please try calling again."
                    }
                }]
            }

        tenant_id = session_context["tenant_id"]
        user_id = session_context["user_id"]

        # Build full transcript from messages in the VAPI request
        # VAPI sends the conversation messages directly in the tool call request
        real_transcript = ""
        if messages:
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "") or msg.get("message", "")
                if content:
                    if role == "user":
                        real_transcript += f"User: {content}\n"
                    elif role == "assistant":
                        real_transcript += f"Assistant: {content}\n"
            logger.info(f"Built transcript from {len(messages)} messages (length: {len(real_transcript)})")

        # Fallback to raw_notes from assistant if no messages available
        if not real_transcript:
            real_transcript = args.get("raw_notes", "")
            logger.info(f"No messages in request, using raw_notes from assistant (length: {len(real_transcript)})")

        # Build update data with real transcript
        update_data = {
            "main_focus": None,  # Will be extracted by AI processor
            "is_wet_weather_closure": False,  # Will be determined by AI processor
            "materials_delivered": None,
            "work_progress": None,
            "issues": None,
            "delays": None,
            "staffing": None,
            "site_visitors": None,
            "site_conditions": None,
            "follow_up_actions": None,
            "raw_transcript": real_transcript  # Use real conversation transcript
        }

        # Process with OpenAI to extract intelligence
        processor = get_processor()
        ai_processed = await processor.process_update(update_data)

        # Generate unique ID for this update
        update_id = str(uuid.uuid4())

        # Merge AI-extracted structured fields with the original data
        # AI processor now returns the full structured data including main_focus, work_progress, etc.
        complete_update = {
            "id": update_id,
            "site_id": site_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "vapi_call_id": vapi_call_id,
            "raw_transcript": real_transcript,  # Store the real tagged transcript
            **ai_processed,  # AI-extracted data includes all structured fields now
            "processing_status": "completed"
        }

        # Store in database
        async with httpx.AsyncClient() as client:
            # Verify site exists and belongs to tenant
            site_check = await client.get(
                f"{settings.SUPABASE_URL}/rest/v1/entities",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
                },
                params={
                    "id": f"eq.{site_id}",
                    "tenant_id": f"eq.{tenant_id}",
                    "entity_type": "eq.sites",
                    "select": "id,name"
                }
            )

            if site_check.status_code != 200 or not site_check.json():
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "success": False,
                            "error": "Site not found or access denied",
                            "message": "I couldn't verify that site. Please try again."
                        }
                    }]
                }

            site_info = site_check.json()[0]
            site_name = site_info["name"]

            # Save the update
            store_response = await client.post(
                f"{settings.SUPABASE_URL}/rest/v1/site_progress_updates",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                json=complete_update
            )

            if store_response.status_code == 201:
                logger.info(f"Site progress update saved for {site_name}: {update_id}")

                # Build response message
                message = f"Perfect! I've saved your update for {site_name}."

                if ai_processed.get("has_urgent_issues"):
                    message += " I've flagged the urgent issues for immediate attention."

                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "success": True,
                            "update_id": update_id,
                            "site_name": site_name,
                            "message": message,
                            "has_urgent_issues": ai_processed.get("has_urgent_issues", False),
                            "has_safety_concerns": ai_processed.get("has_safety_concerns", False)
                        }
                    }]
                }
            else:
                logger.error(f"Failed to store site update: {store_response.status_code} - {store_response.text}")
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "success": False,
                            "error": f"Database error: {store_response.status_code}",
                            "message": "I'm having trouble saving your update. Please try again."
                        }
                    }]
                }

    except Exception as e:
        logger.error(f"Site update save error: {str(e)}")
        return {
            "results": [{
                "toolCallId": tool_call_id,
                "result": {
                    "success": False,
                    "error": f"System error: {str(e)}",
                    "message": "I'm having trouble saving your update. Please try again."
                }
            }]
        }
