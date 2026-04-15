# app/admin/routes.py - Admin UI routes
from fastapi import APIRouter, Request, Depends, HTTPException, Header, BackgroundTasks, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
import asyncio
import httpx
import os
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/admin/templates")

# ============================================
# AUTHENTICATION MIDDLEWARE
# ============================================

# Super admin key from environment
SUPER_ADMIN_KEY = os.getenv("SUPER_ADMIN_API_KEY", "super-admin-change-me")
logger.info(f"Super admin key loaded: {SUPER_ADMIN_KEY[:10]}... (length: {len(SUPER_ADMIN_KEY)})")

async def get_current_admin_user(
    authorization: str = Header(None),
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID")
):
    """
    Verify admin access via API key
    Supports both tenant API keys and super-admin key
    Super-admin can switch tenants via X-Tenant-ID header
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    api_key = authorization.replace("Bearer ", "")

    try:
        # Check if super admin
        if api_key == SUPER_ADMIN_KEY:
            # Super admin mode
            result = {
                "is_super_admin": True,
                "tenant_id": x_tenant_id,  # Can be None (all tenants) or specific tenant
                "tenant_name": "JOURN3Y Super Admin",
                "can_switch_tenants": True
            }

            # If viewing a specific tenant, get tenant name
            if x_tenant_id:
                async with httpx.AsyncClient() as client:
                    tenant_response = await client.get(
                        f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                        headers={
                            "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                            "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                        },
                        params={"id": f"eq.{x_tenant_id}", "select": "name"}
                    )
                    if tenant_response.status_code == 200:
                        tenants = tenant_response.json()
                        if tenants:
                            result["tenant_name"] = tenants[0]["name"]

            return result

        # Regular tenant authentication
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/authenticate_tenant_by_api_key",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json"
                },
                json={"api_key_input": api_key}
            )

            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid API key")

            tenant_id = response.json()
            if not tenant_id:
                raise HTTPException(status_code=401, detail="Invalid API key")

            # Get tenant info
            tenant_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={"id": f"eq.{tenant_id}", "select": "id,name,created_at"}
            )

            tenant_name = "Unknown"
            if tenant_response.status_code == 200:
                tenants = tenant_response.json()
                if tenants:
                    tenant_name = tenants[0]["name"]

            return {
                "is_super_admin": False,
                "tenant_id": tenant_id,
                "tenant_name": tenant_name,
                "can_switch_tenants": False
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin authentication error: {e}")
        raise HTTPException(status_code=500, detail="Authentication system error")

# ============================================
# LOGIN PAGE
# ============================================

@router.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page"""
    # If already authenticated, redirect to dashboard
    user_session = request.session.get("user")
    if user_session:
        if user_session.get("must_change_password"):
            return RedirectResponse(url="/admin/change-password", status_code=302)
        return RedirectResponse(url="/admin", status_code=302)

    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request}
    )


@router.get("/admin/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request):
    """Change password page - used for forced first-login and voluntary changes"""
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)

    forced = user_session.get("must_change_password", False)
    return templates.TemplateResponse(
        "auth/change_password.html",
        {"request": request, "forced": forced}
    )

# ============================================
# DASHBOARD
# ============================================

@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, theme: Optional[str] = None):
    """Main admin dashboard - redirects to login if not authenticated"""
    # Check if authenticated
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    if user_session.get("must_change_password"):
        return RedirectResponse(url="/admin/change-password", status_code=302)

    # Choose template based on theme parameter
    template = "dashboard/index-modern.html" if theme == "modern" else "dashboard/index.html"

    return templates.TemplateResponse(
        template,
        {"request": request, "page_title": "Admin Dashboard"}
    )

@router.get("/admin/help", response_class=HTMLResponse)
async def help_page(request: Request):
    """Help & Guides page"""
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    if user_session.get("must_change_password"):
        return RedirectResponse(url="/admin/change-password", status_code=302)

    return templates.TemplateResponse(
        "help/index.html",
        {"request": request, "page_title": "Help & Guides"}
    )

async def get_session_user(request: Request) -> dict:
    """Get current user from session"""
    user_session = request.session.get("user")
    if not user_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_session

@router.get("/admin/dashboard/stats")
async def get_dashboard_stats(request: Request):
    """Get dashboard statistics"""
    user_session = await get_session_user(request)
    tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    # Super admin without tenant selected sees aggregate stats
    if is_super_admin and not tenant_id:
        try:
            async with httpx.AsyncClient() as client:
                # Get total counts across all tenants
                users_response = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                    },
                    params={"select": "id"}
                )
                user_count = len(users_response.json()) if users_response.status_code == 200 else 0

                # Get tenant count
                tenants_response = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                    },
                    params={"select": "id"}
                )
                tenant_count = len(tenants_response.json()) if tenants_response.status_code == 200 else 0

                return {
                    "success": True,
                    "stats": {
                        "tenants": tenant_count,
                        "users": user_count,
                        "sites": 0,  # Aggregate calculation can be added
                        "voice_notes": 0,
                        "timesheet_entries": 0
                    },
                    "tenant_name": "All Tenants",
                    "is_super_admin": True
                }
        except Exception as e:
            logger.error(f"Error fetching super admin stats: {e}")
            return {"success": False, "error": str(e)}

    try:
        async with httpx.AsyncClient() as client:
            # Get user count
            users_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={"tenant_id": f"eq.{tenant_id}", "select": "id"}
            )
            user_count = len(users_response.json()) if users_response.status_code == 200 else 0

            # Get site count
            sites_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/entities",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={"tenant_id": f"eq.{tenant_id}", "entity_type": "eq.sites", "select": "id"}
            )
            site_count = len(sites_response.json()) if sites_response.status_code == 200 else 0

            # Get voice notes count
            notes_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/voice_notes",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={"tenant_id": f"eq.{tenant_id}", "select": "id"}
            )
            notes_count = len(notes_response.json()) if notes_response.status_code == 200 else 0

            # Get timesheet entries count (if table exists)
            timesheet_count = 0
            try:
                timesheet_response = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/timesheet_entries",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                    },
                    params={"tenant_id": f"eq.{tenant_id}", "select": "id"}
                )
                if timesheet_response.status_code == 200:
                    timesheet_count = len(timesheet_response.json())
            except:
                pass

            return {
                "success": True,
                "stats": {
                    "users": user_count,
                    "sites": site_count,
                    "voice_notes": notes_count,
                    "timesheet_entries": timesheet_count
                },
                "tenant_name": user_session.get("tenant_name", "Unknown")
            }

    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {e}")
        return {"success": False, "error": str(e)}

# ============================================
# TENANT MANAGEMENT
# ============================================

@router.get("/admin/tenants", response_class=HTMLResponse)
async def list_tenants_page(request: Request, theme: Optional[str] = None):
    """Tenants management page"""
    # Check if authenticated
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)

    # Choose template based on theme parameter
    template = "tenants/list-modern.html" if theme == "modern" else "tenants/list.html"

    return templates.TemplateResponse(
        template,
        {"request": request, "page_title": "Tenant Management"}
    )

@router.get("/admin/tenants/data")
async def get_tenants_data(request: Request):
    """Get tenants data (HTMX endpoint)"""
    user_session = await get_session_user(request)
    tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    try:
        async with httpx.AsyncClient() as client:
            # Super admin sees all tenants
            if is_super_admin:
                if tenant_id:
                    # Viewing specific tenant
                    params = {"id": f"eq.{tenant_id}", "select": "id,name,created_at,timezone"}
                else:
                    # Viewing all tenants
                    params = {"select": "id,name,created_at,timezone", "order": "created_at.desc"}
            else:
                # Regular tenant admin sees only their tenant
                params = {"id": f"eq.{tenant_id}", "select": "id,name,created_at,timezone"}

            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params=params
            )

            if response.status_code == 200:
                tenants = response.json()

                # Enrich each tenant with enabled skills count
                for tenant in tenants:
                    skills_count_resp = await client.get(
                        f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_skills",
                        headers={
                            "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                            "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                        },
                        params={
                            "tenant_id": f"eq.{tenant['id']}",
                            "is_enabled": "eq.true",
                            "select": "id"
                        }
                    )
                    tenant["enabled_skills_count"] = len(skills_count_resp.json()) if skills_count_resp.status_code == 200 else 0

                return {
                    "success": True,
                    "tenants": tenants,
                    "is_super_admin": is_super_admin
                }
            else:
                return {"success": False, "error": "Failed to fetch tenants"}

    except Exception as e:
        logger.error(f"Error fetching tenants: {e}")
        return {"success": False, "error": str(e)}

# ============================================
# TENANT SKILL MANAGEMENT
# ============================================

@router.get("/admin/tenants/{tenant_id}/skills")
async def get_tenant_skills(tenant_id: str, request: Request):
    """Get all skills with their enabled/disabled status for a tenant (super admin only)"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        return {"success": False, "error": "Super admin access required"}

    try:
        async with httpx.AsyncClient() as client:
            # Get ALL global skills
            all_skills_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/skills",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={"select": "id,skill_key,name,description", "order": "name.asc"}
            )

            # Get this tenant's enabled skills
            tenant_skills_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_skills",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "is_enabled": "eq.true",
                    "select": "skill_id"
                }
            )

            if all_skills_resp.status_code == 200 and tenant_skills_resp.status_code == 200:
                all_skills = all_skills_resp.json()
                enabled_ids = {ts["skill_id"] for ts in tenant_skills_resp.json()}

                for skill in all_skills:
                    skill["is_enabled"] = skill["id"] in enabled_ids

                return {"success": True, "skills": all_skills}
            else:
                return {"success": False, "error": "Failed to fetch skills"}

    except Exception as e:
        logger.error(f"Error fetching tenant skills: {e}")
        return {"success": False, "error": str(e)}

@router.post("/admin/tenants/{tenant_id}/skills/{skill_id}/toggle")
async def toggle_tenant_skill(tenant_id: str, skill_id: str, request: Request):
    """Enable or disable a skill for a tenant (super admin only)"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        return {"success": False, "error": "Super admin access required"}

    try:
        async with httpx.AsyncClient() as client:
            # Check if tenant_skills record exists
            check_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_skills",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "skill_id": f"eq.{skill_id}"
                }
            )

            if check_resp.status_code == 200 and check_resp.json():
                # Record exists - toggle is_enabled
                current = check_resp.json()[0]
                new_status = not current["is_enabled"]

                update_resp = await client.patch(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_skills",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal"
                    },
                    params={
                        "tenant_id": f"eq.{tenant_id}",
                        "skill_id": f"eq.{skill_id}"
                    },
                    json={"is_enabled": new_status}
                )

                if update_resp.status_code in [200, 204]:
                    return {"success": True, "is_enabled": new_status}
                else:
                    return {"success": False, "error": "Failed to update skill status"}
            else:
                # Record doesn't exist - create as enabled
                import uuid
                create_resp = await client.post(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_skills",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal"
                    },
                    json={
                        "id": str(uuid.uuid4()),
                        "tenant_id": tenant_id,
                        "skill_id": skill_id,
                        "is_enabled": True
                    }
                )

                if create_resp.status_code in [200, 201]:
                    return {"success": True, "is_enabled": True}
                else:
                    return {"success": False, "error": "Failed to create tenant skill"}

    except Exception as e:
        logger.error(f"Error toggling tenant skill: {e}")
        return {"success": False, "error": str(e)}

@router.get("/admin/tenants/{tenant_id}/skills/{skill_id}/affected-users")
async def get_affected_users(tenant_id: str, skill_id: str, request: Request):
    """Get users who currently have this skill assigned (for confirmation before disable)"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        return {"success": False, "error": "Super admin access required"}

    try:
        async with httpx.AsyncClient() as client:
            # Get users in this tenant
            users_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "select": "id,name"
                }
            )

            if users_resp.status_code != 200:
                return {"success": False, "error": "Failed to fetch users"}

            tenant_users = users_resp.json()
            if not tenant_users:
                return {"success": True, "affected_users": [], "count": 0}

            user_ids = [u["id"] for u in tenant_users]
            user_name_map = {u["id"]: u["name"] for u in tenant_users}

            # Get user_skills for these users with this skill
            user_skills_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/user_skills",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "user_id": f"in.({','.join(user_ids)})",
                    "skill_id": f"eq.{skill_id}",
                    "is_enabled": "eq.true",
                    "select": "user_id"
                }
            )

            if user_skills_resp.status_code == 200:
                affected = [
                    {"id": us["user_id"], "name": user_name_map.get(us["user_id"], "Unknown")}
                    for us in user_skills_resp.json()
                ]
                return {"success": True, "affected_users": affected, "count": len(affected)}
            else:
                return {"success": False, "error": "Failed to fetch user skills"}

    except Exception as e:
        logger.error(f"Error fetching affected users: {e}")
        return {"success": False, "error": str(e)}

# ============================================
# USER MANAGEMENT
# ============================================

@router.get("/admin/users", response_class=HTMLResponse)
async def list_users_page(request: Request, theme: Optional[str] = None):
    """Users management page"""
    # Check if authenticated
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)

    # Choose template based on theme parameter
    template = "users/list-modern.html" if theme == "modern" else "users/list.html"

    return templates.TemplateResponse(
        template,
        {"request": request, "page_title": "User Management"}
    )

@router.get("/admin/api/tenants-list")
async def get_tenants_list(request: Request):
    """Get list of all tenants (for tenant switcher dropdown)"""
    user_session = await get_session_user(request)
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        return {"success": False, "error": "Unauthorized"}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={"select": "id,name", "order": "name.asc"}
            )

            if response.status_code == 200:
                tenants = response.json()
                return {"success": True, "tenants": tenants}
            else:
                return {"success": False, "error": "Failed to fetch tenants"}

    except Exception as e:
        logger.error(f"Error fetching tenants list: {e}")
        return {"success": False, "error": str(e)}

@router.get("/admin/users/data")
async def get_users_data(
    request: Request,
    tenant_id: Optional[str] = None
):
    """Get users data (HTMX endpoint)"""
    user_session = await get_session_user(request)
    session_tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    # For tenant admins, always use their tenant_id
    # For super admins, use the query parameter if provided, otherwise show all
    if not is_super_admin:
        tenant_id = session_tenant_id
    # else: use the tenant_id from query params (can be None for "all tenants")

    # Super admin without tenant selected sees all users
    if is_super_admin and not tenant_id:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                    },
                    params={
                        "select": "id,name,phone_number,email,role,is_active,sms_reminders_enabled,created_at,tenants(name)",
                        "order": "created_at.desc",
                        "limit": "100"
                    }
                )

                if response.status_code == 200:
                    users = response.json()

                    # Add tenant names
                    for user in users:
                        user["tenant_name"] = user.get("tenants", {}).get("name", "Unknown") if user.get("tenants") else "Unknown"
                        user["skills"] = []  # Initialize

                    # Batch fetch all skills for all users in ONE query
                    if users:
                        user_ids = [u["id"] for u in users]
                        skills_response = await client.get(
                            f"{os.getenv('SUPABASE_URL')}/rest/v1/user_skills",
                            headers={
                                "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                            },
                            params={
                                "user_id": f"in.({','.join(user_ids)})",
                                "is_enabled": "eq.true",
                                "select": "user_id,skills(id,skill_key,name)"
                            }
                        )

                        if skills_response.status_code == 200:
                            all_skills = skills_response.json()
                            # Group skills by user_id
                            skills_by_user = {}
                            for item in all_skills:
                                if item.get("skills"):
                                    user_id = item["user_id"]
                                    if user_id not in skills_by_user:
                                        skills_by_user[user_id] = []
                                    skills_by_user[user_id].append({
                                        "id": item["skills"]["id"],
                                        "key": item["skills"]["skill_key"],
                                        "name": item["skills"]["name"]
                                    })

                            # Assign skills to users
                            for user in users:
                                user["skills"] = skills_by_user.get(user["id"], [])

                    return {"success": True, "users": users, "is_super_admin": True}
                else:
                    return {"success": False, "error": "Failed to fetch users"}
        except Exception as e:
            logger.error(f"Error fetching all users: {e}")
            return {"success": False, "error": str(e)}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "select": "id,name,phone_number,email,role,is_active,sms_reminders_enabled,created_at",
                    "order": "created_at.desc"
                }
            )

            if response.status_code == 200:
                users = response.json()

                # Initialize skills array for all users
                for user in users:
                    user["skills"] = []

                # Batch fetch all skills for all users in ONE query
                if users:
                    user_ids = [u["id"] for u in users]
                    skills_response = await client.get(
                        f"{os.getenv('SUPABASE_URL')}/rest/v1/user_skills",
                        headers={
                            "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                            "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                        },
                        params={
                            "user_id": f"in.({','.join(user_ids)})",
                            "is_enabled": "eq.true",
                            "select": "user_id,skills(id,skill_key,name)"
                        }
                    )

                    if skills_response.status_code == 200:
                        all_skills = skills_response.json()
                        # Group skills by user_id
                        skills_by_user = {}
                        for item in all_skills:
                            if item.get("skills"):
                                user_id = item["user_id"]
                                if user_id not in skills_by_user:
                                    skills_by_user[user_id] = []
                                skills_by_user[user_id].append({
                                    "id": item["skills"]["id"],
                                    "key": item["skills"]["skill_key"],
                                    "name": item["skills"]["name"]
                                })

                        # Assign skills to users
                        for user in users:
                            user["skills"] = skills_by_user.get(user["id"], [])

                return {"success": True, "users": users}
            else:
                return {"success": False, "error": "Failed to fetch users"}

    except Exception as e:
        logger.error(f"Error fetching users: {e}")
        return {"success": False, "error": str(e)}

@router.post("/admin/users/{user_id}/toggle-active")
async def toggle_user_active(
    user_id: str,
    request: Request
):
    """Toggle user active status (HTMX endpoint)"""
    user_session = await get_session_user(request)
    tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    try:
        async with httpx.AsyncClient() as client:
            # Get current status
            params = {"id": f"eq.{user_id}", "select": "is_active"}
            # Only filter by tenant_id if user is not super admin
            if not is_super_admin and tenant_id:
                params["tenant_id"] = f"eq.{tenant_id}"

            get_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params=params
            )

            if get_response.status_code != 200 or not get_response.json():
                return {"success": False, "error": "User not found"}

            current_status = get_response.json()[0]["is_active"]
            new_status = not current_status

            # Update status
            update_response = await client.patch(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                params={"id": f"eq.{user_id}"},
                json={"is_active": new_status}
            )

            if update_response.status_code in [200, 204]:
                return {"success": True, "is_active": new_status}
            else:
                return {"success": False, "error": "Failed to update user"}

    except Exception as e:
        logger.error(f"Error toggling user status: {e}")
        return {"success": False, "error": str(e)}

@router.get("/admin/users/{user_id}/available-skills")
async def get_available_skills_for_user(
    user_id: str,
    request: Request
):
    """Get available skills that are enabled for the user's tenant and not yet assigned"""
    user_session = await get_session_user(request)
    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # Get user's tenant_id
            user_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                headers=headers,
                params={"id": f"eq.{user_id}", "select": "tenant_id"}
            )
            if user_response.status_code != 200 or not user_response.json():
                return {"success": False, "error": "User not found"}

            user_tenant_id = user_response.json()[0]["tenant_id"]

            # Get skills enabled for this tenant (via tenant_skills join)
            tenant_skills_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_skills",
                headers=headers,
                params={
                    "tenant_id": f"eq.{user_tenant_id}",
                    "is_enabled": "eq.true",
                    "select": "skills(id,skill_key,name)"
                }
            )

            # Get user's current skills
            user_skills_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/user_skills",
                headers=headers,
                params={
                    "user_id": f"eq.{user_id}",
                    "is_enabled": "eq.true",
                    "select": "skill_id"
                }
            )

            if tenant_skills_response.status_code == 200 and user_skills_response.status_code == 200:
                tenant_skills = [ts["skills"] for ts in tenant_skills_response.json() if ts.get("skills")]
                user_skill_ids = {s["skill_id"] for s in user_skills_response.json()}

                # Filter out skills user already has
                available = [s for s in tenant_skills if s["id"] not in user_skill_ids]

                return {"success": True, "skills": available}
            else:
                return {"success": False, "error": "Failed to fetch skills"}

    except Exception as e:
        logger.error(f"Error fetching available skills: {e}")
        return {"success": False, "error": str(e)}

