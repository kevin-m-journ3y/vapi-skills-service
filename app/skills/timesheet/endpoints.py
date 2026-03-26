"""
Timesheet Skill - FastAPI Endpoints

Webhook endpoints for verbal timesheet logging using VAPI format.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Optional, List
import logging
import json
import httpx
import uuid
from datetime import datetime, time as datetime_time
from zoneinfo import ZoneInfo

from app.vapi_utils import extract_vapi_args
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["timesheet"])

# Sydney timezone for date handling
SYDNEY_TZ = ZoneInfo('Australia/Sydney')


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
                        "tenant_name": log_entry["raw_log_data"].get("tenant_name"),
                        "available_sites": log_entry["raw_log_data"].get("available_sites", []),
                        "current_date": log_entry["raw_log_data"].get("current_date"),
                        "tenant_timezone": log_entry["raw_log_data"].get("tenant_timezone", "Australia/Sydney"),
                    }

            logger.warning(f"No session context found for call ID: {vapi_call_id}")
            return None

    except Exception as e:
        logger.error(f"Error getting session context for call {vapi_call_id}: {str(e)}")
        return None


def calculate_hours_worked(start_time: str, end_time: str) -> float:
    """
    Calculate hours worked from start and end times.

    Includes a PM auto-correction: if the end time is before the start time
    and adding 12 hours to the end produces a reasonable shift (≤14h),
    assume the user meant PM. This catches the common case where a user says
    "3:30" meaning 15:30 but the LLM sends "03:30".

    Args:
        start_time: Time in HH:MM format
        end_time: Time in HH:MM format

    Returns:
        Hours worked as a decimal (e.g., 7.5 for 7 hours 30 minutes)
    """
    try:
        start = datetime.strptime(start_time, "%H:%M")
        end = datetime.strptime(end_time, "%H:%M")

        if end < start:
            # Try adding 12 hours (user likely meant PM)
            end_pm = end.replace(hour=end.hour + 12)
            pm_hours = (end_pm - start).total_seconds() / 3600
            if 0 < pm_hours <= 14:
                logger.info(
                    f"PM auto-correction: {end_time} → {end_pm.strftime('%H:%M')} "
                    f"(hours: {round(pm_hours, 2)} instead of overnight calc)"
                )
                return round(pm_hours, 2)
            # Genuinely overnight (e.g. night shift) — keep original logic
            end = end.replace(day=start.day + 1)

        duration = end - start
        hours = duration.total_seconds() / 3600
        return round(hours, 2)
    except Exception as e:
        logger.error(f"Error calculating hours: {e}")
        return 0.0


@router.post("/api/v1/skills/timesheet/identify-site")
async def identify_site_for_timesheet(request: dict):
    """
    Identify which site the user wants to log time for
    Uses AI to match user's description to available sites in their tenant
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

        logger.info(f"Identifying site for timesheet. Call: {vapi_call_id}, Input: {site_description}")

        # Check if this is an overhead work request
        overhead_keywords = [
            'overhead', 'overheads', 'admin', 'office', 'general duties',
            'general', 'paperwork', 'non-site', 'administration'
        ]
        is_overhead_request = any(keyword in site_description.lower() for keyword in overhead_keywords)

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
            # If this is an overhead work request, try to find the overhead site first
            if is_overhead_request:
                logger.info(f"Overhead work detected. Searching for overhead site for tenant {tenant_id}")
                overhead_response = await client.get(
                    f"{settings.SUPABASE_URL}/rest/v1/entities",
                    headers={
                        "apikey": settings.SUPABASE_SERVICE_KEY,
                        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
                    },
                    params={
                        "tenant_id": f"eq.{tenant_id}",
                        "entity_type": "eq.sites",
                        "is_active": "eq.true",
                        "select": "id,name,identifier,address,metadata"
                    }
                )

                if overhead_response.status_code == 200:
                    all_sites = overhead_response.json()
                    # Find site with is_overhead metadata
                    overhead_site = None
                    for site in all_sites:
                        metadata = site.get('metadata', {})
                        if isinstance(metadata, dict) and metadata.get('is_overhead') == True:
                            overhead_site = site
                            break

                    if overhead_site:
                        logger.info(f"Found overhead site: {overhead_site['name']} ({overhead_site['id']})")
                        return {
                            "results": [{
                                "toolCallId": tool_call_id,
                                "result": {
                                    "site_identified": True,
                                    "site_id": overhead_site['id'],
                                    "site_name": overhead_site['name'],
                                    "confidence": "high",
                                    "is_overhead": True,
                                    "message": f"Got it! Logging time for {overhead_site['name']}. What time did you start?"
                                }
                            }]
                        }
                    else:
                        logger.warning(f"No overhead site found for tenant {tenant_id}")

            # Get available sites for this tenant (regular flow or fallback)
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
                            "message": f"You have {len(sites)} sites available for timesheet logging."
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
                            "message": "I had trouble identifying that site. Could you be more specific?"
                        }
                    }]
                }

            openai_data = openai_response.json()
            ai_content = openai_data['choices'][0]['message']['content']

            # Parse JSON from AI response
            # Handle markdown code blocks
            if "```json" in ai_content:
                ai_content = ai_content.split("```json")[1].split("```")[0].strip()
            elif "```" in ai_content:
                ai_content = ai_content.split("```")[1].split("```")[0].strip()

            match_result = json.loads(ai_content)

            if match_result.get("site_found"):
                site_id = match_result["site_id"]
                site_name = match_result["site_name"]
                confidence = match_result.get("confidence", "medium")

                logger.info(f"Site identified: {site_name} ({site_id}) with {confidence} confidence")

                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "site_identified": True,
                            "site_id": site_id,
                            "site_name": site_name,
                            "confidence": confidence,
                            "message": f"Great! I've identified {site_name}. What time did you start work there today?"
                        }
                    }]
                }
            else:
                # Site not found - provide list for clarification
                site_names = [site['name'] for site in sites]
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "site_identified": False,
                            "available_sites": site_names,
                            "message": f"I couldn't find that site. Your available sites are: {', '.join(site_names)}. Which one did you mean?"
                        }
                    }]
                }

    except Exception as e:
        logger.error(f"Error in identify_site_for_timesheet: {str(e)}", exc_info=True)
        return {
            "results": [{
                "toolCallId": tool_call_id,
                "result": {
                    "site_identified": False,
                    "error": str(e),
                    "message": "I encountered an error identifying the site. Please try again."
                }
            }]
        }


