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
                    "select": "id,company_name,phone"
                }
            )

            if response.status_code == 200:
                users = response.json()
                if users and len(users) > 0:
                    user = users[0]
                    logger.info(f"User authenticated: {user.get('id')}")

                    return {
                        "results": [{
                            "toolCallId": data.get("message", {}).get("toolCallId"),
                            "result": f"Authenticated as {user.get('company_name', 'user')}. User ID: {user.get('id')}"
                        }]
                    }

            logger.warning(f"Authentication failed for phone: {caller_phone}")
            return {
                "results": [{
                    "toolCallId": data.get("message", {}).get("toolCallId"),
                    "result": "Authentication failed: Phone number not registered"
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