@router.post("/admin/users/{user_id}/skills/{skill_id}/add")
async def add_skill_to_user(
    user_id: str,
    skill_id: str,
    request: Request
):
    """Add a skill to a user (validates skill is enabled for user's tenant)"""
    user_session = await get_session_user(request)
    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # Validate: skill must be enabled for the user's tenant
            user_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                headers=headers,
                params={"id": f"eq.{user_id}", "select": "tenant_id"}
            )
            if user_resp.status_code != 200 or not user_resp.json():
                return {"success": False, "error": "User not found"}

            user_tenant_id = user_resp.json()[0]["tenant_id"]

            ts_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_skills",
                headers=headers,
                params={
                    "tenant_id": f"eq.{user_tenant_id}",
                    "skill_id": f"eq.{skill_id}",
                    "is_enabled": "eq.true"
                }
            )
            if ts_resp.status_code != 200 or not ts_resp.json():
                return {"success": False, "error": "This skill is not enabled for this tenant"}

            # Check if relationship already exists (might be disabled)
            check_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/user_skills",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "user_id": f"eq.{user_id}",
                    "skill_id": f"eq.{skill_id}"
                }
            )

            if check_response.status_code == 200 and check_response.json():
                # Relationship exists, just enable it
                update_response = await client.patch(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/user_skills",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal"
                    },
                    params={
                        "user_id": f"eq.{user_id}",
                        "skill_id": f"eq.{skill_id}"
                    },
                    json={"is_enabled": True}
                )

                if update_response.status_code in [200, 204]:
                    return {"success": True, "message": "Skill enabled"}
                else:
                    return {"success": False, "error": "Failed to enable skill"}
            else:
                # Create new relationship
                import uuid
                create_response = await client.post(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/user_skills",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal"
                    },
                    json={
                        "id": str(uuid.uuid4()),
                        "user_id": user_id,
                        "skill_id": skill_id,
                        "is_enabled": True
                    }
                )

                if create_response.status_code in [200, 201]:
                    return {"success": True, "message": "Skill added"}
                else:
                    logger.error(f"Failed to create user skill: {create_response.text}")
                    return {"success": False, "error": "Failed to add skill"}

    except Exception as e:
        logger.error(f"Error adding skill to user: {e}")
        return {"success": False, "error": str(e)}