@router.post("/api/v1/skills/timesheet/save-entry")
async def save_timesheet_entry(request: dict):
    """
    Save a timesheet entry for one site
    This is called for each site the user worked at
    """
    try:
        # Extract VAPI arguments
        tool_call_id, args = extract_vapi_args(request)

        # Extract call ID
        vapi_call_id = None
        if "message" in request and "call" in request["message"]:
            vapi_call_id = request["message"]["call"]["id"]

        if not vapi_call_id:
            vapi_call_id = args.get("vapi_call_id", tool_call_id)

        # Get required fields
        site_id = args.get("site_id")
        start_time = args.get("start_time")
        end_time = args.get("end_time")
        work_description = args.get("work_description")
        plans_for_tomorrow = args.get("plans_for_tomorrow", "")
        work_date_arg = args.get("work_date")  # Optional - for historical entries

        logger.info(f"Saving timesheet entry. Call: {vapi_call_id}, Site: {site_id}, Date: {work_date_arg or 'today'}")

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

        # Calculate hours worked
        hours_worked = calculate_hours_worked(start_time, end_time)

        # Determine work_date: use provided date or default to current_date from session
        if work_date_arg:
            # Use the date provided by the assistant (for historical entries)
            work_date_str = work_date_arg
        else:
            # Default to current_date from authentication (tenant timezone aware)
            work_date_str = session_context.get("current_date")
            if not work_date_str:
                # Fallback to Sydney time if not in session (backwards compatibility)
                tenant_timezone = session_context.get("tenant_timezone", "Australia/Sydney")
                tz = ZoneInfo(tenant_timezone)
                work_date_str = datetime.now(tz).strftime('%Y-%m-%d')

        work_date = work_date_str

        # Create timesheet entry
        timesheet_entry = {
            "id": str(uuid.uuid4()),
            "site_id": site_id,
            "user_id": session_context["user_id"],
            "tenant_id": session_context["tenant_id"],
            "vapi_call_id": vapi_call_id,
            "work_date": work_date,  # Already in ISO format (YYYY-MM-DD)
            "start_time": start_time,
            "end_time": end_time,
            "hours_worked": hours_worked,
            "work_description": work_description,
            "plans_for_tomorrow": plans_for_tomorrow
        }

        # Save to database
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.SUPABASE_URL}/rest/v1/timesheets",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                json=timesheet_entry
            )

            if response.status_code != 201:
                logger.error(f"Failed to save timesheet: {response.status_code} - {response.text}")
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "success": False,
                            "error": "Database error",
                            "message": "I had trouble saving that entry. Please try again."
                        }
                    }]
                }

        logger.info(f"Timesheet entry saved successfully: {timesheet_entry['id']}")

        # Auto-close matching active sign-on (fire-and-forget)
        try:
            async with httpx.AsyncClient() as client:
                # Find active sign-on for this user + site + today
                tenant_timezone = session_context.get("tenant_timezone", "Australia/Sydney")
                tz = ZoneInfo(tenant_timezone)
                today_start = datetime.strptime(work_date, '%Y-%m-%d').replace(
                    hour=0, minute=0, second=0, tzinfo=tz
                )
                today_end = datetime.strptime(work_date, '%Y-%m-%d').replace(
                    hour=23, minute=59, second=59, tzinfo=tz
                )

                signon_resp = await client.get(
                    f"{settings.SUPABASE_URL}/rest/v1/site_signons",
                    headers={
                        "apikey": settings.SUPABASE_SERVICE_KEY,
                        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
                    },
                    params={
                        "user_id": f"eq.{session_context['user_id']}",
                        "site_id": f"eq.{site_id}",
                        "status": "eq.active",
                        "and": f"(signed_on_at.gte.{today_start.isoformat()},signed_on_at.lte.{today_end.isoformat()})",
                        "select": "id",
                        "limit": "1",
                    }
                )

                if signon_resp.status_code == 200 and signon_resp.json():
                    signon_id = signon_resp.json()[0]["id"]
                    close_resp = await client.patch(
                        f"{settings.SUPABASE_URL}/rest/v1/site_signons",
                        headers={
                            "apikey": settings.SUPABASE_SERVICE_KEY,
                            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
                            "Content-Type": "application/json",
                        },
                        params={"id": f"eq.{signon_id}"},
                        json={
                            "status": "signed_off",
                            "signed_off_at": datetime.now(tz).isoformat(),
                            "signoff_method": "jill_timesheet",
                            "timesheet_id": timesheet_entry["id"],
                        }
                    )
                    if close_resp.status_code in (200, 204):
                        logger.info(f"Auto-closed sign-on {signon_id} via timesheet save")
                    else:
                        logger.warning(f"Failed to close sign-on {signon_id}: {close_resp.status_code}")
        except Exception as signon_err:
            logger.warning(f"Non-fatal: failed to auto-close sign-on: {signon_err}")

        return {
            "results": [{
                "toolCallId": tool_call_id,
                "result": {
                    "success": True,
                    "entry_id": timesheet_entry['id'],
                    "hours_worked": hours_worked,
                    "message": f"Got it! I've logged {hours_worked} hours for that site."
                }
            }]
        }

    except Exception as e:
        logger.error(f"Error in save_timesheet_entry: {str(e)}", exc_info=True)
        return {
            "results": [{
                "toolCallId": tool_call_id,
                "result": {
                    "success": False,
                    "error": str(e),
                    "message": "I encountered an error saving your timesheet. Please try again."
                }
            }]
        }


