# app/admin/routes.py - Admin UI routes
from fastapi import APIRouter, Request, Depends, HTTPException, Header, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
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
        return RedirectResponse(url="/admin", status_code=302)

    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request}
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

    # Choose template based on theme parameter
    template = "dashboard/index-modern.html" if theme == "modern" else "dashboard/index.html"

    return templates.TemplateResponse(
        template,
        {"request": request, "page_title": "Admin Dashboard"}
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
        from scripts.vapi_evals.eval_definitions import GREETER_EVALS, TIMESHEET_EVALS, FLOW_EVALS

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