@router.delete("/admin/users/{user_id}/skills/{skill_id}")
async def remove_skill_from_user(
    user_id: str,
    skill_id: str,
    request: Request
):
    user_session = await get_session_user(request)
    """Remove a skill from a user (soft delete - set is_enabled = false)"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/user_skills",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                params={
                    "user_id": f"eq.{user_id}",
                    "skill_id": f"eq.{skill_id}"
                },
                json={"is_enabled": False}
            )

            if response.status_code in [200, 204]:
                return {"success": True, "message": "Skill removed"}
            else:
                return {"success": False, "error": "Failed to remove skill"}

    except Exception as e:
        logger.error(f"Error removing skill from user: {e}")
        return {"success": False, "error": str(e)}

@router.put("/admin/users/{user_id}")
async def update_user(
    user_id: str,
    request: Request
):
    """Update user details (name, phone, email, role)"""
    user_session = await get_session_user(request)
    try:
        body = await request.json()
        name = body.get("name")
        phone_number = body.get("phone_number")
        email = body.get("email")
        role = body.get("role")

        if not name or not phone_number:
            return {"success": False, "error": "Name and phone number are required"}

        async with httpx.AsyncClient() as client:
            update_data = {
                "name": name,
                "phone_number": phone_number,
                "email": email if email else None,
                "role": role if role else None
            }

            response = await client.patch(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation"
                },
                params={"id": f"eq.{user_id}"},
                json=update_data
            )

            if response.status_code == 200:
                updated_user = response.json()[0] if response.json() else None
                return {"success": True, "user": updated_user}
            else:
                logger.error(f"Failed to update user: {response.text}")
                return {"success": False, "error": "Failed to update user"}

    except Exception as e:
        logger.error(f"Error updating user: {e}")
        return {"success": False, "error": str(e)}

@router.post("/admin/users")
async def create_user(
    request: Request
):
    """Create a new user"""
    user_session = await get_session_user(request)
    tenant_id = user_session.get("tenant_id")

    # Must have a specific tenant selected
    if not tenant_id:
        return {"success": False, "error": "Please select a specific tenant to add users"}

    try:
        body = await request.json()
        name = body.get("name")
        phone_number = body.get("phone_number")
        email = body.get("email")
        role = body.get("role", "User")

        if not name or not phone_number:
            return {"success": False, "error": "Name and phone number are required"}

        # Validate phone number format (basic check)
        if not phone_number.startswith("+"):
            return {"success": False, "error": "Phone number must include country code (e.g., +1)"}

        async with httpx.AsyncClient() as client:
            # Check if phone number already exists for this tenant
            check_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "phone_number": f"eq.{phone_number}"
                }
            )

            if check_response.status_code == 200 and check_response.json():
                return {"success": False, "error": "A user with this phone number already exists", "status": 409}

            # Create new user
            import uuid
            user_data = {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "name": name,
                "phone_number": phone_number,
                "email": email if email else None,
                "role": role,
                "is_active": True  # New users are active by default
            }

            response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation"
                },
                json=user_data
            )

            if response.status_code in [200, 201]:
                new_user = response.json()[0] if response.json() else None
                logger.info(f"Created new user: {name} ({phone_number}) for tenant {tenant_id}")
                return {"success": True, "user": new_user}
            else:
                logger.error(f"Failed to create user: {response.text}")
                return {"success": False, "error": "Failed to create user"}

    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return {"success": False, "error": str(e)}

# ============================================
# SITE MANAGEMENT
# ============================================

@router.get("/admin/sites", response_class=HTMLResponse)
async def list_sites_page(request: Request):
    """Sites management page"""
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    return templates.TemplateResponse(
        "sites/list.html",
        {"request": request}
    )

@router.get("/admin/sites/data")
async def get_sites_data(request: Request):
    """Get sites data from entities table"""
    user_session = await get_session_user(request)
    tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    try:
        async with httpx.AsyncClient() as client:
            params = {
                "select": "id,name,address,tenant_id",
                "entity_type": "eq.sites"  # Filter for sites only
            }

            # Apply tenant filter
            if tenant_id and not is_super_admin:
                params["tenant_id"] = f"eq.{tenant_id}"
            elif tenant_id and is_super_admin:
                params["tenant_id"] = f"eq.{tenant_id}"

            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/entities",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params=params
            )

            logger.info(f"Fetching sites from entities table: {response.status_code}, params: {params}")

            if response.status_code == 200:
                sites = response.json()
                logger.info(f"Found {len(sites)} sites")
                return {"success": True, "sites": sites}
            else:
                logger.error(f"Failed to fetch sites: {response.status_code} - {response.text}")
                return {"success": False, "error": "Failed to fetch sites"}

    except Exception as e:
        logger.error(f"Error fetching sites: {e}")
        return {"success": False, "error": str(e)}

# ============================================
# REPORTS
# ============================================

@router.get("/admin/reports/timesheets", response_class=HTMLResponse)
async def timesheets_report_page(request: Request, theme: Optional[str] = None):
    """Timesheets report page"""
    # Check if authenticated
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)

    # Choose template based on theme parameter
    template = "reports/timesheets-modern.html" if theme == "modern" else "reports/timesheets.html"

    return templates.TemplateResponse(
        template,
        {"request": request, "page_title": "Timesheet Reports"}
    )

@router.get("/admin/reports/timesheets/data")
async def get_timesheets_data(
    request: Request,
    view: str = "all_users",
    user_id: Optional[str] = None,
    site_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tenant_id: Optional[str] = None  # Allow super admin to filter by tenant
):
    """Get timesheet data with filtering"""
    user_session = await get_session_user(request)
    session_tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    # For tenant admins, always use their session tenant_id
    # For super admins, use the query parameter if provided
    if not is_super_admin:
        tenant_id = session_tenant_id

    try:
        async with httpx.AsyncClient() as client:
            # Build query params
            # Note: sites are stored in entities table, we'll just get site_id and fetch names separately
            params = {
                "select": "id,work_date,start_time,end_time,hours_worked,work_description,plans_for_tomorrow,call_transcript,site_id,user_id,users(name)",
                "order": "work_date.desc,start_time.desc"
            }

            # Apply tenant filter (always apply if tenant_id is set)
            if tenant_id:
                params["tenant_id"] = f"eq.{tenant_id}"

            # Apply additional filters
            if user_id:
                params["user_id"] = f"eq.{user_id}"

            if site_id:
                params["site_id"] = f"eq.{site_id}"

            if start_date and end_date:
                # Use and operator for date range
                params["and"] = f"(work_date.gte.{start_date},work_date.lte.{end_date})"
            elif start_date:
                params["work_date"] = f"gte.{start_date}"
            elif end_date:
                params["work_date"] = f"lte.{end_date}"

            # Fetch timesheets
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/timesheets",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params=params
            )

            logger.info(f"Fetching timesheets: {response.status_code}, params: {params}")

            if response.status_code != 200:
                logger.error(f"Supabase error: {response.status_code} - {response.text}")
                return {"success": False, "error": f"Failed to fetch timesheets: {response.text}"}

            if response.status_code == 200:
                timesheets = response.json()
                logger.info(f"Found {len(timesheets)} timesheets")

                # Fetch site names from entities table
                if timesheets:
                    site_ids = list(set(entry.get("site_id") for entry in timesheets if entry.get("site_id")))
                    if site_ids:
                        # Fetch entities (sites) by IDs
                        sites_response = await client.get(
                            f"{os.getenv('SUPABASE_URL')}/rest/v1/entities",
                            headers={
                                "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                            },
                            params={
                                "id": f"in.({','.join(site_ids)})",
                                "select": "id,name"
                            }
                        )

                        if sites_response.status_code == 200:
                            sites = {site["id"]: site["name"] for site in sites_response.json()}
                            # Enrich timesheets with site names
                            for entry in timesheets:
                                if entry.get("site_id"):
                                    entry["site_name"] = sites.get(entry["site_id"], "Unknown Site")
                                else:
                                    entry["site_name"] = "Unknown Site"
                        else:
                            # If sites fetch fails, just use Unknown
                            for entry in timesheets:
                                entry["site_name"] = "Unknown Site"
                    else:
                        for entry in timesheets:
                            entry["site_name"] = "Unknown Site"

                # Calculate summary stats
                if view == "all_users":
                    # Group by user
                    user_summary = {}
                    for entry in timesheets:
                        user_id_key = entry["user_id"]
                        user_name = entry.get("users", {}).get("name", "Unknown User")

                        if user_id_key not in user_summary:
                            user_summary[user_id_key] = {
                                "user_id": user_id_key,
                                "user_name": user_name,
                                "total_hours": 0,
                                "entry_count": 0,
                                "days_worked": set()
                            }

                        user_summary[user_id_key]["total_hours"] += entry["hours_worked"]
                        user_summary[user_id_key]["entry_count"] += 1
                        user_summary[user_id_key]["days_worked"].add(entry["work_date"])

                    # Convert to list and format
                    summary_list = []
                    for user_data in user_summary.values():
                        summary_list.append({
                            "user_id": user_data["user_id"],
                            "user_name": user_data["user_name"],
                            "total_hours": round(user_data["total_hours"], 2),
                            "entry_count": user_data["entry_count"],
                            "days_worked": len(user_data["days_worked"]),
                            "avg_hours_per_day": round(user_data["total_hours"] / len(user_data["days_worked"]), 2) if user_data["days_worked"] else 0
                        })

                    # Sort by total hours descending
                    summary_list.sort(key=lambda x: x["total_hours"], reverse=True)

                    # Overall stats
                    total_hours = sum(e["hours_worked"] for e in timesheets)
                    total_users = len(user_summary)
                    total_entries = len(timesheets)

                    return {
                        "success": True,
                        "view": view,
                        "summary": {
                            "total_hours": round(total_hours, 2),
                            "total_users": total_users,
                            "total_entries": total_entries,
                            "avg_hours_per_user": round(total_hours / total_users, 2) if total_users > 0 else 0
                        },
                        "user_summary": summary_list,
                        "entries": timesheets
                    }
                else:
                    # Individual user view
                    total_hours = sum(e["hours_worked"] for e in timesheets)
                    unique_days = len(set(e["work_date"] for e in timesheets))

                    return {
                        "success": True,
                        "view": view,
                        "summary": {
                            "total_hours": round(total_hours, 2),
                            "days_worked": unique_days,
                            "total_entries": len(timesheets),
                            "avg_hours_per_day": round(total_hours / unique_days, 2) if unique_days > 0 else 0
                        },
                        "entries": timesheets
                    }
            else:
                return {"success": False, "error": "Failed to fetch timesheets"}

    except Exception as e:
        logger.error(f"Error fetching timesheets: {e}")
        return {"success": False, "error": str(e)}

@router.get("/admin/reports/timesheets/by-site")
async def get_timesheets_by_site(
    request: Request,
    site_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tenant_id: Optional[str] = None  # Allow super admin to filter by tenant
):
    """Get timesheet data grouped by site"""
    user_session = await get_session_user(request)
    session_tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    # For tenant admins, always use their session tenant_id
    # For super admins, use the query parameter if provided
    if not is_super_admin:
        tenant_id = session_tenant_id

    try:
        async with httpx.AsyncClient() as client:
            # Build query params
            params = {
                "select": "id,work_date,start_time,end_time,hours_worked,work_description,plans_for_tomorrow,call_transcript,site_id,user_id,users(name)",
                "order": "work_date.desc,start_time.desc"
            }

            # Apply tenant filter (always apply if tenant_id is set)
            if tenant_id:
                params["tenant_id"] = f"eq.{tenant_id}"

            # Apply site filter if provided
            if site_id:
                params["site_id"] = f"eq.{site_id}"

            # Apply date filter
            if start_date and end_date:
                params["and"] = f"(work_date.gte.{start_date},work_date.lte.{end_date})"
            elif start_date:
                params["work_date"] = f"gte.{start_date}"
            elif end_date:
                params["work_date"] = f"lte.{end_date}"

            # Fetch timesheets
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/timesheets",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params=params
            )

            logger.info(f"Fetching timesheets by site: {response.status_code}, params: {params}")

            if response.status_code != 200:
                logger.error(f"Supabase error: {response.status_code} - {response.text}")
                return {"success": False, "error": f"Failed to fetch timesheets: {response.text}"}

            timesheets = response.json()
            logger.info(f"Found {len(timesheets)} timesheets")

            # Fetch site names from entities table
            site_ids = list(set(entry.get("site_id") for entry in timesheets if entry.get("site_id")))
            site_names = {}

            if site_ids:
                sites_response = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/entities",
                    headers={
                        "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                        "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                    },
                    params={
                        "id": f"in.({','.join(site_ids)})",
                        "select": "id,name"
                    }
                )

                if sites_response.status_code == 200:
                    site_names = {site["id"]: site["name"] for site in sites_response.json()}

            # Group timesheets by site
            site_data = {}
            for entry in timesheets:
                entry_site_id = entry.get("site_id")
                if not entry_site_id:
                    entry_site_id = "no_site"
                    site_name = "No Site Assigned"
                else:
                    site_name = site_names.get(entry_site_id, "Unknown Site")

                # Enrich entry with site name
                entry["site_name"] = site_name

                # Group by site
                if entry_site_id not in site_data:
                    site_data[entry_site_id] = {
                        "site_id": entry_site_id,
                        "site_name": site_name,
                        "total_hours": 0,
                        "entry_count": 0,
                        "user_count": set(),
                        "days_worked": set(),
                        "entries": []
                    }

                site_data[entry_site_id]["total_hours"] += entry["hours_worked"]
                site_data[entry_site_id]["entry_count"] += 1
                site_data[entry_site_id]["user_count"].add(entry["user_id"])
                site_data[entry_site_id]["days_worked"].add(entry["work_date"])
                site_data[entry_site_id]["entries"].append(entry)

            # Convert to list and format
            site_list = []
            for site_info in site_data.values():
                site_list.append({
                    "site_id": site_info["site_id"],
                    "site_name": site_info["site_name"],
                    "total_hours": round(site_info["total_hours"], 2),
                    "entry_count": site_info["entry_count"],
                    "user_count": len(site_info["user_count"]),
                    "days_worked": len(site_info["days_worked"]),
                    "avg_hours_per_day": round(site_info["total_hours"] / len(site_info["days_worked"]), 2) if site_info["days_worked"] else 0,
                    "entries": site_info["entries"]
                })

            # Sort by total hours descending
            site_list.sort(key=lambda x: x["total_hours"], reverse=True)

            # Overall stats
            total_hours = sum(e["hours_worked"] for e in timesheets)
            total_sites = len(site_data)
            total_entries = len(timesheets)

            return {
                "success": True,
                "view": "by_site",
                "summary": {
                    "total_hours": round(total_hours, 2),
                    "total_sites": total_sites,
                    "total_entries": total_entries,
                    "avg_hours_per_site": round(total_hours / total_sites, 2) if total_sites > 0 else 0
                },
                "site_summary": site_list,
                "entries": timesheets
            }

    except Exception as e:
        logger.error(f"Error fetching timesheets by site: {e}")
        return {"success": False, "error": str(e)}


@router.post("/admin/timesheets/{timesheet_id}/update")
async def update_timesheet_entry(timesheet_id: str, request: Request):
    """Update a timesheet entry (start_time, end_time, work_description)."""
    user_session = await get_session_user(request)
    is_super_admin = user_session.get("role") == "super_admin"
    session_tenant_id = user_session.get("tenant_id")
    body = await request.json()

    async with httpx.AsyncClient() as client:
        # Verify access - fetch the record
        check = await client.get(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/timesheets",
            headers={
                "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            },
            params={"id": f"eq.{timesheet_id}", "select": "id,tenant_id,start_time,end_time"},
        )
        if check.status_code != 200 or not check.json():
            return {"success": False, "error": "Timesheet entry not found"}

        record = check.json()[0]
        if not is_super_admin and record["tenant_id"] != session_tenant_id:
            return {"success": False, "error": "Access denied"}

        # Build update payload
        update_data = {}
        if "start_time" in body and body["start_time"]:
            update_data["start_time"] = body["start_time"]
        if "end_time" in body and body["end_time"]:
            update_data["end_time"] = body["end_time"]
        if "work_description" in body:
            update_data["work_description"] = body["work_description"]

        # Recalculate hours_worked if times changed
        new_start = update_data.get("start_time", record.get("start_time"))
        new_end = update_data.get("end_time", record.get("end_time"))
        if new_start and new_end and ("start_time" in update_data or "end_time" in update_data):
            try:
                from datetime import datetime as dt
                start_dt = dt.strptime(new_start.split("+")[0].split("Z")[0], "%H:%M:%S" if len(new_start) <= 8 else "%H:%M")
                end_dt = dt.strptime(new_end.split("+")[0].split("Z")[0], "%H:%M:%S" if len(new_end) <= 8 else "%H:%M")
                diff = (end_dt - start_dt).total_seconds() / 3600
                if diff < 0:
                    diff += 24  # handle overnight
                update_data["hours_worked"] = round(diff, 2)
            except Exception as e:
                logger.warning(f"Could not recalculate hours: {e}")

        if not update_data:
            return {"success": False, "error": "No changes provided"}

        resp = await client.patch(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/timesheets",
            headers={
                "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            },
            params={"id": f"eq.{timesheet_id}"},
            json=update_data,
        )

        if resp.status_code in (200, 204):
            updated = resp.json()[0] if resp.json() else {}
            return {"success": True, "timesheet": updated}
        else:
            logger.error("Failed to update timesheet %s: %s", timesheet_id, resp.text)
            return {"success": False, "error": "Failed to update"}


@router.get("/admin/reports/voice-notes", response_class=HTMLResponse)
async def voice_notes_report_page(request: Request, theme: Optional[str] = None):
    """Voice notes report page"""
    # Check if authenticated
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)

    # Choose template based on theme parameter
    template = "reports/voice_notes-modern.html" if theme == "modern" else "reports/voice_notes.html"

    return templates.TemplateResponse(
        template,
        {"request": request, "page_title": "Voice Notes Reports"}
    )


# ============================================
# CALL QUALITY (Super Admin Only)
# ============================================

@router.get("/admin/call-quality", response_class=HTMLResponse)
async def call_quality_page(request: Request):
    """Call Quality dashboard page - super admin only"""
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)

    # Super admin only
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    return templates.TemplateResponse(
        "reports/call_quality.html",
        {"request": request, "page_title": "Call Quality"}
    )


@router.get("/admin/call-quality/data")
async def get_call_quality_data(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    call_type: Optional[str] = None,
    tenant_id: Optional[str] = None,
):
    """Get call quality data - super admin only"""
    user_session = await get_session_user(request)

    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # Build query params
            params = {
                "select": "id,vapi_call_id,tenant_id,user_id,call_type,caller_phone,"
                          "call_duration_seconds,call_cost,ended_reason,summary,"
                          "success_evaluation,task_completed,sites_logged,"
                          "repeated_questions,filler_phrases_used,user_had_to_repeat,"
                          "user_sentiment,naturalness_score,flow_steps_skipped,"
                          "improvement_notes,call_started_at,call_ended_at",
                "order": "call_started_at.desc",
                "limit": "100"
            }

            if start_date:
                params["call_started_at"] = f"gte.{start_date}T00:00:00Z"
            if end_date:
                params["call_started_at"] = f"lte.{end_date}T23:59:59Z"
                if start_date:
                    # Both dates - use and syntax
                    params.pop("call_started_at")
                    params["and"] = f"(call_started_at.gte.{start_date}T00:00:00Z,call_started_at.lte.{end_date}T23:59:59Z)"
            if call_type and call_type != "all":
                params["call_type"] = f"eq.{call_type}"
            if tenant_id:
                params["tenant_id"] = f"eq.{tenant_id}"

            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/call_quality_assessments",
                headers=headers,
                params=params
            )

            if response.status_code != 200:
                logger.error(f"Failed to fetch call quality data: {response.status_code} - {response.text}")
                return {"success": False, "error": "Failed to fetch data"}

            calls = response.json()

            # Enrich with user names
            user_ids = list(set(c.get("user_id") for c in calls if c.get("user_id")))
            user_names = {}
            if user_ids:
                users_response = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                    headers=headers,
                    params={
                        "id": f"in.({','.join(user_ids)})",
                        "select": "id,name"
                    }
                )
                if users_response.status_code == 200:
                    for u in users_response.json():
                        user_names[u["id"]] = u["name"]

            # Enrich with tenant names
            tenant_ids = list(set(c.get("tenant_id") for c in calls if c.get("tenant_id")))
            tenant_names = {}
            if tenant_ids:
                tenants_response = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                    headers=headers,
                    params={
                        "id": f"in.({','.join(tenant_ids)})",
                        "select": "id,name"
                    }
                )
                if tenants_response.status_code == 200:
                    for t in tenants_response.json():
                        tenant_names[t["id"]] = t["name"]

            # Add names to calls
            for c in calls:
                c["user_name"] = user_names.get(c.get("user_id"), "Unknown")
                c["tenant_name"] = tenant_names.get(c.get("tenant_id"), "Unknown")

            # Calculate aggregate stats
            total = len(calls)
            successful = sum(1 for c in calls if c.get("success_evaluation") in ["true", True])
            failed = sum(1 for c in calls if c.get("success_evaluation") in ["false", False])
            avg_naturalness = 0
            naturalness_calls = [c for c in calls if c.get("naturalness_score")]
            if naturalness_calls:
                avg_naturalness = sum(c["naturalness_score"] for c in naturalness_calls) / len(naturalness_calls)

            repeated_q = sum(1 for c in calls if c.get("repeated_questions"))
            filler_used = sum(1 for c in calls if c.get("filler_phrases_used"))
            user_repeat = sum(1 for c in calls if c.get("user_had_to_repeat"))

            sentiment_counts = {}
            for c in calls:
                s = c.get("user_sentiment", "unknown")
                sentiment_counts[s] = sentiment_counts.get(s, 0) + 1

            avg_duration = 0
            duration_calls = [c for c in calls if c.get("call_duration_seconds")]
            if duration_calls:
                avg_duration = sum(c["call_duration_seconds"] for c in duration_calls) / len(duration_calls)

            total_cost = sum(c.get("call_cost", 0) or 0 for c in calls)

            return {
                "success": True,
                "calls": calls,
                "stats": {
                    "total_calls": total,
                    "successful": successful,
                    "failed": failed,
                    "success_rate": round(successful / total * 100, 1) if total > 0 else 0,
                    "avg_naturalness": round(avg_naturalness, 1),
                    "repeated_questions_count": repeated_q,
                    "filler_phrases_count": filler_used,
                    "user_had_to_repeat_count": user_repeat,
                    "sentiment_counts": sentiment_counts,
                    "avg_duration_seconds": round(avg_duration, 1),
                    "total_cost": round(total_cost, 4),
                }
            }

    except Exception as e:
        logger.error(f"Error fetching call quality data: {e}")
        return {"success": False, "error": str(e)}


@router.get("/admin/call-quality/{call_id}")
async def get_call_quality_detail(request: Request, call_id: str):
    """Get detailed call quality data for a single call - super admin only"""
    user_session = await get_session_user(request)

    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/call_quality_assessments",
                headers=headers,
                params={
                    "id": f"eq.{call_id}",
                    "select": "*"
                }
            )

            if response.status_code != 200 or not response.json():
                return {"success": False, "error": "Call not found"}

            call = response.json()[0]

            # Enrich with user name
            if call.get("user_id"):
                user_resp = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                    headers=headers,
                    params={
                        "id": f"eq.{call['user_id']}",
                        "select": "name"
                    }
                )
                if user_resp.status_code == 200 and user_resp.json():
                    call["user_name"] = user_resp.json()[0]["name"]

            # Enrich with tenant name
            if call.get("tenant_id"):
                tenant_resp = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                    headers=headers,
                    params={
                        "id": f"eq.{call['tenant_id']}",
                        "select": "name"
                    }
                )
                if tenant_resp.status_code == 200 and tenant_resp.json():
                    call["tenant_name"] = tenant_resp.json()[0]["name"]

            return {"success": True, "call": call}

    except Exception as e:
        logger.error(f"Error fetching call quality detail: {e}")
        return {"success": False, "error": str(e)}


# ============================================
# LEARNING LOOP (Super Admin Only)
# ============================================

@router.get("/admin/learning-loop", response_class=HTMLResponse)
async def learning_loop_page(request: Request):
    """Learning Loop dashboard - super admin only"""
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    return templates.TemplateResponse(
        "reports/learning_loop.html",
        {"request": request, "page_title": "Learning Loop"}
    )


@router.get("/admin/learning-loop/insights")
async def get_learning_loop_insights(
    request: Request,
    period: str = "this_week",
    assistant: str = None,
):
    """Get quality insights with period-over-period comparison"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    try:
        now = datetime.now(timezone.utc)

        # Calculate date ranges
        if period == "today":
            current_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            prev_start = current_start - timedelta(days=1)
            prev_end = current_start
        elif period == "this_week":
            days_since_monday = now.weekday()
            current_start = (now - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
            prev_start = current_start - timedelta(weeks=1)
            prev_end = current_start
        elif period == "this_month":
            current_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            prev_start = (current_start - timedelta(days=1)).replace(day=1)
            prev_end = current_start
        else:
            current_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            prev_start = current_start - timedelta(weeks=1)
            prev_end = current_start

        current_end = now

        # Build assistant filter clause
        assistant_filter = f",call_type.eq.{assistant}" if assistant else ""

        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # Fetch current period calls
            current_params = {
                "select": "success_evaluation,naturalness_score,repeated_questions,"
                          "filler_phrases_used,user_had_to_repeat,user_sentiment,"
                          "improvement_notes,call_type",
                "and": f"(call_started_at.gte.{current_start.isoformat()},call_started_at.lte.{current_end.isoformat()}{assistant_filter})",
                "order": "call_started_at.desc"
            }

            current_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/call_quality_assessments",
                headers=headers,
                params=current_params
            )

            # Fetch previous period calls
            prev_params = {
                "select": "success_evaluation,naturalness_score,repeated_questions,"
                          "filler_phrases_used,user_had_to_repeat,user_sentiment,"
                          "improvement_notes,call_type",
                "and": f"(call_started_at.gte.{prev_start.isoformat()},call_started_at.lte.{prev_end.isoformat()}{assistant_filter})",
                "order": "call_started_at.desc"
            }

            prev_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/call_quality_assessments",
                headers=headers,
                params=prev_params
            )

            # Fetch recent prompt changes
            prompt_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/prompt_changes",
                headers=headers,
                params={
                    "select": "assistant_key,change_summary,pushed_at",
                    "pushed_at": f"gte.{prev_start.isoformat()}",
                    "order": "pushed_at.desc",
                    "limit": "10"
                }
            )

            current_calls = current_resp.json() if current_resp.status_code == 200 else []
            prev_calls = prev_resp.json() if prev_resp.status_code == 200 else []
            recent_prompt_changes = prompt_resp.json() if prompt_resp.status_code == 200 else []

        # Compute metrics for each period
        def compute_metrics(calls):
            total = len(calls)
            if total == 0:
                return {"total": 0, "success_rate": 0, "avg_naturalness": 0,
                        "repeated_pct": 0, "filler_pct": 0, "user_repeat_pct": 0}

            successful = sum(1 for c in calls if c.get("success_evaluation") in ["true", True])
            nat_scores = [c["naturalness_score"] for c in calls if c.get("naturalness_score")]
            avg_nat = sum(nat_scores) / len(nat_scores) if nat_scores else 0
            repeated = sum(1 for c in calls if c.get("repeated_questions"))
            filler = sum(1 for c in calls if c.get("filler_phrases_used"))
            user_repeat = sum(1 for c in calls if c.get("user_had_to_repeat"))

            return {
                "total": total,
                "success_rate": round(successful / total * 100, 1),
                "avg_naturalness": round(avg_nat, 1),
                "repeated_pct": round(repeated / total * 100, 1),
                "filler_pct": round(filler / total * 100, 1),
                "user_repeat_pct": round(user_repeat / total * 100, 1),
            }

        current_metrics = compute_metrics(current_calls)
        prev_metrics = compute_metrics(prev_calls)

        # Compute deltas
        def delta(current_val, prev_val):
            if prev_val == 0:
                return None
            return round(current_val - prev_val, 1)

        deltas = {
            "success_rate": delta(current_metrics["success_rate"], prev_metrics["success_rate"]),
            "avg_naturalness": delta(current_metrics["avg_naturalness"], prev_metrics["avg_naturalness"]),
            "repeated_pct": delta(current_metrics["repeated_pct"], prev_metrics["repeated_pct"]),
            "filler_pct": delta(current_metrics["filler_pct"], prev_metrics["filler_pct"]),
            "user_repeat_pct": delta(current_metrics["user_repeat_pct"], prev_metrics["user_repeat_pct"]),
        }

        # Generate insight cards
        insights = []

        # Check for regressions
        if deltas["success_rate"] is not None and deltas["success_rate"] < -10:
            insights.append({
                "type": "warning",
                "title": "Success rate dropped",
                "detail": f"Down {abs(deltas['success_rate'])}% from last period ({prev_metrics['success_rate']}% → {current_metrics['success_rate']}%)",
                "recommendation": "Review failed calls in Call Quality for common patterns"
            })

        if deltas["repeated_pct"] is not None and deltas["repeated_pct"] > 10:
            insights.append({
                "type": "warning",
                "title": "More repeated questions",
                "detail": f"Up {deltas['repeated_pct']}% — Jill is asking the same question more often",
                "recommendation": "Check if STT confidence is low on certain phrases"
            })

        if deltas["filler_pct"] is not None and deltas["filler_pct"] > 10:
            insights.append({
                "type": "warning",
                "title": "More filler phrases",
                "detail": f"Up {deltas['filler_pct']}% — Jill is saying 'hold on', 'one moment', etc.",
                "recommendation": "Review prompt instructions about staying silent during tool calls"
            })

        # Check for improvements
        if deltas["success_rate"] is not None and deltas["success_rate"] > 5:
            insights.append({
                "type": "improvement",
                "title": "Success rate improved",
                "detail": f"Up {deltas['success_rate']}% ({prev_metrics['success_rate']}% → {current_metrics['success_rate']}%)",
                "recommendation": "Great progress — keep monitoring"
            })

        if deltas["avg_naturalness"] is not None and deltas["avg_naturalness"] > 0.3:
            insights.append({
                "type": "improvement",
                "title": "Naturalness improving",
                "detail": f"Score up {deltas['avg_naturalness']} ({prev_metrics['avg_naturalness']} → {current_metrics['avg_naturalness']})",
                "recommendation": "Prompt changes are having a positive effect"
            })

        # Correlate with prompt changes
        if recent_prompt_changes and deltas["success_rate"] is not None:
            direction = "improved" if deltas["success_rate"] > 0 else "changed"
            insights.append({
                "type": "info",
                "title": f"{len(recent_prompt_changes)} prompt change(s) recently",
                "detail": f"Quality has {direction} since — may be related",
                "recommendation": "Compare before/after in the timeline below"
            })

        # Extract themes from improvement notes
        themes = {}
        theme_keywords = {
            "time_parsing": ["time parsing", "half seven", "quarter past", "o'clock", "parse time", "time format"],
            "site_recognition": ["wrong site", "didn't recognise", "couldn't find site", "site not found", "site name"],
            "filler_phrases": ["hold on", "one moment", "just a sec", "filler phrase", "filler"],
            "repeated_questions": ["repeated", "asked again", "same question", "re-asked"],
            "flow_steps": ["skipped", "didn't ask", "missed step", "readback", "confirmation step"],
        }

        for call in current_calls:
            notes = (call.get("improvement_notes") or "").lower()
            if not notes or notes == "none":
                continue
            for theme, keywords in theme_keywords.items():
                if any(kw.lower() in notes for kw in keywords):
                    themes[theme] = themes.get(theme, 0) + 1

        return {
            "success": True,
            "period": period,
            "current": current_metrics,
            "previous": prev_metrics,
            "deltas": deltas,
            "insights": insights,
            "themes": themes,
            "recent_prompt_changes": recent_prompt_changes,
        }

    except Exception as e:
        logger.error(f"Error computing insights: {e}")
        return {"success": False, "error": str(e)}