@router.post("/api/v1/skills/timesheet/confirm-all")
async def confirm_and_save_all(request: dict):
    """
    Finalize all timesheet entries for this call
    This is called after all sites have been logged and user confirms
    """
    try:
        # Extract VAPI arguments
        tool_call_id, args = extract_vapi_args(request)

        # Extract call ID
        vapi_call_id = None
        if "message" in request and "call" in request["message"]:
            vapi_call_id = request["message"]["call"]["id"]

        if not vapi_call_id:
            vapi_call_id = args.get("vapi_call_id", tool_call_id)

        user_confirmed = args.get("user_confirmed", False)

        logger.info(f"Confirming timesheet entries. Call: {vapi_call_id}, Confirmed: {user_confirmed}")

        if not user_confirmed:
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "success": False,
                        "message": "No problem, let's make corrections. What needs to be changed?"
                    }
                }]
            }

        # Get session context
        session_context = await get_session_context_by_call_id(vapi_call_id)

        if not session_context:
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "success": False,
                        "error": "Session not found"
                    }
                }]
            }

        # Get all timesheet entries for this call
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.SUPABASE_URL}/rest/v1/timesheets",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
                },
                params={
                    "vapi_call_id": f"eq.{vapi_call_id}",
                    "select": "id,hours_worked,site_id,entities(name)"
                }
            )

            if response.status_code == 200:
                entries = response.json()
                total_hours = sum(entry.get('hours_worked', 0) for entry in entries)
                num_sites = len(entries)

                logger.info(f"Confirmed {num_sites} timesheet entries totaling {total_hours} hours")

                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "success": True,
                            "total_entries": num_sites,
                            "total_hours": total_hours,
                            "message": f"Perfect! I've saved your timesheet for {num_sites} site{'s' if num_sites > 1 else ''}, totaling {total_hours} hours. Have a great day!"
                        }
                    }]
                }
            else:
                logger.error(f"Failed to retrieve entries: {response.status_code}")
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "success": True,
                            "message": "Your timesheet has been saved. Have a great day!"
                        }
                    }]
                }

    except Exception as e:
        logger.error(f"Error in confirm_and_save_all: {str(e)}", exc_info=True)
        return {
            "results": [{
                "toolCallId": tool_call_id,
                "result": {
                    "success": True,
                    "message": "Your timesheet has been saved. Have a great day!"
                }
            }]
        }


