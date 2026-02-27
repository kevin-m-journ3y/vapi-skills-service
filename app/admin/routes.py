# app/admin/routes.py - Admin UI routes
from fastapi import APIRouter, Request, Depends, HTTPException, Header
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
import httpx
import os
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
                "select": "id,work_date,start_time,end_time,hours_worked,work_description,plans_for_tomorrow,site_id,user_id,users(name)",
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
                "select": "id,work_date,start_time,end_time,hours_worked,work_description,plans_for_tomorrow,site_id,user_id,users(name)",
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