@router.get("/admin/learning-loop/timeline")
async def get_learning_loop_timeline(
    request: Request,
    days: int = 30,
    assistant: str = None,
):
    """Get daily quality timeline with eval runs and prompt changes"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    try:
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # Fetch calls for the period
            calls_params = {
                "select": "call_started_at,success_evaluation,naturalness_score",
                "call_started_at": f"gte.{start_date.isoformat()}",
                "order": "call_started_at.asc"
            }
            if assistant:
                calls_params["call_type"] = f"eq.{assistant}"

            calls_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/call_quality_assessments",
                headers=headers,
                params=calls_params
            )

            # Fetch eval runs for the period
            evals_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/eval_runs",
                headers=headers,
                params={
                    "select": "run_timestamp,pass_rate,status,total_evals,passed,failed",
                    "run_timestamp": f"gte.{start_date.isoformat()}",
                    "order": "run_timestamp.asc"
                }
            )

            # Fetch prompt changes for the period
            prompts_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/prompt_changes",
                headers=headers,
                params={
                    "select": "pushed_at,assistant_key,change_summary",
                    "pushed_at": f"gte.{start_date.isoformat()}",
                    "order": "pushed_at.asc"
                }
            )

            calls = calls_resp.json() if calls_resp.status_code == 200 else []
            eval_runs = evals_resp.json() if evals_resp.status_code == 200 else []
            prompt_changes = prompts_resp.json() if prompts_resp.status_code == 200 else []

        # Group calls by day
        daily = {}
        for call in calls:
            day = call.get("call_started_at", "")[:10]  # YYYY-MM-DD
            if day not in daily:
                daily[day] = {"calls": 0, "successful": 0, "naturalness_scores": []}
            daily[day]["calls"] += 1
            if call.get("success_evaluation") in ["true", True]:
                daily[day]["successful"] += 1
            if call.get("naturalness_score"):
                daily[day]["naturalness_scores"].append(call["naturalness_score"])

        # Build timeline data
        timeline = []
        for day_str, data in sorted(daily.items()):
            total = data["calls"]
            timeline.append({
                "date": day_str,
                "calls": total,
                "success_rate": round(data["successful"] / total * 100, 1) if total > 0 else 0,
                "avg_naturalness": round(sum(data["naturalness_scores"]) / len(data["naturalness_scores"]), 1) if data["naturalness_scores"] else None,
            })

        # Map eval runs to dates
        eval_run_dots = []
        for run in eval_runs:
            if run.get("status") == "completed":
                eval_run_dots.append({
                    "date": run["run_timestamp"][:10],
                    "pass_rate": run.get("pass_rate"),
                    "total": run.get("total_evals"),
                    "passed": run.get("passed"),
                })

        # Map prompt changes to dates
        prompt_markers = []
        for change in prompt_changes:
            prompt_markers.append({
                "date": change["pushed_at"][:10],
                "assistant": change.get("assistant_key"),
                "summary": change.get("change_summary"),
            })

        return {
            "success": True,
            "timeline": timeline,
            "eval_runs": eval_run_dots,
            "prompt_changes": prompt_markers,
        }

    except Exception as e:
        logger.error(f"Error computing timeline: {e}")
        return {"success": False, "error": str(e)}


@router.post("/admin/learning-loop/run-evals")
async def run_evals(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Trigger eval suite run in background"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # Create eval_run record with status=running
            run_record = {
                "status": "running",
                "triggered_by": "dashboard",
            }

            response = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/eval_runs",
                headers={**headers, "Content-Type": "application/json", "Prefer": "return=representation"},
                json=run_record
            )

            if response.status_code != 201:
                return {"success": False, "error": "Failed to create eval run record"}

            run_data = response.json()
            run_id = run_data[0]["id"] if isinstance(run_data, list) else run_data["id"]

        # Run evals in background
        background_tasks.add_task(_execute_eval_run, run_id)

        return {"success": True, "run_id": run_id, "status": "running"}

    except Exception as e:
        logger.error(f"Error starting eval run: {e}")
        return {"success": False, "error": str(e)}


async def _execute_eval_run(run_id: str):
    """Background task to execute eval suite and store results"""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    try:
        from scripts.vapi_evals.eval_runner import VAPIEvalsRunner
        from scripts.vapi_evals.eval_definitions import GREETER_EVALS, TIMESHEET_EVALS, FLOW_EVALS, QR_EVALS

        runner = VAPIEvalsRunner()
        await runner.get_assistants()

        existing = await runner.list_evals()
        eval_map = {e.get("name"): e.get("id") for e in existing}

        results = []
        passed = 0
        failed = 0

        # Build list of evals to run
        evals_to_run = []
        for eval_def in GREETER_EVALS:
            if eval_def["name"] in eval_map:
                evals_to_run.append({
                    "name": eval_def["name"],
                    "eval_id": eval_map[eval_def["name"]],
                    "assistant_id": runner.assistant_ids.get("greeter"),
                })
        for eval_def in TIMESHEET_EVALS:
            if eval_def["name"] in eval_map:
                evals_to_run.append({
                    "name": eval_def["name"],
                    "eval_id": eval_map[eval_def["name"]],
                    "assistant_id": runner.assistant_ids.get("timesheet"),
                })
        for eval_def in FLOW_EVALS:
            if eval_def["name"] in eval_map:
                evals_to_run.append({
                    "name": eval_def["name"],
                    "eval_id": eval_map[eval_def["name"]],
                    "assistant_id": runner.assistant_ids.get("timesheet"),
                })
        for eval_def in QR_EVALS:
            if eval_def["name"] in eval_map:
                evals_to_run.append({
                    "name": eval_def["name"],
                    "eval_id": eval_map[eval_def["name"]],
                    "assistant_id": runner.assistant_ids.get("timesheet"),
                })

        for eval_info in evals_to_run:
            result = await runner.run_eval(
                eval_info["eval_id"],
                eval_info["name"],
                eval_info["assistant_id"]
            )

            # Extract failure reason from nested messages
            failure_reason = None
            if result.get("status") == "fail":
                for r in result.get("results", []):
                    for msg in r.get("messages", []):
                        judge = msg.get("judge", {})
                        if judge.get("status") == "fail":
                            failure_reason = judge.get("failureReason", "Unknown")[:200]
                            break
                    if failure_reason:
                        break

            results.append({
                "name": result["name"],
                "status": result["status"],
                "failure_reason": failure_reason,
                "run_id": result.get("run_id"),
            })

            if result["status"] == "pass":
                passed += 1
            else:
                failed += 1

        total = len(results)
        pass_rate = round(passed / total * 100, 1) if total > 0 else 0

        # Update the eval_run record
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            }

            await client.patch(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/eval_runs",
                headers=headers,
                params={"id": f"eq.{run_id}"},
                json={
                    "status": "completed",
                    "total_evals": total,
                    "passed": passed,
                    "failed": failed,
                    "pass_rate": pass_rate,
                    "results": results,
                }
            )

        logger.info(f"Eval run {run_id} completed: {passed}/{total} passed ({pass_rate}%)")

    except Exception as e:
        logger.error(f"Eval run {run_id} failed: {e}")
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {
                    "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                }
                await client.patch(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/eval_runs",
                    headers=headers,
                    params={"id": f"eq.{run_id}"},
                    json={
                        "status": "failed",
                        "error_message": str(e)[:500],
                    }
                )
        except Exception:
            pass


@router.get("/admin/learning-loop/eval-status/{run_id}")
async def get_eval_status(request: Request, run_id: str):
    """Poll for eval run status"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/eval_runs",
                headers=headers,
                params={
                    "id": f"eq.{run_id}",
                    "select": "*"
                }
            )

            if response.status_code != 200 or not response.json():
                return {"success": False, "error": "Run not found"}

            run = response.json()[0]
            return {"success": True, "run": run}

    except Exception as e:
        logger.error(f"Error fetching eval status: {e}")
        return {"success": False, "error": str(e)}


@router.get("/admin/learning-loop/eval-runs")
async def get_eval_runs(request: Request):
    """Get history of eval runs"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/eval_runs",
                headers=headers,
                params={
                    "select": "*",
                    "order": "run_timestamp.desc",
                    "limit": "20"
                }
            )

            if response.status_code != 200:
                return {"success": False, "error": "Failed to fetch eval runs"}

            return {"success": True, "runs": response.json()}

    except Exception as e:
        logger.error(f"Error fetching eval runs: {e}")
        return {"success": False, "error": str(e)}


@router.get("/admin/learning-loop/prompt-changes")
async def get_prompt_changes(request: Request):
    """Get history of prompt changes"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/prompt_changes",
                headers=headers,
                params={
                    "select": "*",
                    "order": "pushed_at.desc",
                    "limit": "50"
                }
            )

            if response.status_code != 200:
                return {"success": False, "error": "Failed to fetch prompt changes"}

            return {"success": True, "changes": response.json()}

    except Exception as e:
        logger.error(f"Error fetching prompt changes: {e}")
        return {"success": False, "error": str(e)}