@router.post("/api/v1/skills/timesheet/get-recent-timesheets")
async def get_recent_timesheets(request: dict):
    """
    Get summary of recently logged timesheets for the user

    Used when user asks "what have I logged this week?" or for proactive checking
    Returns brief summary of dates with timesheets in last N days
    """
    try:
        tool_call_id, args = extract_vapi_args(request)

        vapi_call_id = None
        if "message" in request and "call" in request["message"]:
            vapi_call_id = request["message"]["call"]["id"]

        if not vapi_call_id:
            vapi_call_id = tool_call_id

        days_back = args.get("days_back", 14)  # Default 2 weeks

        logger.info(f"Getting recent timesheets. Call: {vapi_call_id}, days_back: {days_back}")

        session_context = await get_session_context_by_call_id(vapi_call_id)

        if not session_context:
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "has_timesheets": False,
                        "message": "I couldn't find your session. Please try again."
                    }
                }]
            }

        user_id = session_context["user_id"]
        tenant_timezone = session_context.get("tenant_timezone", "Australia/Sydney")
        current_date = session_context.get("current_date")

        # Calculate date range
        from datetime import timedelta
        tz = ZoneInfo(tenant_timezone)

        # If current_date is not available, calculate it from tenant timezone
        if current_date:
            end_date = datetime.strptime(current_date, '%Y-%m-%d')
        else:
            # Fallback: use current date in tenant timezone
            end_date = datetime.now(tz)
            logger.warning(f"current_date not in session context, using calculated date: {end_date.strftime('%Y-%m-%d')}")

        start_date = end_date - timedelta(days=days_back - 1)

        async with httpx.AsyncClient() as client:
            # Get timesheets grouped by date
            response = await client.get(
                f"{settings.SUPABASE_URL}/rest/v1/timesheets",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
                },
                params={
                    "user_id": f"eq.{user_id}",
                    "work_date": f"gte.{start_date.strftime('%Y-%m-%d')}",
                    "select": "work_date,hours_worked,site_id,entities!inner(name)",
                    "order": "work_date.desc"
                }
            )

            if response.status_code != 200:
                logger.error(f"Failed to fetch timesheets: {response.status_code}")
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "has_timesheets": False,
                            "message": "I couldn't retrieve your timesheet history."
                        }
                    }]
                }

            timesheets = response.json()

            if not timesheets:
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "has_timesheets": False,
                            "days_checked": days_back,
                            "message": f"You haven't logged any timesheets in the last {days_back} days."
                        }
                    }]
                }

            # Group by date
            from collections import defaultdict
            dates_summary = defaultdict(lambda: {"count": 0, "total_hours": 0.0, "sites": []})

            for entry in timesheets:
                work_date = entry['work_date']
                site_name = entry['entities']['name']
                hours = float(entry['hours_worked'])

                dates_summary[work_date]["count"] += 1
                dates_summary[work_date]["total_hours"] += hours
                dates_summary[work_date]["sites"].append(site_name)

            # Format for response - convert to day names
            logged_days = []
            for work_date_str in sorted(dates_summary.keys(), reverse=True):
                work_date_obj = datetime.strptime(work_date_str, '%Y-%m-%d')
                day_name = work_date_obj.strftime('%A')

                # Calculate days ago
                days_ago = (end_date - work_date_obj).days

                if days_ago == 0:
                    day_label = "today"
                elif days_ago == 1:
                    day_label = "yesterday"
                else:
                    day_label = day_name

                logged_days.append({
                    "date": work_date_str,
                    "day_label": day_label,
                    "days_ago": days_ago,
                    "site_count": dates_summary[work_date_str]["count"],
                    "total_hours": dates_summary[work_date_str]["total_hours"],
                    "sites": dates_summary[work_date_str]["sites"]
                })

            # Create natural language summary
            if len(logged_days) == 1:
                summary = f"You've logged time for {logged_days[0]['day_label']}"
            elif len(logged_days) == 2:
                summary = f"You've logged time for {logged_days[0]['day_label']} and {logged_days[1]['day_label']}"
            else:
                day_labels = [d['day_label'] for d in logged_days[:3]]  # First 3
                if len(logged_days) > 3:
                    summary = f"You've logged time for {', '.join(day_labels)}, and {len(logged_days) - 3} other day(s)"
                else:
                    summary = f"You've logged time for {', '.join(day_labels[:-1])}, and {day_labels[-1]}"

            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "has_timesheets": True,
                        "days_checked": days_back,
                        "total_days_logged": len(logged_days),
                        "logged_days": logged_days,
                        "summary": summary,
                        "message": summary + "."
                    }
                }]
            }

    except Exception as e:
        logger.error(f"Error in get_recent_timesheets: {str(e)}", exc_info=True)
        return {
            "results": [{
                "toolCallId": tool_call_id,
                "result": {
                    "has_timesheets": False,
                    "error": str(e),
                    "message": "I had trouble checking your timesheet history. Let's continue anyway."
                }
            }]
        }

