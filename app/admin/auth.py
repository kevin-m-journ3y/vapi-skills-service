"""
Admin Authentication Routes

Handles login, logout, and session management for admin users.
Uses HTTP-only secure cookies for session storage.
"""

from fastapi import APIRouter, Request, HTTPException, Response, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
import httpx
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
import logging

from app.auth_utils import verify_password, validate_password_strength, hash_password

logger = logging.getLogger(__name__)

router = APIRouter()

# Session configuration
SESSION_COOKIE_NAME = "admin_session"
SESSION_MAX_AGE = 8 * 60 * 60  # 8 hours in seconds


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    success: bool
    message: str
    user: Optional[dict] = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


async def get_admin_user_by_username(username: str) -> Optional[dict]:
    """Get admin user from database by username or email (case-insensitive)"""
    async with httpx.AsyncClient() as client:
        # Try to find by username first
        response = await client.get(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/admin_users",
            headers={
                "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            },
            params={
                "username": f"ilike.{username}",  # Case-insensitive match
                "is_active": "eq.true",
                "select": "id,username,email,password_hash,role,tenant_id,must_change_password,tenants(id,name)"
            }
        )

        if response.status_code == 200:
            users = response.json()
            if users:
                return users[0]

        # If not found by username, try email
        response = await client.get(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/admin_users",
            headers={
                "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            },
            params={
                "email": f"ilike.{username}",  # Case-insensitive match
                "is_active": "eq.true",
                "select": "id,username,email,password_hash,role,tenant_id,must_change_password,tenants(id,name)"
            }
        )

        if response.status_code == 200:
            users = response.json()
            if users:
                return users[0]

        return None


async def update_last_login(user_id: str):
    """Update last_login_at timestamp for user"""
    async with httpx.AsyncClient() as client:
        await client.patch(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/admin_users",
            headers={
                "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            },
            params={"id": f"eq.{user_id}"},
            json={"last_login_at": datetime.now(timezone.utc).isoformat()}
        )


async def get_user_permissions(user_id: str) -> list:
    """Get permissions for a tenant_admin user"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/admin_user_permissions",
            headers={
                "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
            },
            params={
                "admin_user_id": f"eq.{user_id}",
                "select": "permission_type"
            }
        )

        if response.status_code == 200:
            perms = response.json()
            return [p["permission_type"] for p in perms]

        return []


@router.post("/admin/auth/login")
async def login(request: Request, login_data: LoginRequest):
    """
    Login endpoint - authenticate user and create session

    Returns:
        JSON with success status and user info (excluding password hash)
        Sets HTTP-only secure cookie for session management
    """
    try:
        # Debug logging
        logger.info(f"Login attempt - username: {login_data.username}, password length: {len(login_data.password)}")

        # Get user from database
        user = await get_admin_user_by_username(login_data.username)

        if not user:
            logger.warning(f"Login attempt for non-existent user: {login_data.username}")
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid username or password"}
            )

        # Verify password
        password_valid = verify_password(login_data.password, user["password_hash"])
        logger.info(f"Password verification result: {password_valid}")

        if not password_valid:
            logger.warning(f"Failed login attempt for user: {login_data.username}")
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Invalid username or password"}
            )

        # Get permissions for tenant_admin users
        permissions = []
        if user["role"] == "tenant_admin":
            permissions = await get_user_permissions(user["id"])
        elif user["role"] == "super_admin":
            # Super admins have all permissions
            permissions = [
                "view_timesheets",
                "view_voice_notes",
                "manage_users",
                "manage_sites",
                "view_reports",
                "manage_settings"
            ]

        # Update last login
        await update_last_login(user["id"])

        # Check if user must change password on first login
        must_change_password = user.get("must_change_password", False)

        # Prepare session data
        session_data = {
            "user_id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"],
            "tenant_id": user.get("tenant_id"),
            "tenant_name": user.get("tenants", {}).get("name") if user.get("tenants") else None,
            "permissions": permissions,
            "must_change_password": must_change_password,
            "login_time": datetime.now(timezone.utc).isoformat()
        }

        # Store session in request.session (handled by SessionMiddleware)
        request.session["user"] = session_data

        logger.info(f"Successful login: {login_data.username} (role: {user['role']})")

        # Return user info (without password hash)
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Login successful",
                "user": {
                    "username": user["username"],
                    "email": user["email"],
                    "role": user["role"],
                    "tenant_id": user.get("tenant_id"),
                    "tenant_name": session_data["tenant_name"],
                    "permissions": permissions,
                    "must_change_password": must_change_password
                }
            }
        )

    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred during login"}
        )


@router.post("/admin/auth/logout")
async def logout(request: Request):
    """
    Logout endpoint - clear session

    Returns:
        JSON with success status
    """
    try:
        # Clear session
        request.session.clear()

        return JSONResponse(
            status_code=200,
            content={"success": True, "message": "Logged out successfully"}
        )

    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred during logout"}
        )


@router.get("/admin/auth/me")
async def get_current_user(request: Request):
    """
    Get current user from session

    Returns:
        JSON with user info if authenticated, 401 if not
    """
    user_session = request.session.get("user")

    if not user_session:
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": "Not authenticated"}
        )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "user": user_session
        }
    )


@router.post("/admin/auth/change-password")
async def change_password(request: Request, password_data: PasswordChangeRequest):
    """
    Change password for current user

    Returns:
        JSON with success status
    """
    user_session = request.session.get("user")

    if not user_session:
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": "Not authenticated"}
        )

    try:
        # Validate new password strength
        validation = validate_password_strength(password_data.new_password)
        if not validation["valid"]:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Password does not meet requirements",
                    "requirements": validation["requirements"]
                }
            )

        # Get current user from database
        user = await get_admin_user_by_username(user_session["username"])

        if not user:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "User not found"}
            )

        # Verify current password
        if not verify_password(password_data.current_password, user["password_hash"]):
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "Current password is incorrect"}
            )

        # Hash new password
        new_password_hash = hash_password(password_data.new_password)

        # Update password in database
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/admin_users",
                headers={
                    "apikey": os.getenv('SUPABASE_SERVICE_KEY'),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                params={"id": f"eq.{user['id']}"},
                json={"password_hash": new_password_hash, "must_change_password": False}
            )

            if response.status_code not in [200, 204]:
                logger.error(f"Failed to update password: {response.status_code} - {response.text}")
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "message": "Failed to update password"}
                )

        # Clear the must_change_password flag in session
        if user_session.get("must_change_password"):
            user_session["must_change_password"] = False
            request.session["user"] = user_session

        logger.info(f"Password changed for user: {user_session['username']}")

        return JSONResponse(
            status_code=200,
            content={"success": True, "message": "Password changed successfully"}
        )

    except Exception as e:
        logger.error(f"Change password error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while changing password"}
        )


async def require_authenticated_user(request: Request) -> dict:
    """
    Dependency to require authenticated user

    Raises:
        HTTPException: If user is not authenticated

    Returns:
        User session data
    """
    user_session = request.session.get("user")

    if not user_session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return user_session


async def require_permission(permission: str):
    """
    Dependency factory to require specific permission

    Args:
        permission: Permission type required (e.g., 'view_timesheets')

    Returns:
        Dependency function
    """
    async def check_permission(user_session: dict = Depends(require_authenticated_user)):
        # Super admins have all permissions
        if user_session["role"] == "super_admin":
            return user_session

        # Check if user has the required permission
        if permission not in user_session.get("permissions", []):
            raise HTTPException(status_code=403, detail=f"Permission denied: {permission}")

        return user_session

    return check_permission


async def require_super_admin(user_session: dict = Depends(require_authenticated_user)):
    """
    Dependency to require super admin role

    Raises:
        HTTPException: If user is not super admin

    Returns:
        User session data
    """
    if user_session["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")

    return user_session