# ============================================
# TENANT REPORT CONFIGURATION
# ============================================

REPORT_TYPES = {
    "timesheets": "Timesheets",
    "qr_signons": "QR Sign-Ons",
    "voice_notes": "Voice Notes",
    "payroll_weekly": "Weekly Payroll Summary",
    "site_weekly": "Site Weekly Report",
    "site_progress": "Site Progress Report",
}

@router.get("/admin/tenants/{tenant_id}/reports")
async def get_tenant_report_config(tenant_id: str, request: Request):
    """Get report configuration for a tenant"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_report_config",
                headers=headers,
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "select": "report_type,is_enabled"
                }
            )

            enabled_map = {}
            if response.status_code == 200:
                for row in response.json():
                    enabled_map[row["report_type"]] = row["is_enabled"]

            reports = []
            for key, label in REPORT_TYPES.items():
                reports.append({
                    "report_type": key,
                    "label": label,
                    "is_enabled": enabled_map.get(key, False)
                })

            return {"success": True, "reports": reports}

    except Exception as e:
        logger.error(f"Error fetching tenant report config: {e}")
        return {"success": False, "error": str(e)}


@router.post("/admin/tenants/{tenant_id}/reports/{report_type}/toggle")
async def toggle_tenant_report(tenant_id: str, report_type: str, request: Request):
    """Toggle a report on/off for a tenant (super admin only)"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    if report_type not in REPORT_TYPES:
        return {"success": False, "error": f"Unknown report type: {report_type}"}

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            }

            # Check if config row exists
            check = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_report_config",
                headers={
                    "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "report_type": f"eq.{report_type}",
                    "select": "id,is_enabled"
                }
            )

            if check.status_code == 200 and check.json():
                # Toggle existing
                existing = check.json()[0]
                new_val = not existing["is_enabled"]
                await client.patch(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_report_config",
                    headers=headers,
                    params={
                        "id": f"eq.{existing['id']}"
                    },
                    json={"is_enabled": new_val, "updated_at": datetime.now(timezone.utc).isoformat()}
                )
                return {"success": True, "is_enabled": new_val}
            else:
                # Create new (default to enabled)
                await client.post(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_report_config",
                    headers=headers,
                    json={
                        "tenant_id": tenant_id,
                        "report_type": report_type,
                        "is_enabled": True
                    }
                )
                return {"success": True, "is_enabled": True}

    except Exception as e:
        logger.error(f"Error toggling tenant report: {e}")
        return {"success": False, "error": str(e)}


async def get_enabled_reports_for_tenant(tenant_id: str) -> list:
    """Helper: get list of enabled report_type strings for a tenant"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_report_config",
                headers={
                    "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "is_enabled": "eq.true",
                    "select": "report_type"
                }
            )
            if response.status_code == 200:
                return [r["report_type"] for r in response.json()]
    except Exception:
        pass
    return []


# ============================================
# NEW REPORTS - PAGE ROUTES
# ============================================

@router.get("/admin/reports/payroll", response_class=HTMLResponse)
async def payroll_report_page(request: Request):
    """Weekly payroll report page"""
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    return templates.TemplateResponse(
        "reports/payroll.html",
        {"request": request, "page_title": "Weekly Payroll Summary"}
    )


@router.get("/admin/reports/site-weekly", response_class=HTMLResponse)
async def site_weekly_report_page(request: Request):
    """Site weekly report page"""
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    return templates.TemplateResponse(
        "reports/site_weekly.html",
        {"request": request, "page_title": "Site Weekly Report"}
    )


@router.get("/admin/reports/site-progress", response_class=HTMLResponse)
async def site_progress_report_page(request: Request):
    """Site progress report page"""
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    return templates.TemplateResponse(
        "reports/site_progress.html",
        {"request": request, "page_title": "Site Progress Report"}
    )


@router.get("/admin/reports/enabled")
async def get_enabled_reports(request: Request):
    """Get which reports are enabled for the current user's tenant"""
    user_session = await get_session_user(request)
    tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    # Super admin sees all reports
    if is_super_admin and not tenant_id:
        return {"success": True, "reports": list(REPORT_TYPES.keys())}

    if not tenant_id:
        return {"success": True, "reports": []}

    enabled = await get_enabled_reports_for_tenant(tenant_id)
    return {"success": True, "reports": enabled}


# ============================================
# REPORT 1: WEEKLY PAYROLL - DATA + PDF
# ============================================

@router.get("/admin/reports/payroll/data")
async def get_payroll_data(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tenant_id: Optional[str] = None,
):
    """Get payroll data for a week - person x day grid"""
    user_session = await get_session_user(request)
    session_tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        tenant_id = session_tenant_id

    if not tenant_id:
        return {"success": False, "error": "Please select a tenant"}

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            params = {
                "select": "user_id,work_date,hours_worked,users(name)",
                "tenant_id": f"eq.{tenant_id}",
                "order": "work_date.asc"
            }

            if start_date and end_date:
                params["and"] = f"(work_date.gte.{start_date},work_date.lte.{end_date})"

            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/timesheets",
                headers=headers,
                params=params
            )

            if response.status_code != 200:
                return {"success": False, "error": "Failed to fetch timesheets"}

            entries = response.json()

            # Build user map
            users = {}
            user_hours = {}  # user_id -> {date: hours}
            for entry in entries:
                uid = entry["user_id"]
                uname = entry.get("users", {}).get("name", "Unknown")
                users[uid] = uname
                if uid not in user_hours:
                    user_hours[uid] = {}
                d = entry["work_date"]
                user_hours[uid][d] = user_hours[uid].get(d, 0) + float(entry["hours_worked"])

            # Build grid data
            grid = []
            for uid, name in sorted(users.items(), key=lambda x: x[1]):
                grid.append({
                    "user_id": uid,
                    "name": name,
                    "days": user_hours.get(uid, {})
                })

            # All dates in range
            all_dates = sorted(set(e["work_date"] for e in entries))

            return {
                "success": True,
                "grid": grid,
                "dates": all_dates,
                "total_entries": len(entries)
            }

    except Exception as e:
        logger.error(f"Error fetching payroll data: {e}")
        return {"success": False, "error": str(e)}


@router.get("/admin/reports/payroll/pdf")
async def download_payroll_pdf(
    request: Request,
    start_date: str = "",
    end_date: str = "",
    break_minutes: int = 0,
    break_threshold: float = 4.0,
    tenant_id: Optional[str] = None,
):
    """Generate and download payroll PDF"""
    from fastapi.responses import Response
    from app.admin.pdf_generator import generate_payroll_pdf
    from datetime import date as date_type

    user_session = await get_session_user(request)
    session_tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        tenant_id = session_tenant_id

    if not tenant_id or not start_date or not end_date:
        raise HTTPException(status_code=400, detail="tenant_id, start_date and end_date required")

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # Get tenant name
            tenant_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                headers=headers,
                params={"id": f"eq.{tenant_id}", "select": "name"}
            )
            tenant_name = "Unknown Company"
            if tenant_resp.status_code == 200 and tenant_resp.json():
                tenant_name = tenant_resp.json()[0]["name"]

            # Get timesheet data
            params = {
                "select": "user_id,work_date,hours_worked,users(name)",
                "tenant_id": f"eq.{tenant_id}",
                "and": f"(work_date.gte.{start_date},work_date.lte.{end_date})",
                "order": "work_date.asc"
            }

            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/timesheets",
                headers=headers,
                params=params
            )

            if response.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to fetch timesheets")

            entries = response.json()
            users = {}
            for entry in entries:
                uid = entry["user_id"]
                users[uid] = entry.get("users", {}).get("name", "Unknown")

            week_start = date_type.fromisoformat(start_date)
            week_end = date_type.fromisoformat(end_date)

            pdf_bytes = generate_payroll_pdf(
                tenant_name=tenant_name,
                week_start=week_start,
                week_end=week_end,
                entries=entries,
                users=users,
                break_minutes=break_minutes,
                break_threshold_hours=break_threshold,
            )

            filename = f"payroll_{tenant_name.replace(' ', '_')}_{start_date}_to_{end_date}.pdf"
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'}
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating payroll PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# REPORT 2: SITE WEEKLY - DATA + PDF
# ============================================

@router.get("/admin/reports/site-weekly/data")
async def get_site_weekly_data(
    request: Request,
    site_id: str = "",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tenant_id: Optional[str] = None,
):
    """Get site weekly report data - hours + verbal updates"""
    user_session = await get_session_user(request)
    session_tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        tenant_id = session_tenant_id

    if not tenant_id:
        return {"success": False, "error": "Please select a tenant"}
    if not site_id:
        return {"success": False, "error": "Please select a site"}

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # Get site info
            site_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/entities",
                headers=headers,
                params={"id": f"eq.{site_id}", "select": "id,name,address"}
            )
            site_info = {"name": "Unknown Site", "address": ""}
            if site_resp.status_code == 200 and site_resp.json():
                site_info = site_resp.json()[0]

            # Get timesheets for this site
            ts_params = {
                "select": "user_id,work_date,start_time,end_time,hours_worked,work_description,plans_for_tomorrow,users(name)",
                "tenant_id": f"eq.{tenant_id}",
                "site_id": f"eq.{site_id}",
                "order": "work_date.asc"
            }
            if start_date and end_date:
                ts_params["and"] = f"(work_date.gte.{start_date},work_date.lte.{end_date})"

            ts_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/timesheets",
                headers=headers,
                params=ts_params
            )
            timesheets = ts_response.json() if ts_response.status_code == 200 else []

            # Get site progress updates
            su_params = {
                "select": "id,update_date,main_focus,work_progress,issues,delays,staffing,site_conditions,follow_up_actions,is_wet_weather_closure,has_urgent_issues,has_delays,has_safety_concerns,identified_blockers,flagged_concerns,extracted_action_items,summary_brief,user_id,users(name)",
                "tenant_id": f"eq.{tenant_id}",
                "site_id": f"eq.{site_id}",
                "order": "update_date.asc"
            }
            if start_date and end_date:
                su_params["and"] = f"(update_date.gte.{start_date},update_date.lte.{end_date})"

            su_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/site_progress_updates",
                headers=headers,
                params=su_params
            )
            site_updates = su_response.json() if su_response.status_code == 200 else []

            # Fetch site notes for this site + period
            sn_params = {
                "select": "id,note_text,created_at,admin_user_id,admin_users(username)",
                "tenant_id": f"eq.{tenant_id}",
                "site_id": f"eq.{site_id}",
                "order": "created_at.asc"
            }
            if start_date and end_date:
                sn_params["and"] = f"(created_at.gte.{start_date}T00:00:00,created_at.lte.{end_date}T23:59:59)"

            sn_response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/site_notes",
                headers=headers,
                params=sn_params
            )
            site_notes = sn_response.json() if sn_response.status_code == 200 else []

            # Build users map
            users = {}
            for entry in timesheets:
                uid = entry["user_id"]
                users[uid] = entry.get("users", {}).get("name", "Unknown")
            for update in site_updates:
                uid = update.get("user_id")
                if uid:
                    users[uid] = update.get("users", {}).get("name", users.get(uid, "Unknown"))

            # Build hours grid
            user_hours = {}
            for entry in timesheets:
                uid = entry["user_id"]
                if uid not in user_hours:
                    user_hours[uid] = {}
                d = entry["work_date"]
                user_hours[uid][d] = user_hours[uid].get(d, 0) + float(entry["hours_worked"])

            grid = []
            for uid in sorted(users.keys(), key=lambda u: users.get(u, "")):
                grid.append({
                    "user_id": uid,
                    "name": users[uid],
                    "days": user_hours.get(uid, {})
                })

            all_dates = sorted(set(e["work_date"] for e in timesheets)) if timesheets else []

            # Extract raw work items for AI summarisation
            raw_work_items = []
            for entry in timesheets:
                desc = entry.get("work_description", "")
                if desc and desc.strip():
                    raw_work_items.append({
                        "text": desc.strip(),
                        "user": users.get(entry["user_id"], "Unknown"),
                        "date": entry["work_date"]
                    })
            for update in site_updates:
                for field in ["work_progress", "main_focus"]:
                    val = update.get(field, "")
                    if val and val.strip():
                        raw_work_items.append({
                            "text": val.strip(),
                            "user": users.get(update.get("user_id"), ""),
                            "date": update.get("update_date", "")
                        })

            # Add site notes to raw work items (fed into AI alongside verbal updates)
            for note in site_notes:
                note_text = note.get("note_text", "")
                if note_text and note_text.strip():
                    author = note.get("admin_users", {}).get("username", "Admin")
                    note_date = note.get("created_at", "")[:10]  # Extract date from timestamp
                    raw_work_items.append({
                        "text": f"[Site Note] {note_text.strip()}",
                        "user": author,
                        "date": note_date
                    })

            # Fetch weather data for the site (cached in Supabase)
            from app.admin.weather import get_weather_for_site
            weather = {}
            site_address = site_info.get("address", "")
            if site_address and start_date and end_date:
                # Get tenant timezone for country code derivation
                tenant_resp = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                    headers=headers,
                    params={"id": f"eq.{tenant_id}", "select": "timezone"}
                )
                tenant_tz = ""
                if tenant_resp.status_code == 200 and tenant_resp.json():
                    tenant_tz = tenant_resp.json()[0].get("timezone", "")
                weather = await get_weather_for_site(
                    site_id, site_address, start_date, end_date,
                    tenant_timezone=tenant_tz,
                )

            # AI-powered categorisation and cleanup (cached in Supabase)
            from app.admin.work_summary import summarise_work_items
            work_categories = await summarise_work_items(
                raw_work_items, users,
                tenant_id=tenant_id, site_id=site_id,
                week_start=start_date or "", week_end=end_date or "",
            )

            risks = []
            for update in site_updates:
                if update.get("issues"):
                    risks.append({"type": "Issue", "text": update["issues"], "date": update.get("update_date", "")})
                if update.get("delays"):
                    risks.append({"type": "Delay", "text": update["delays"], "date": update.get("update_date", "")})
                for b in (update.get("identified_blockers") or []):
                    if isinstance(b, dict):
                        risks.append({"type": b.get("blocker_type", "Blocker"), "text": b.get("description", ""), "date": update.get("update_date", "")})
                for c in (update.get("flagged_concerns") or []):
                    if isinstance(c, dict):
                        risks.append({"type": c.get("severity", "Concern"), "text": c.get("description", ""), "date": update.get("update_date", "")})

            plans = []
            for entry in timesheets:
                p = entry.get("plans_for_tomorrow", "")
                if p and p.strip():
                    plans.append({"text": p.strip(), "date": entry["work_date"]})
            for update in site_updates:
                fa = update.get("follow_up_actions", "")
                if fa and fa.strip():
                    plans.append({"text": fa.strip(), "date": update.get("update_date", "")})
                for a in (update.get("extracted_action_items") or []):
                    if isinstance(a, dict):
                        plans.append({"text": f"{a.get('action', '')} (Priority: {a.get('priority', 'normal')})", "date": update.get("update_date", "")})

            conditions = []
            for update in site_updates:
                cond = update.get("site_conditions", "")
                if cond and cond.strip():
                    conditions.append({"text": cond.strip(), "date": update.get("update_date", "")})
                if update.get("is_wet_weather_closure"):
                    conditions.append({"text": "Wet weather closure", "date": update.get("update_date", "")})

            total_hours = sum(float(e["hours_worked"]) for e in timesheets)

            return {
                "success": True,
                "site": site_info,
                "grid": grid,
                "dates": all_dates,
                "weather": weather,
                "work_categories": work_categories,
                "raw_work_items": raw_work_items,
                "risks": risks,
                "plans": plans,
                "conditions": conditions,
                "summary": {
                    "total_hours": round(total_hours, 1),
                    "total_workers": len(user_hours),
                    "total_updates": len(site_updates),
                    "has_risks": len(risks) > 0,
                }
            }

    except Exception as e:
        logger.error(f"Error fetching site weekly data: {e}")
        return {"success": False, "error": str(e)}