@router.post("/api/v1/skills/timesheet/check-date-conflicts")
async def check_date_for_conflicts(request: dict):
    """
    Check if timesheets already exist for a specific date
    
    Returns existing entries for that date to detect conflicts
    Used before logging historical timesheets
    """
    try:
        tool_call_id, args = extract_vapi_args(request)
        
        vapi_call_id = None
        if "message" in request and "call" in request["message"]:
            vapi_call_id = request["message"]["call"]["id"]
        
        if not vapi_call_id:
            vapi_call_id = tool_call_id
        
        work_date = args.get("work_date")  # ISO format YYYY-MM-DD
        site_id = args.get("site_id")  # Optional - check specific site
        
        if not work_date:
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "has_conflicts": False,
                        "error": "work_date is required",
                        "message": "I need a date to check for existing timesheets."
                    }
                }]
            }
        
        logger.info(f"Checking conflicts for date: {work_date}, site: {site_id}, call: {vapi_call_id}")
        
        session_context = await get_session_context_by_call_id(vapi_call_id)
        
        if not session_context:
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "has_conflicts": False,
                        "message": "I couldn't find your session."
                    }
                }]
            }
        
        user_id = session_context["user_id"]
        
        async with httpx.AsyncClient() as client:
            # Build query params
            params = {
                "user_id": f"eq.{user_id}",
                "work_date": f"eq.{work_date}",
                "select": "id,site_id,start_time,end_time,hours_worked,work_description,entities!inner(name)",
                "order": "start_time.asc"
            }
            
            # Optionally filter by site
            if site_id:
                params["site_id"] = f"eq.{site_id}"
            
            response = await client.get(
                f"{settings.SUPABASE_URL}/rest/v1/timesheets",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
                },
                params=params
            )
            
            if response.status_code != 200:
                logger.error(f"Failed to check conflicts: {response.status_code}")
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "has_conflicts": False,
                            "message": "I couldn't check for existing timesheets."
                        }
                    }]
                }
            
            existing_entries = response.json()
            
            if not existing_entries:
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "has_conflicts": False,
                            "work_date": work_date,
                            "message": f"No existing timesheets found for {work_date}."
                        }
                    }]
                }
            
            # Format existing entries for assistant
            entries_summary = []
            total_hours = 0.0
            
            for entry in existing_entries:
                site_name = entry['entities']['name']
                start_time = entry['start_time']
                end_time = entry['end_time']
                hours = float(entry['hours_worked'])
                total_hours += hours
                
                entries_summary.append({
                    "timesheet_id": entry['id'],
                    "site_id": entry['site_id'],
                    "site_name": site_name,
                    "start_time": start_time,
                    "end_time": end_time,
                    "hours_worked": hours,
                    "work_description": entry.get('work_description', '')
                })
            
            # Create natural language summary
            if len(entries_summary) == 1:
                entry = entries_summary[0]
                summary = f"{entry['site_name']}, {entry['hours_worked']} hours ({entry['start_time']} to {entry['end_time']})"
            else:
                site_names = [e['site_name'] for e in entries_summary]
                summary = f"{len(entries_summary)} entries: {', '.join(set(site_names))}, total {total_hours} hours"
            
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "has_conflicts": True,
                        "work_date": work_date,
                        "entry_count": len(entries_summary),
                        "total_hours": total_hours,
                        "existing_entries": entries_summary,
                        "summary": summary,
                        "message": f"I already have {summary} logged for {work_date}."
                    }
                }]
            }
    
    except Exception as e:
        logger.error(f"Error in check_date_for_conflicts: {str(e)}", exc_info=True)
        return {
            "results": [{
                "toolCallId": tool_call_id,
                "result": {
                    "has_conflicts": False,
                    "error": str(e),
                    "message": "I had trouble checking for existing entries. Let's continue anyway."
                }
            }]
        }