@router.get("/admin/reports/site-weekly/pdf")
async def download_site_weekly_pdf(
    request: Request,
    site_id: str = "",
    start_date: str = "",
    end_date: str = "",
    tenant_id: Optional[str] = None,
):
    """Generate and download site weekly PDF"""
    from fastapi.responses import Response
    from app.admin.pdf_generator import generate_site_weekly_pdf
    from datetime import date as date_type

    user_session = await get_session_user(request)
    session_tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        tenant_id = session_tenant_id

    if not tenant_id or not site_id or not start_date or not end_date:
        raise HTTPException(status_code=400, detail="tenant_id, site_id, start_date and end_date required")

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # Get tenant name
            tenant_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                headers=headers,
                params={"id": f"eq.{tenant_id}", "select": "name"}
            )
            tenant_name = "Unknown Company"
            if tenant_resp.status_code == 200 and tenant_resp.json():
                tenant_name = tenant_resp.json()[0]["name"]

            # Get site info
            site_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/entities",
                headers=headers,
                params={"id": f"eq.{site_id}", "select": "id,name,address"}
            )
            site_name = "Unknown Site"
            site_address = ""
            if site_resp.status_code == 200 and site_resp.json():
                site_name = site_resp.json()[0].get("name", "Unknown Site")
                site_address = site_resp.json()[0].get("address", "")

            # Get timesheets
            ts_params = {
                "select": "user_id,work_date,hours_worked,work_description,plans_for_tomorrow,users(name)",
                "tenant_id": f"eq.{tenant_id}",
                "site_id": f"eq.{site_id}",
                "and": f"(work_date.gte.{start_date},work_date.lte.{end_date})",
                "order": "work_date.asc"
            }
            ts_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/timesheets",
                headers=headers,
                params=ts_params
            )
            timesheets = ts_resp.json() if ts_resp.status_code == 200 else []

            # Get site progress updates
            su_params = {
                "select": "update_date,main_focus,work_progress,issues,delays,site_conditions,follow_up_actions,is_wet_weather_closure,has_urgent_issues,has_delays,has_safety_concerns,identified_blockers,flagged_concerns,extracted_action_items,user_id,users(name)",
                "tenant_id": f"eq.{tenant_id}",
                "site_id": f"eq.{site_id}",
                "and": f"(update_date.gte.{start_date},update_date.lte.{end_date})",
                "order": "update_date.asc"
            }
            su_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/site_progress_updates",
                headers=headers,
                params=su_params
            )
            site_updates = su_resp.json() if su_resp.status_code == 200 else []

            # Build users map
            users = {}
            for e in timesheets:
                users[e["user_id"]] = e.get("users", {}).get("name", "Unknown")
            for u in site_updates:
                if u.get("user_id"):
                    users[u["user_id"]] = u.get("users", {}).get("name", users.get(u["user_id"], "Unknown"))

            week_start = date_type.fromisoformat(start_date)
            week_end = date_type.fromisoformat(end_date)

            # Build AI-categorised work summary for the PDF
            from app.admin.work_summary import summarise_work_items
            raw_work_items = []
            for entry in timesheets:
                desc = entry.get("work_description", "")
                if desc and desc.strip():
                    raw_work_items.append({
                        "text": desc.strip(),
                        "user": users.get(entry["user_id"], "Unknown"),
                        "date": entry.get("work_date", "")
                    })
            for update in site_updates:
                for field in ["work_progress", "main_focus"]:
                    val = update.get(field, "")
                    if val and val.strip():
                        raw_work_items.append({
                            "text": val.strip(),
                            "user": users.get(update.get("user_id"), ""),
                            "date": update.get("update_date", "")
                        })

            # Fetch site notes for PDF
            sn_params = {
                "select": "note_text,created_at,admin_users(username)",
                "tenant_id": f"eq.{tenant_id}",
                "site_id": f"eq.{site_id}",
                "and": f"(created_at.gte.{start_date}T00:00:00,created_at.lte.{end_date}T23:59:59)",
            }
            sn_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/site_notes",
                headers=headers,
                params=sn_params
            )
            for note in (sn_resp.json() if sn_resp.status_code == 200 else []):
                nt = note.get("note_text", "")
                if nt and nt.strip():
                    raw_work_items.append({
                        "text": f"[Site Note] {nt.strip()}",
                        "user": note.get("admin_users", {}).get("username", "Admin"),
                        "date": note.get("created_at", "")[:10]
                    })

            work_categories = await summarise_work_items(
                raw_work_items, users,
                tenant_id=tenant_id, site_id=site_id,
                week_start=start_date, week_end=end_date,
            )

            # Fetch weather for PDF
            from app.admin.weather import get_weather_for_site
            tenant_tz_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                headers=headers,
                params={"id": f"eq.{tenant_id}", "select": "timezone"}
            )
            pdf_tenant_tz = ""
            if tenant_tz_resp.status_code == 200 and tenant_tz_resp.json():
                pdf_tenant_tz = tenant_tz_resp.json()[0].get("timezone", "")
            weather = {}
            if site_address:
                weather = await get_weather_for_site(
                    site_id, site_address, start_date, end_date,
                    tenant_timezone=pdf_tenant_tz,
                )

            pdf_bytes = generate_site_weekly_pdf(
                tenant_name=tenant_name,
                site_name=site_name,
                site_address=site_address,
                week_start=week_start,
                week_end=week_end,
                timesheet_entries=timesheets,
                site_updates=site_updates,
                users=users,
                work_categories=work_categories,
                weather=weather,
            )

            filename = f"site_report_{site_name.replace(' ', '_')}_{start_date}_to_{end_date}.pdf"
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'}
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating site weekly PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# REPORT 3: SITE PROGRESS - DATA + PDF
# ============================================

@router.get("/admin/reports/site-progress/data")
async def get_site_progress_data(
    request: Request,
    site_id: str = "",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tenant_id: Optional[str] = None,
):
    """Get site progress data - multi-week breakdown"""
    user_session = await get_session_user(request)
    session_tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        tenant_id = session_tenant_id

    if not tenant_id:
        return {"success": False, "error": "Please select a tenant"}
    if not site_id:
        return {"success": False, "error": "Please select a site"}

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # Get site info
            site_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/entities",
                headers=headers,
                params={"id": f"eq.{site_id}", "select": "id,name,address"}
            )
            site_info = {"name": "Unknown Site", "address": ""}
            if site_resp.status_code == 200 and site_resp.json():
                site_info = site_resp.json()[0]

            # Get timesheets
            ts_params = {
                "select": "user_id,work_date,hours_worked,work_description,plans_for_tomorrow,users(name)",
                "tenant_id": f"eq.{tenant_id}",
                "site_id": f"eq.{site_id}",
                "order": "work_date.asc"
            }
            if start_date and end_date:
                ts_params["and"] = f"(work_date.gte.{start_date},work_date.lte.{end_date})"

            ts_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/timesheets",
                headers=headers,
                params=ts_params
            )
            timesheets = ts_resp.json() if ts_resp.status_code == 200 else []

            # Get site progress updates
            su_params = {
                "select": "update_date,main_focus,work_progress,issues,delays,site_conditions,follow_up_actions,is_wet_weather_closure,has_urgent_issues,has_delays,has_safety_concerns,identified_blockers,flagged_concerns,extracted_action_items,user_id",
                "tenant_id": f"eq.{tenant_id}",
                "site_id": f"eq.{site_id}",
                "order": "update_date.asc"
            }
            if start_date and end_date:
                su_params["and"] = f"(update_date.gte.{start_date},update_date.lte.{end_date})"

            su_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/site_progress_updates",
                headers=headers,
                params=su_params
            )
            site_updates = su_resp.json() if su_resp.status_code == 200 else []

            # Fetch site notes for this site + period
            sn_params = {
                "select": "id,note_text,created_at,admin_user_id,admin_users(username)",
                "tenant_id": f"eq.{tenant_id}",
                "site_id": f"eq.{site_id}",
                "order": "created_at.asc"
            }
            if start_date and end_date:
                sn_params["and"] = f"(created_at.gte.{start_date}T00:00:00,created_at.lte.{end_date}T23:59:59)"

            sn_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/site_notes",
                headers=headers,
                params=sn_params
            )
            site_notes = sn_resp.json() if sn_resp.status_code == 200 else []

            # Group into weeks (Mon-Sun)
            from datetime import date as date_type, timedelta
            weeks = {}

            def get_week_start(d_str):
                d = date_type.fromisoformat(d_str)
                return d - timedelta(days=d.weekday())  # Monday

            # Build users map from timesheets
            users = {}
            for entry in timesheets:
                uid = entry["user_id"]
                users[uid] = entry.get("users", {}).get("name", "Unknown")

            # Group timesheets by week
            for entry in timesheets:
                ws = get_week_start(entry["work_date"])
                we = ws + timedelta(days=6)
                key = ws.isoformat()
                if key not in weeks:
                    weeks[key] = {
                        "week_start": ws.isoformat(),
                        "week_end": we.isoformat(),
                        "hours": 0,
                        "workers": set(),
                        "work_descriptions": [],
                        "raw_work_items": [],
                        "plans": [],
                        "risks": [],
                        "conditions": [],
                    }
                weeks[key]["hours"] += float(entry["hours_worked"])
                weeks[key]["workers"].add(entry["user_id"])
                desc = entry.get("work_description", "")
                if desc and desc.strip():
                    weeks[key]["work_descriptions"].append(desc.strip())
                    weeks[key]["raw_work_items"].append({
                        "text": desc.strip(),
                        "user": users.get(entry["user_id"], "Unknown"),
                        "date": entry["work_date"]
                    })
                plan = entry.get("plans_for_tomorrow", "")
                if plan and plan.strip():
                    weeks[key]["plans"].append(plan.strip())

            # Group site updates by week
            for update in site_updates:
                ud = update.get("update_date", "")
                if not ud:
                    continue
                ws = get_week_start(ud)
                we = ws + timedelta(days=6)
                key = ws.isoformat()
                if key not in weeks:
                    weeks[key] = {
                        "week_start": ws.isoformat(),
                        "week_end": we.isoformat(),
                        "hours": 0,
                        "workers": set(),
                        "work_descriptions": [],
                        "raw_work_items": [],
                        "plans": [],
                        "risks": [],
                        "conditions": [],
                    }
                progress = update.get("work_progress", "")
                if progress and progress.strip():
                    weeks[key]["work_descriptions"].append(progress.strip())
                    weeks[key]["raw_work_items"].append({
                        "text": progress.strip(),
                        "user": users.get(update.get("user_id"), ""),
                        "date": update.get("update_date", "")
                    })
                focus = update.get("main_focus", "")
                if focus and focus.strip():
                    weeks[key]["work_descriptions"].append(focus.strip())
                    weeks[key]["raw_work_items"].append({
                        "text": focus.strip(),
                        "user": users.get(update.get("user_id"), ""),
                        "date": update.get("update_date", "")
                    })

                # Risks
                if update.get("issues"):
                    weeks[key]["risks"].append(f"Issue: {update['issues']}")
                if update.get("delays"):
                    weeks[key]["risks"].append(f"Delay: {update['delays']}")
                for b in (update.get("identified_blockers") or []):
                    if isinstance(b, dict):
                        weeks[key]["risks"].append(f"{b.get('blocker_type', 'Blocker')}: {b.get('description', '')}")
                for c in (update.get("flagged_concerns") or []):
                    if isinstance(c, dict):
                        weeks[key]["risks"].append(f"{c.get('severity', 'Concern')}: {c.get('description', '')}")

                # Conditions
                cond = update.get("site_conditions", "")
                if cond and cond.strip():
                    weeks[key]["conditions"].append(cond.strip())
                if update.get("is_wet_weather_closure"):
                    weeks[key]["conditions"].append("Wet weather closure")

                # Plans
                fa = update.get("follow_up_actions", "")
                if fa and fa.strip():
                    weeks[key]["plans"].append(fa.strip())

            # Group site notes by week
            for note in site_notes:
                note_ts = note.get("created_at", "")
                if not note_ts:
                    continue
                note_date_str = note_ts[:10]
                ws = get_week_start(note_date_str)
                we = ws + timedelta(days=6)
                key = ws.isoformat()
                if key not in weeks:
                    weeks[key] = {
                        "week_start": ws.isoformat(),
                        "week_end": we.isoformat(),
                        "hours": 0,
                        "workers": set(),
                        "work_descriptions": [],
                        "raw_work_items": [],
                        "plans": [],
                        "risks": [],
                        "conditions": [],
                    }
                note_text = note.get("note_text", "")
                if note_text and note_text.strip():
                    author = note.get("admin_users", {}).get("username", "Admin")
                    weeks[key]["work_descriptions"].append(f"[Site Note] {note_text.strip()}")
                    weeks[key]["raw_work_items"].append({
                        "text": f"[Site Note] {note_text.strip()}",
                        "user": author,
                        "date": note_date_str
                    })

            # Fetch weather for the full period
            from app.admin.weather import get_weather_for_site
            weather = {}
            site_address = site_info.get("address", "")
            if site_address and start_date and end_date:
                tenant_tz_resp = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                    headers=headers,
                    params={"id": f"eq.{tenant_id}", "select": "timezone"}
                )
                tenant_tz = ""
                if tenant_tz_resp.status_code == 200 and tenant_tz_resp.json():
                    tenant_tz = tenant_tz_resp.json()[0].get("timezone", "")
                weather = await get_weather_for_site(
                    site_id, site_address, start_date, end_date,
                    tenant_timezone=tenant_tz,
                )

            weather_location = ""
            if isinstance(weather.get("_meta"), dict):
                weather_location = weather["_meta"].get("location", "")

            # AI-summarise work items per week (uses shared cache with Site Weekly Report)
            from app.admin.work_summary import summarise_work_items

            # Convert to list sorted by week, attach daily weather and AI summary
            weeks_list = []
            for key in sorted(weeks.keys()):
                w = weeks[key]

                # Build daily weather for this week (Mon-Sun)
                week_weather = []
                ws = date_type.fromisoformat(w["week_start"])
                for i in range(7):
                    d = ws + timedelta(days=i)
                    ds = d.isoformat()
                    dw = weather.get(ds)
                    if isinstance(dw, dict) and dw.get("temperature_max") is not None:
                        week_weather.append({
                            "date": ds,
                            "day_label": d.strftime("%a"),
                            "temp_max": round(dw.get("temperature_max", 0)),
                            "temp_min": round(dw.get("temperature_min", 0)),
                            "description": dw.get("weather_description", ""),
                            "icon": dw.get("weather_icon", "cloud"),
                            "rain_mm": round(dw.get("precipitation_mm", 0) or 0, 1),
                        })

                # AI-clean the work summary (cached per site+week — shared with Site Weekly Report)
                raw_items = w.get("raw_work_items", [])
                work_categories = []
                if raw_items:
                    work_categories = await summarise_work_items(
                        raw_items, users,
                        tenant_id=tenant_id, site_id=site_id,
                        week_start=w["week_start"], week_end=w["week_end"],
                    )

                # Build a flat text summary from the AI categories for display
                ai_summary = ""
                if work_categories:
                    parts = []
                    for cat in work_categories:
                        items = cat.get("items", [])
                        for item in items:
                            parts.append(item.get("text", ""))
                    ai_summary = "; ".join(parts[:6]) if parts else ""

                weeks_list.append({
                    "week_start": w["week_start"],
                    "week_end": w["week_end"],
                    "total_hours": round(w["hours"], 1),
                    "worker_count": len(w["workers"]),
                    "work_summary": ai_summary or ("; ".join(w["work_descriptions"][:5]) if w["work_descriptions"] else "No updates recorded"),
                    "work_categories": work_categories,
                    "risks": w["risks"],
                    "conditions": "; ".join(w["conditions"]) if w["conditions"] else "",
                    "plans": "; ".join(w["plans"][:3]) if w["plans"] else "",
                    "weather": week_weather,
                })

            total_hours = sum(w["total_hours"] for w in weeks_list)

            return {
                "success": True,
                "site": site_info,
                "weeks": weeks_list,
                "weather_location": weather_location,
                "summary": {
                    "total_hours": round(total_hours, 1),
                    "total_weeks": len(weeks_list),
                    "total_risks": sum(len(w["risks"]) for w in weeks_list),
                }
            }

    except Exception as e:
        logger.error(f"Error fetching site progress data: {e}")
        return {"success": False, "error": str(e)}