@router.post("/api/v1/skills/timesheet/update-entry")
async def update_timesheet_entry(request: dict):
    """
    Update an existing timesheet entry
    
    Used when user wants to correct/overwrite an existing entry
    """
    try:
        tool_call_id, args = extract_vapi_args(request)
        
        vapi_call_id = None
        if "message" in request and "call" in request["message"]:
            vapi_call_id = request["message"]["call"]["id"]
        
        if not vapi_call_id:
            vapi_call_id = tool_call_id
        
        timesheet_id = args.get("timesheet_id")
        start_time = args.get("start_time")  # HH:MM format
        end_time = args.get("end_time")  # HH:MM format
        work_description = args.get("work_description", "")
        plans_for_tomorrow = args.get("plans_for_tomorrow", "")
        
        if not timesheet_id:
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "success": False,
                        "error": "timesheet_id is required",
                        "message": "I need the timesheet ID to update."
                    }
                }]
            }
        
        if not start_time or not end_time:
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "success": False,
                        "error": "start_time and end_time are required",
                        "message": "I need both start and end times to update the entry."
                    }
                }]
            }
        
        logger.info(f"Updating timesheet {timesheet_id}: {start_time}-{end_time}")
        
        # Calculate hours worked
        hours_worked = calculate_hours_worked(start_time, end_time)
        
        async with httpx.AsyncClient() as client:
            # Update the entry
            update_data = {
                "start_time": start_time,
                "end_time": end_time,
                "hours_worked": hours_worked,
                "work_description": work_description,
                "plans_for_tomorrow": plans_for_tomorrow
            }
            
            response = await client.patch(
                f"{settings.SUPABASE_URL}/rest/v1/timesheets",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation"
                },
                params={"id": f"eq.{timesheet_id}"},
                json=update_data
            )
            
            if response.status_code not in (200, 204):
                logger.error(f"Failed to update timesheet: {response.status_code} - {response.text}")
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "success": False,
                            "error": f"Database error: {response.status_code}",
                            "message": "I had trouble updating that timesheet entry."
                        }
                    }]
                }
            
            updated_entry = response.json()[0] if response.json() else {}
            
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "success": True,
                        "timesheet_id": timesheet_id,
                        "hours_worked": hours_worked,
                        "start_time": start_time,
                        "end_time": end_time,
                        "message": f"Updated! That's now {hours_worked} hours from {start_time} to {end_time}."
                    }
                }]
            }
    
    except Exception as e:
        logger.error(f"Error in update_timesheet_entry: {str(e)}", exc_info=True)
        return {
            "results": [{
                "toolCallId": tool_call_id,
                "result": {
                    "success": False,
                    "error": str(e),
                    "message": "I had trouble updating that entry."
                }
            }]
        }


@router.post("/api/v1/skills/timesheet/get-signon-data")
async def get_signon_data(request: dict):
    """
    Get today's QR sign-on data for the authenticated caller.

    Called by Jill immediately after greeting to check if the user
    signed on at any sites today via QR code. If so, Jill can skip
    site identification and pre-fill start times.
    """
    try:
        tool_call_id, args = extract_vapi_args(request)

        vapi_call_id = None
        if "message" in request and "call" in request["message"]:
            vapi_call_id = request["message"]["call"]["id"]

        if not vapi_call_id:
            vapi_call_id = tool_call_id

        logger.info(f"Getting sign-on data. Call: {vapi_call_id}")

        session_context = await get_session_context_by_call_id(vapi_call_id)

        if not session_context:
            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "has_signons": False,
                        "message": "Session not found."
                    }
                }]
            }

        user_id = session_context["user_id"]
        tenant_id = session_context["tenant_id"]
        tenant_timezone = session_context.get("tenant_timezone", "Australia/Sydney")
        current_date = session_context.get("current_date")

        # Calculate today's date in tenant timezone if not in session
        if not current_date:
            tz = ZoneInfo(tenant_timezone)
            current_date = datetime.now(tz).strftime('%Y-%m-%d')

        # Query site_signons for today
        tz = ZoneInfo(tenant_timezone)
        today_naive = datetime.strptime(current_date, '%Y-%m-%d')
        today_start = today_naive.replace(hour=0, minute=0, second=0, tzinfo=tz)
        today_end = today_naive.replace(hour=23, minute=59, second=59, tzinfo=tz)

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.SUPABASE_URL}/rest/v1/site_signons",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
                },
                params={
                    "user_id": f"eq.{user_id}",
                    "tenant_id": f"eq.{tenant_id}",
                    "status": "in.(active,signed_off)",
                    "and": f"(signed_on_at.gte.{today_start.isoformat()},signed_on_at.lte.{today_end.isoformat()})",
                    "select": "id,site_id,signed_on_at,signed_off_at,status",
                    "order": "signed_on_at.asc",
                }
            )

            if resp.status_code != 200:
                logger.error(f"Failed to query site_signons: {resp.status_code} - {resp.text}")
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "has_signons": False,
                            "signon_count": 0,
                            "signons": [],
                            "message": "No sign-on data available."
                        }
                    }]
                }

            signons = resp.json()

            if not signons:
                return {
                    "results": [{
                        "toolCallId": tool_call_id,
                        "result": {
                            "has_signons": False,
                            "signon_count": 0,
                            "signons": [],
                            "message": "No sign-on data for today."
                        }
                    }]
                }

            # Enrich with site names
            site_ids = list(set(s["site_id"] for s in signons))
            sites_resp = await client.get(
                f"{settings.SUPABASE_URL}/rest/v1/entities",
                headers={
                    "apikey": settings.SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
                },
                params={
                    "id": f"in.({','.join(site_ids)})",
                    "select": "id,name",
                }
            )
            site_map = {}
            if sites_resp.status_code == 200:
                site_map = {s["id"]: s["name"] for s in sites_resp.json()}

            # Format sign-on times in tenant timezone for natural speech
            signon_list = []
            for s in signons:
                signed_on_dt = datetime.fromisoformat(s["signed_on_at"].replace("Z", "+00:00"))
                signed_on_local = signed_on_dt.astimezone(tz)
                time_str = signed_on_local.strftime("%-I:%M %p").lower()  # e.g. "7:30 am"

                signon_list.append({
                    "signon_id": s["id"],
                    "site_id": s["site_id"],
                    "site_name": site_map.get(s["site_id"], "Unknown site"),
                    "signed_on_at": s["signed_on_at"],
                    "signed_on_time": time_str,
                    "status": s["status"],
                })

            logger.info(f"Found {len(signon_list)} sign-ons for user {user_id} today")

            return {
                "results": [{
                    "toolCallId": tool_call_id,
                    "result": {
                        "has_signons": True,
                        "signon_count": len(signon_list),
                        "signons": signon_list,
                        "message": f"Found {len(signon_list)} sign-on(s) for today."
                    }
                }]
            }

    except Exception as e:
        logger.error(f"Error in get_signon_data: {str(e)}", exc_info=True)
        return {
            "results": [{
                "toolCallId": tool_call_id,
                "result": {
                    "has_signons": False,
                    "signon_count": 0,
                    "signons": [],
                    "error": str(e),
                    "message": "Could not check sign-on data. Continuing normally."
                }
            }]
        }