@router.get("/admin/reports/site-progress/pdf")
async def download_site_progress_pdf(
    request: Request,
    site_id: str = "",
    start_date: str = "",
    end_date: str = "",
    flavour: str = "client",
    tenant_id: Optional[str] = None,
):
    """Generate and download site progress PDF"""
    from fastapi.responses import Response
    from app.admin.pdf_generator import generate_site_progress_pdf
    from datetime import date as date_type

    user_session = await get_session_user(request)
    session_tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        tenant_id = session_tenant_id

    if not tenant_id or not site_id or not start_date or not end_date:
        raise HTTPException(status_code=400, detail="tenant_id, site_id, start_date and end_date required")

    if flavour not in ("client", "internal"):
        flavour = "client"

    try:
        # Reuse the data endpoint logic
        # Simulate request to get_site_progress_data
        data_result = await get_site_progress_data(
            request=request,
            site_id=site_id,
            start_date=start_date,
            end_date=end_date,
            tenant_id=tenant_id,
        )

        if not data_result.get("success"):
            raise HTTPException(status_code=500, detail=data_result.get("error", "Failed to fetch data"))

        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }
            tenant_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                headers=headers,
                params={"id": f"eq.{tenant_id}", "select": "name"}
            )
            tenant_name = "Unknown Company"
            if tenant_resp.status_code == 200 and tenant_resp.json():
                tenant_name = tenant_resp.json()[0]["name"]

        site_info = data_result["site"]
        weeks_data = []
        for w in data_result["weeks"]:
            weeks_data.append({
                "week_start": date_type.fromisoformat(w["week_start"]),
                "week_end": date_type.fromisoformat(w["week_end"]),
                "total_hours": w["total_hours"],
                "worker_count": w["worker_count"],
                "work_summary": w["work_summary"],
                "risks": w.get("risks", []),
                "conditions": w.get("conditions", ""),
                "plans": w.get("plans", ""),
            })

        pdf_bytes = generate_site_progress_pdf(
            tenant_name=tenant_name,
            site_name=site_info.get("name", "Unknown Site"),
            site_address=site_info.get("address", ""),
            period_start=date_type.fromisoformat(start_date),
            period_end=date_type.fromisoformat(end_date),
            weeks_data=weeks_data,
            flavour=flavour,
        )

        site_name_clean = site_info.get("name", "site").replace(" ", "_")
        filename = f"progress_{site_name_clean}_{flavour}_{start_date}_to_{end_date}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating site progress PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# SITE NOTES
# ============================================

@router.post("/admin/site-notes")
async def create_site_note(
    request: Request,
    site_id: str = Form(...),
    tenant_id: str = Form(...),
    note_text: str = Form(...),
    attachments: list = None,
):
    """Create a site note with optional file attachments"""
    import uuid as uuid_mod

    user_session = await get_session_user(request)
    admin_user_id = user_session.get("user_id")
    is_super_admin = user_session.get("role") == "super_admin"

    # Tenant admins can only create notes for their own tenant
    if not is_super_admin:
        tenant_id = user_session.get("tenant_id")

    if not tenant_id or not site_id or not note_text.strip():
        return {"success": False, "error": "Tenant, site, and note text are required"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
            }

            # Handle file uploads to Supabase Storage
            attachment_list = []
            form = await request.form()
            files = form.getlist("files")

            for f in files:
                if hasattr(f, 'filename') and f.filename:
                    file_bytes = await f.read()
                    if not file_bytes:
                        continue

                    # Generate unique path
                    ext = f.filename.rsplit(".", 1)[-1] if "." in f.filename else "bin"
                    storage_path = f"{tenant_id}/{site_id}/{uuid_mod.uuid4().hex[:12]}.{ext}"

                    # Upload to Supabase Storage
                    upload_resp = await client.post(
                        f"{os.getenv('SUPABASE_URL')}/storage/v1/object/site-note-attachments/{storage_path}",
                        headers={
                            "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                            "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                            "Content-Type": f.content_type or "application/octet-stream",
                        },
                        content=file_bytes,
                    )

                    if upload_resp.status_code in [200, 201]:
                        public_url = f"{os.getenv('SUPABASE_URL')}/storage/v1/object/public/site-note-attachments/{storage_path}"
                        attachment_list.append({
                            "filename": f.filename,
                            "url": public_url,
                            "content_type": f.content_type or "",
                            "size": len(file_bytes),
                        })
                        logger.info(f"Uploaded attachment: {f.filename} -> {storage_path}")
                    else:
                        logger.error(f"Failed to upload {f.filename}: {upload_resp.status_code} {upload_resp.text}")

            # Create the note
            note_data = {
                "id": str(uuid_mod.uuid4()),
                "tenant_id": tenant_id,
                "site_id": site_id,
                "admin_user_id": admin_user_id,
                "note_text": note_text.strip(),
                "attachments": json.dumps(attachment_list),
            }

            resp = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/site_notes",
                headers={
                    **headers,
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
                json=note_data,
            )

            if resp.status_code not in [200, 201]:
                logger.error(f"Failed to create site note: {resp.status_code} {resp.text}")
                return {"success": False, "error": "Failed to create note"}

            note = resp.json()[0] if resp.json() else note_data

            # Invalidate work summary cache for the affected week
            note_date = datetime.now(timezone.utc).date()
            week_start = note_date - timedelta(days=note_date.weekday())  # Monday
            week_end = week_start + timedelta(days=6)

            await client.delete(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/work_summary_cache",
                headers=headers,
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "site_id": f"eq.{site_id}",
                    "week_start": f"eq.{week_start.isoformat()}",
                    "week_end": f"eq.{week_end.isoformat()}",
                }
            )
            logger.info(f"Invalidated work summary cache for site={site_id} week={week_start}")

            return {"success": True, "note": note}

    except Exception as e:
        logger.error(f"Error creating site note: {e}")
        return {"success": False, "error": str(e)}


@router.get("/admin/site-notes/data")
async def get_site_notes(
    request: Request,
    site_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tenant_id: Optional[str] = None,
    limit: int = 50,
):
    """Get site notes with optional filters"""
    user_session = await get_session_user(request)
    session_tenant_id = user_session.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        tenant_id = session_tenant_id

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            params = {
                "select": "id,tenant_id,site_id,admin_user_id,note_text,attachments,created_at,admin_users(username,email)",
                "order": "created_at.desc",
                "limit": str(limit),
            }

            if tenant_id:
                params["tenant_id"] = f"eq.{tenant_id}"
            if site_id:
                params["site_id"] = f"eq.{site_id}"

            if start_date and end_date:
                params["and"] = f"(created_at.gte.{start_date}T00:00:00,created_at.lte.{end_date}T23:59:59)"
            elif start_date:
                params["created_at"] = f"gte.{start_date}T00:00:00"
            elif end_date:
                params["created_at"] = f"lte.{end_date}T23:59:59"

            resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/site_notes",
                headers=headers,
                params=params,
            )

            if resp.status_code != 200:
                return {"success": False, "error": "Failed to fetch notes"}

            notes = resp.json()

            # Enrich with site names
            if notes:
                site_ids = list(set(n["site_id"] for n in notes))
                sites_resp = await client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/entities",
                    headers=headers,
                    params={
                        "id": f"in.({','.join(site_ids)})",
                        "select": "id,name"
                    }
                )
                site_map = {}
                if sites_resp.status_code == 200:
                    site_map = {s["id"]: s["name"] for s in sites_resp.json()}

                for note in notes:
                    note["site_name"] = site_map.get(note["site_id"], "Unknown Site")
                    # Parse attachments if stored as string
                    if isinstance(note.get("attachments"), str):
                        try:
                            note["attachments"] = json.loads(note["attachments"])
                        except json.JSONDecodeError:
                            note["attachments"] = []

            return {"success": True, "notes": notes}

    except Exception as e:
        logger.error(f"Error fetching site notes: {e}")
        return {"success": False, "error": str(e)}


@router.get("/admin/site-notes", response_class=HTMLResponse)
async def site_notes_page(request: Request):
    """Site notes timeline page"""
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    return templates.TemplateResponse(
        "reports/site_notes.html",
        {"request": request, "page_title": "Site Notes"}
    )


# ============================================
# BILLING & INVOICING (Super Admin Only)
# ============================================

@router.get("/admin/billing", response_class=HTMLResponse)
async def billing_page(request: Request):
    """Billing & Invoicing dashboard - super admin only"""
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")
    return templates.TemplateResponse(
        "reports/billing.html",
        {"request": request, "page_title": "Billing & Invoicing"}
    )


@router.get("/admin/billing/config/{tenant_id}")
async def get_billing_config(tenant_id: str, request: Request):
    """Get billing configuration for a tenant"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_billing_config",
                headers=headers,
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "select": "*"
                }
            )

            if response.status_code == 200 and response.json():
                config = response.json()[0]
                return {"success": True, "config": config}
            else:
                # Return defaults
                return {"success": True, "config": {
                    "platform_fee": 500.00,
                    "platform_discount_percent": 0,
                    "cost_per_call_timesheet": 1.00,
                    "cost_per_call_voice_notes": 1.00,
                    "cost_per_call_site_updates": 2.00,
                    "usd_to_aud_rate": 1.5500,
                    "billing_cycle_day": None,
                    "invoice_prefix": "INV"
                }}

    except Exception as e:
        logger.error(f"Error fetching billing config: {e}")
        return {"success": False, "error": str(e)}


@router.post("/admin/billing/config/{tenant_id}")
async def save_billing_config(tenant_id: str, request: Request):
    """Save billing configuration for a tenant (upsert)"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    body = await request.json()

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            }

            config_data = {
                "tenant_id": tenant_id,
                "platform_fee": body.get("platform_fee", 500.00),
                "platform_discount_percent": body.get("platform_discount_percent", 0),
                "cost_per_call_timesheet": body.get("cost_per_call_timesheet", 1.00),
                "cost_per_call_voice_notes": body.get("cost_per_call_voice_notes", 1.00),
                "cost_per_call_site_updates": body.get("cost_per_call_site_updates", 2.00),
                "usd_to_aud_rate": body.get("usd_to_aud_rate", 1.5500),
                "billing_cycle_day": body.get("billing_cycle_day") or None,
                "invoice_prefix": body.get("invoice_prefix", "INV"),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }

            # Check if exists
            check = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_billing_config",
                headers={
                    "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={"tenant_id": f"eq.{tenant_id}", "select": "id"}
            )

            if check.status_code == 200 and check.json():
                # Update existing
                existing_id = check.json()[0]["id"]
                await client.patch(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_billing_config",
                    headers=headers,
                    params={"id": f"eq.{existing_id}"},
                    json=config_data
                )
            else:
                # Create new
                await client.post(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_billing_config",
                    headers=headers,
                    json=config_data
                )

            return {"success": True}

    except Exception as e:
        logger.error(f"Error saving billing config: {e}")
        return {"success": False, "error": str(e)}


@router.get("/admin/billing/preview")
async def preview_billing(
    request: Request,
    tenant_id: str = "",
    start_date: str = "",
    end_date: str = "",
):
    """Preview billable calls for a tenant in a date range"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    if not tenant_id or not start_date or not end_date:
        return {"success": False, "error": "tenant_id, start_date, and end_date required"}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # 1. Get billing config
            config_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_billing_config",
                headers=headers,
                params={"tenant_id": f"eq.{tenant_id}", "select": "*"}
            )
            if config_resp.status_code == 200 and config_resp.json():
                config = config_resp.json()[0]
            else:
                config = {
                    "platform_fee": 500.00,
                    "platform_discount_percent": 0,
                    "cost_per_call_timesheet": 1.00,
                    "cost_per_call_voice_notes": 1.00,
                    "cost_per_call_site_updates": 2.00,
                    "usd_to_aud_rate": 1.5500,
                }

            usd_to_aud = float(config.get("usd_to_aud_rate") or 1.55)

            # 1b. Get Jill's phone number + tenant timezone
            phone_resp, tz_resp = await asyncio.gather(
                client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/qr_signon_config",
                    headers=headers,
                    params={"tenant_id": f"eq.{tenant_id}", "select": "jill_phone_number"}
                ),
                client.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                    headers=headers,
                    params={"id": f"eq.{tenant_id}", "select": "timezone"}
                )
            )
            jill_phone = ""
            if phone_resp.status_code == 200 and phone_resp.json():
                jill_phone = phone_resp.json()[0].get("jill_phone_number", "") or ""

            # Convert date boundaries to UTC using the tenant's local timezone
            # so that e.g. "31 Mar 23:59 AEST" doesn't bleed into April UTC calls
            import pytz as pytz_mod
            from datetime import datetime as dt_cls
            tz_name = "Australia/Sydney"
            if tz_resp.status_code == 200 and tz_resp.json():
                tz_name = tz_resp.json()[0].get("timezone") or "Australia/Sydney"
            tz = pytz_mod.timezone(tz_name)
            start_utc = tz.localize(dt_cls.strptime(f"{start_date} 00:00:00", "%Y-%m-%d %H:%M:%S")).astimezone(pytz_mod.utc).isoformat()
            end_utc = tz.localize(dt_cls.strptime(f"{end_date} 23:59:59", "%Y-%m-%d %H:%M:%S")).astimezone(pytz_mod.utc).isoformat()

            # 2. Get calls from call_quality_assessments
            calls_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/call_quality_assessments",
                headers=headers,
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "call_type": "neq.greeter",
                    "and": f"(call_started_at.gte.{start_utc},call_started_at.lte.{end_utc})",
                    "select": "vapi_call_id,user_id,call_type,call_duration_seconds,call_cost,call_started_at,caller_phone,success_evaluation,task_completed",
                    "order": "call_started_at.asc",
                    "limit": "10000"
                }
            )

            if calls_resp.status_code != 200:
                return {"success": False, "error": "Failed to fetch call data"}

            all_calls = calls_resp.json()

            # 3. Enrich with VAPI API data (duration + cost)
            # CQA table often has null duration/cost, so fetch from VAPI API
            vapi_api_key = os.getenv("VAPI_API_KEY")
            vapi_data_cache = {}  # call_id -> {cost, duration}
            if vapi_api_key:
                try:
                    # Fetch multiple pages if needed
                    for page_offset in range(0, 500, 100):
                        vapi_resp = await client.get(
                            "https://api.vapi.ai/call",
                            headers={"Authorization": f"Bearer {vapi_api_key}"},
                            params={"limit": "100"},
                            timeout=30.0,
                        )
                        if vapi_resp.status_code == 200:
                            vapi_calls = vapi_resp.json()
                            for vc in vapi_calls:
                                vc_id = vc.get("id", "")
                                vc_cost = float(vc.get("cost") or 0)
                                vc_duration = 0
                                started = vc.get("startedAt")
                                ended = vc.get("endedAt")
                                if started and ended:
                                    try:
                                        from datetime import datetime as dt_cls
                                        s = dt_cls.fromisoformat(started.replace("Z", "+00:00"))
                                        e = dt_cls.fromisoformat(ended.replace("Z", "+00:00"))
                                        vc_duration = int((e - s).total_seconds())
                                    except Exception:
                                        pass
                                vapi_data_cache[vc_id] = {"cost": vc_cost, "duration": vc_duration}
                            if len(vapi_calls) < 100:
                                break
                        else:
                            break
                except Exception as e:
                    logger.warning(f"Could not fetch VAPI call data: {e}")

            # Filter billable calls: duration >= 30s
            min_duration_seconds = 30
            billable_calls = []

            for c in all_calls:
                vapi_call_id = c.get("vapi_call_id", "")
                vapi_info = vapi_data_cache.get(vapi_call_id, {})

                # Use VAPI API duration first, fall back to CQA
                duration = vapi_info.get("duration", 0) or int(c.get("call_duration_seconds") or 0)
                if duration < min_duration_seconds:
                    continue

                vapi_cost_usd = vapi_info.get("cost", 0) or float(c.get("call_cost") or 0)
                vapi_cost_aud = vapi_cost_usd * usd_to_aud

                c["call_duration_seconds"] = duration
                c["actual_cost_usd"] = round(vapi_cost_usd, 4)
                c["actual_cost_aud"] = round(vapi_cost_aud, 4)
                billable_calls.append(c)

            # 4. Enrich with user names
            user_ids = list(set(c.get("user_id") for c in billable_calls if c.get("user_id")))
            user_map = {}
            if user_ids:
                for i in range(0, len(user_ids), 50):
                    batch = user_ids[i:i+50]
                    user_resp = await client.get(
                        f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                        headers=headers,
                        params={
                            "id": f"in.({','.join(batch)})",
                            "select": "id,name"
                        }
                    )
                    if user_resp.status_code == 200:
                        for u in user_resp.json():
                            user_map[u["id"]] = u["name"]

            # 5. Enrich with site names + completion status (via skill tables)
            vapi_ids = [c["vapi_call_id"] for c in billable_calls if c.get("vapi_call_id")]
            site_map = {}  # vapi_call_id -> site_name
            completed_calls = set()  # vapi_call_ids where the skill objective was met

            if vapi_ids:
                # Timesheets — check for saved entries (proof of completion)
                for i in range(0, len(vapi_ids), 50):
                    batch = vapi_ids[i:i+50]
                    ts_resp = await client.get(
                        f"{os.getenv('SUPABASE_URL')}/rest/v1/timesheets",
                        headers=headers,
                        params={
                            "vapi_call_id": f"in.({','.join(batch)})",
                            "select": "vapi_call_id,site_id"
                        }
                    )
                    if ts_resp.status_code == 200:
                        site_ids_needed = set()
                        ts_site_map = {}
                        for ts in ts_resp.json():
                            completed_calls.add(ts["vapi_call_id"])
                            if ts.get("site_id"):
                                site_ids_needed.add(ts["site_id"])
                                ts_site_map[ts["vapi_call_id"]] = ts["site_id"]

                        if site_ids_needed:
                            ent_resp = await client.get(
                                f"{os.getenv('SUPABASE_URL')}/rest/v1/entities",
                                headers=headers,
                                params={
                                    "id": f"in.({','.join(site_ids_needed)})",
                                    "select": "id,name"
                                }
                            )
                            if ent_resp.status_code == 200:
                                entity_names = {e["id"]: e["name"] for e in ent_resp.json()}
                                for vcid, sid in ts_site_map.items():
                                    site_map[vcid] = entity_names.get(sid, "")

                # Voice notes — check for saved entries
                for i in range(0, len(vapi_ids), 50):
                    batch = vapi_ids[i:i+50]
                    vn_resp = await client.get(
                        f"{os.getenv('SUPABASE_URL')}/rest/v1/voice_notes",
                        headers=headers,
                        params={
                            "vapi_call_id": f"in.({','.join(batch)})",
                            "select": "vapi_call_id"
                        }
                    )
                    if vn_resp.status_code == 200:
                        for vn in vn_resp.json():
                            completed_calls.add(vn["vapi_call_id"])

                # Site progress updates — check for saved entries
                for i in range(0, len(vapi_ids), 50):
                    batch = vapi_ids[i:i+50]
                    sp_resp = await client.get(
                        f"{os.getenv('SUPABASE_URL')}/rest/v1/site_progress_updates",
                        headers=headers,
                        params={
                            "vapi_call_id": f"in.({','.join(batch)})",
                            "select": "vapi_call_id"
                        }
                    )
                    if sp_resp.status_code == 200:
                        for sp in sp_resp.json():
                            completed_calls.add(sp["vapi_call_id"])

            # 6. Build call list with billing rates
            rate_map = {
                "timesheet": float(config.get("cost_per_call_timesheet") or 1.00),
                "voice_notes": float(config.get("cost_per_call_voice_notes") or 1.00),
                "site_updates": float(config.get("cost_per_call_site_updates") or 2.00),
            }

            calls_list = []
            type_breakdown = {}
            total_billed = 0
            total_actual_aud = 0

            for c in billable_calls:
                call_type = c.get("call_type", "unknown")
                unit_cost = rate_map.get(call_type, 1.00)
                actual_aud = c.get("actual_cost_aud", 0)

                vapi_cid = c.get("vapi_call_id", "")
                call_entry = {
                    "call_date": c.get("call_started_at"),
                    "user_name": user_map.get(c.get("user_id"), "Unknown"),
                    "call_type": call_type,
                    "site_name": site_map.get(vapi_cid, ""),
                    "duration_seconds": int(c.get("call_duration_seconds") or 0),
                    "unit_cost": unit_cost,
                    "actual_cost_usd": c.get("actual_cost_usd", 0),
                    "actual_cost_aud": actual_aud,
                    "vapi_call_id": vapi_cid,
                    "caller_phone": c.get("caller_phone", ""),
                    "number_called": jill_phone,
                    "completed": vapi_cid in completed_calls,
                }
                calls_list.append(call_entry)
                total_billed += unit_cost
                total_actual_aud += actual_aud

                if call_type not in type_breakdown:
                    type_breakdown[call_type] = {"count": 0, "rate": unit_cost, "subtotal": 0}
                type_breakdown[call_type]["count"] += 1
                type_breakdown[call_type]["subtotal"] += unit_cost

            # 7. Platform fee
            platform_fee = float(config.get("platform_fee") or 500.00)
            discount_pct = float(config.get("platform_discount_percent") or 0)
            platform_after_discount = round(platform_fee * (1 - discount_pct / 100), 2)
            total_amount = round(total_billed + platform_after_discount, 2)

            return {
                "success": True,
                "calls": calls_list,
                "summary": {
                    "total_calls": len(calls_list),
                    "total_billed": round(total_billed, 2),
                    "total_actual_aud": round(total_actual_aud, 2),
                    "margin": round(total_billed - total_actual_aud, 2),
                    "margin_percent": round((total_billed - total_actual_aud) / total_billed * 100, 1) if total_billed > 0 else 0,
                    "platform_fee": platform_fee,
                    "platform_discount_percent": discount_pct,
                    "platform_fee_after_discount": platform_after_discount,
                    "total_amount": total_amount,
                    "type_breakdown": type_breakdown,
                    "usd_to_aud_rate": usd_to_aud,
                }
            }

    except Exception as e:
        logger.error(f"Error previewing billing: {e}")
        return {"success": False, "error": str(e)}


@router.post("/admin/billing/generate")
async def generate_invoice(request: Request):
    """Generate an invoice from preview data"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    body = await request.json()
    tenant_id = body.get("tenant_id")
    start_date = body.get("start_date")
    end_date = body.get("end_date")

    if not tenant_id or not start_date or not end_date:
        return {"success": False, "error": "tenant_id, start_date, and end_date required"}

    try:
        # First, run the preview to get fresh data
        preview_result = await preview_billing(
            request=request,
            tenant_id=tenant_id,
            start_date=start_date,
            end_date=end_date,
        )

        if not preview_result.get("success"):
            return {"success": False, "error": preview_result.get("error", "Preview failed")}

        calls = preview_result["calls"]
        summary = preview_result["summary"]

        async with httpx.AsyncClient() as client:
            read_headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # Check for overlapping invoices (calls already billed)
            preview_vapi_ids = [c["vapi_call_id"] for c in calls if c.get("vapi_call_id")]
            if preview_vapi_ids:
                already_billed = set()
                for i in range(0, len(preview_vapi_ids), 50):
                    batch = preview_vapi_ids[i:i+50]
                    li_resp = await client.get(
                        f"{os.getenv('SUPABASE_URL')}/rest/v1/invoice_line_items",
                        headers=read_headers,
                        params={
                            "vapi_call_id": f"in.({','.join(batch)})",
                            "select": "vapi_call_id,invoice_id"
                        }
                    )
                    if li_resp.status_code == 200:
                        for li in li_resp.json():
                            already_billed.add(li["vapi_call_id"])

                if already_billed:
                    overlap_count = len(already_billed)
                    return {
                        "success": False,
                        "error": f"{overlap_count} call(s) in this period have already been invoiced. Adjust the date range to avoid overlap."
                    }
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                "Content-Type": "application/json",
                "Prefer": "return=representation"
            }
            read_headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # Get invoice prefix from config
            config_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenant_billing_config",
                headers=read_headers,
                params={"tenant_id": f"eq.{tenant_id}", "select": "invoice_prefix"}
            )
            prefix = "INV"
            if config_resp.status_code == 200 and config_resp.json():
                prefix = config_resp.json()[0].get("invoice_prefix") or "INV"

            # Get next invoice number
            inv_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/invoices",
                headers=read_headers,
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "select": "invoice_number",
                    "order": "created_at.desc",
                    "limit": "1"
                }
            )

            next_num = 1
            if inv_resp.status_code == 200 and inv_resp.json():
                last_number = inv_resp.json()[0]["invoice_number"]
                try:
                    next_num = int(last_number.split("-")[-1]) + 1
                except (ValueError, IndexError):
                    next_num = 1

            invoice_number = f"{prefix}-{next_num:03d}"

            # Create invoice
            invoice_data = {
                "tenant_id": tenant_id,
                "invoice_number": invoice_number,
                "period_start": start_date,
                "period_end": end_date,
                "total_calls": summary["total_calls"],
                "total_call_cost": summary["total_billed"],
                "platform_fee": summary["platform_fee"],
                "platform_discount_percent": summary["platform_discount_percent"],
                "platform_fee_after_discount": summary["platform_fee_after_discount"],
                "total_amount": summary["total_amount"],
                "total_actual_cost_aud": summary["total_actual_aud"],
                "usd_to_aud_rate": summary["usd_to_aud_rate"],
                "status": "draft",
            }

            inv_create = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/invoices",
                headers=headers,
                json=invoice_data
            )

            if inv_create.status_code not in (200, 201):
                return {"success": False, "error": f"Failed to create invoice: {inv_create.text}"}

            invoice = inv_create.json()[0]
            invoice_id = invoice["id"]

            # Create line items (bulk insert)
            if calls:
                line_items = []
                for c in calls:
                    line_items.append({
                        "invoice_id": invoice_id,
                        "call_date": c["call_date"],
                        "user_name": c["user_name"],
                        "call_type": c["call_type"],
                        "site_name": c.get("site_name", ""),
                        "duration_seconds": c["duration_seconds"],
                        "unit_cost": c["unit_cost"],
                        "actual_cost_usd": c.get("actual_cost_usd", 0),
                        "actual_cost_aud": c.get("actual_cost_aud", 0),
                        "vapi_call_id": c.get("vapi_call_id", ""),
                    })

                li_headers = {**headers, "Prefer": "return=minimal"}
                await client.post(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/invoice_line_items",
                    headers=li_headers,
                    json=line_items
                )

            return {"success": True, "invoice": invoice}

    except Exception as e:
        logger.error(f"Error generating invoice: {e}")
        return {"success": False, "error": str(e)}


@router.get("/admin/billing/invoices")
async def list_invoices(request: Request, tenant_id: str = ""):
    """List invoices for a tenant"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    if not tenant_id:
        return {"success": False, "error": "tenant_id required"}

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/invoices",
                headers=headers,
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "select": "*",
                    "order": "created_at.desc"
                }
            )

            if response.status_code == 200:
                return {"success": True, "invoices": response.json()}
            return {"success": False, "error": "Failed to fetch invoices"}

    except Exception as e:
        logger.error(f"Error listing invoices: {e}")
        return {"success": False, "error": str(e)}


@router.post("/admin/billing/invoices/{invoice_id}/status")
async def update_invoice_status(invoice_id: str, request: Request):
    """Update invoice status (draft/sent/paid)"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    body = await request.json()
    new_status = body.get("status")

    if new_status not in ("draft", "sent", "paid"):
        return {"success": False, "error": "Invalid status"}

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            }

            await client.patch(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/invoices",
                headers=headers,
                params={"id": f"eq.{invoice_id}"},
                json={"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()}
            )

            return {"success": True}

    except Exception as e:
        logger.error(f"Error updating invoice status: {e}")
        return {"success": False, "error": str(e)}


@router.delete("/admin/billing/invoices/{invoice_id}")
async def delete_invoice(invoice_id: str, request: Request):
    """Delete an invoice and its line items (super admin only)"""
    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                "Prefer": "return=minimal"
            }

            # Delete line items first (FK constraint)
            await client.delete(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/invoice_line_items",
                headers=headers,
                params={"invoice_id": f"eq.{invoice_id}"}
            )

            # Delete the invoice
            resp = await client.delete(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/invoices",
                headers=headers,
                params={"id": f"eq.{invoice_id}"}
            )

            if resp.status_code in (200, 204):
                return {"success": True}
            return {"success": False, "error": f"Delete failed: {resp.text}"}

    except Exception as e:
        logger.error(f"Error deleting invoice: {e}")
        return {"success": False, "error": str(e)}


@router.get("/admin/billing/invoices/{invoice_id}/pdf")
async def download_invoice_pdf(invoice_id: str, request: Request):
    """Generate and download invoice PDF"""
    from fastapi.responses import Response
    from app.admin.pdf_generator import generate_invoice_pdf

    user_session = await get_session_user(request)
    if user_session.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            }

            # Get invoice
            inv_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/invoices",
                headers=headers,
                params={"id": f"eq.{invoice_id}", "select": "*"}
            )

            if inv_resp.status_code != 200 or not inv_resp.json():
                raise HTTPException(status_code=404, detail="Invoice not found")

            invoice = inv_resp.json()[0]

            # Get line items
            li_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/invoice_line_items",
                headers=headers,
                params={
                    "invoice_id": f"eq.{invoice_id}",
                    "select": "*",
                    "order": "call_date.asc"
                }
            )
            line_items = li_resp.json() if li_resp.status_code == 200 else []

            # Get tenant name
            tenant_resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/tenants",
                headers=headers,
                params={"id": f"eq.{invoice['tenant_id']}", "select": "name"}
            )
            tenant_name = "Unknown"
            if tenant_resp.status_code == 200 and tenant_resp.json():
                tenant_name = tenant_resp.json()[0]["name"]

            from datetime import date as date_type
            pdf_bytes = generate_invoice_pdf(
                tenant_name=tenant_name,
                invoice_number=invoice["invoice_number"],
                invoice_date=datetime.now().date(),
                period_start=date_type.fromisoformat(invoice["period_start"]),
                period_end=date_type.fromisoformat(invoice["period_end"]),
                platform_fee=float(invoice.get("platform_fee") or 0),
                platform_discount_percent=float(invoice.get("platform_discount_percent") or 0),
                platform_fee_after_discount=float(invoice.get("platform_fee_after_discount") or 0),
                total_call_cost=float(invoice.get("total_call_cost") or 0),
                total_amount=float(invoice.get("total_amount") or 0),
                line_items=line_items,
            )

            filename = f"invoice_{invoice['invoice_number']}_{tenant_name.replace(' ', '_')}.pdf"
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'}
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating invoice PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))
