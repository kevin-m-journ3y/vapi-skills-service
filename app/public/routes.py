"""Public (unauthenticated) routes for QR site sign-on."""

import os
import logging
from typing import Optional
from fastapi import APIRouter, Request, Response, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.services.signon_service import (
    resolve_short_code,
    identify_user_by_phone,
    record_signon,
)
from app.services.photo_upload import verify_photo_token, get_signon, store_uploaded_photo

logger = logging.getLogger(__name__)

router = APIRouter()

# Jinja2 templates for public pages (separate from admin templates)
template_dir = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)

# Cookie signing
COOKIE_NAME = "journ3y_signon"
COOKIE_MAX_AGE = 365 * 24 * 3600  # 1 year


def _serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("SESSION_SECRET_KEY", "change-me-in-production")
    return URLSafeTimedSerializer(secret)


def _get_user_from_cookie(request: Request) -> Optional[dict]:
    """Decode the signed cookie. Returns {user_id, tenant_id} or None."""
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        data = _serializer().loads(raw, max_age=COOKIE_MAX_AGE)
        return data
    except (BadSignature, SignatureExpired):
        return None


def _set_user_cookie(response: Response, user_id: str, tenant_id: str):
    """Set a signed, long-lived cookie identifying the user."""
    value = _serializer().dumps({"user_id": user_id, "tenant_id": tenant_id})
    is_prod = os.getenv("ENVIRONMENT") == "production"
    response.set_cookie(
        key=COOKIE_NAME,
        value=value,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=is_prod,
    )


@router.get("/s/{short_code}", response_class=HTMLResponse)
async def signon_page(short_code: str, request: Request):
    """Main QR scan entry point. Shows identify or confirm page."""
    qr_data = await resolve_short_code(short_code)
    if not qr_data:
        template = _env.get_template("signon/not_found.html")
        return HTMLResponse(template.render(), status_code=404)

    if not qr_data.get("qr_enabled"):
        template = _env.get_template("signon/not_found.html")
        return HTMLResponse(template.render(), status_code=404)

    # Check cookie for returning user
    cookie_data = _get_user_from_cookie(request)
    if cookie_data and cookie_data.get("tenant_id") == qr_data["tenant_id"]:
        # Verify user still exists and is active
        from app.services.signon_service import identify_user_by_phone
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
                headers={
                    "apikey": os.getenv("SUPABASE_SERVICE_KEY", ""),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY', '')}",
                },
                params={
                    "id": f"eq.{cookie_data['user_id']}",
                    "is_active": "eq.true",
                    "select": "id,name,phone_number",
                },
            )
            if resp.status_code == 200 and resp.json():
                user = resp.json()[0]
                template = _env.get_template("signon/confirm.html")
                return HTMLResponse(template.render(
                    user_name=user["name"],
                    user_id=user["id"],
                    site_name=qr_data["site_name"],
                    site_address=qr_data.get("site_address", ""),
                    short_code=short_code,
                ))

    # No valid cookie - show phone entry page
    template = _env.get_template("signon/identify.html")
    return HTMLResponse(template.render(
        site_name=qr_data["site_name"],
        site_address=qr_data.get("site_address", ""),
        short_code=short_code,
        manager_phone=qr_data.get("manager_phone_number", ""),
    ))


@router.post("/s/{short_code}/identify")
async def identify_user(short_code: str, request: Request):
    """Accept phone number, find user, set cookie."""
    qr_data = await resolve_short_code(short_code)
    if not qr_data:
        return JSONResponse({"success": False, "error": "Invalid QR code"}, status_code=404)

    body = await request.json()
    phone = body.get("phone", "").strip()
    if not phone:
        return JSONResponse({"success": False, "error": "Phone number required"}, status_code=400)

    user = await identify_user_by_phone(phone, qr_data["tenant_id"])
    if not user:
        return JSONResponse({
            "success": False,
            "error": "not_registered",
            "manager_phone": qr_data.get("manager_phone_number", ""),
        }, status_code=404)

    # Set signed cookie and return user info
    response = JSONResponse({
        "success": True,
        "user_name": user["name"],
        "user_id": user["id"],
    })
    _set_user_cookie(response, user["id"], qr_data["tenant_id"])
    return response


@router.post("/s/{short_code}/signon")
async def do_signon(short_code: str, request: Request):
    """Record the sign-on event."""
    qr_data = await resolve_short_code(short_code)
    if not qr_data:
        return JSONResponse({"success": False, "error": "Invalid QR code"}, status_code=404)

    # Get user from cookie or request body
    cookie_data = _get_user_from_cookie(request)
    body = await request.json()
    user_id = body.get("user_id") or (cookie_data.get("user_id") if cookie_data else None)

    if not user_id:
        return JSONResponse({"success": False, "error": "User not identified"}, status_code=400)

    # Verify user belongs to this tenant
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/users",
            headers={
                "apikey": os.getenv("SUPABASE_SERVICE_KEY", ""),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY', '')}",
            },
            params={
                "id": f"eq.{user_id}",
                "tenant_id": f"eq.{qr_data['tenant_id']}",
                "is_active": "eq.true",
                "select": "id,name",
            },
        )
        if resp.status_code != 200 or not resp.json():
            return JSONResponse({"success": False, "error": "User not found"}, status_code=404)

    try:
        signon = await record_signon(
            user_id=user_id,
            site_id=qr_data["site_id"],
            tenant_id=qr_data["tenant_id"],
            short_code=short_code,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

        response = JSONResponse({
            "success": True,
            "signon_id": signon["id"],
            "post_signon_message": qr_data.get("post_signon_message"),
            "jill_phone_number": qr_data.get("jill_phone_number"),
        })
        # Ensure cookie is set/refreshed
        _set_user_cookie(response, user_id, qr_data["tenant_id"])
        return response

    except Exception as e:
        logger.error(f"Sign-on failed: {e}")
        return JSONResponse({"success": False, "error": "Sign-on failed"}, status_code=500)


# ============================================
# PHOTO UPLOAD (web link workaround for AU inbound MMS)
# ============================================

@router.get("/p/{token}", response_class=HTMLResponse)
async def photo_upload_page(token: str, request: Request):
    """Mobile page a worker opens from the SMS'd link to upload site photos."""
    import httpx
    from datetime import datetime
    signon_id = verify_photo_token(token)
    if not signon_id:
        return HTMLResponse(_env.get_template("photo/expired.html").render(), status_code=404)
    async with httpx.AsyncClient() as client:
        signon = await get_signon(client, signon_id)
    if not signon:
        return HTMLResponse(_env.get_template("photo/expired.html").render(), status_code=404)
    template = _env.get_template("photo/upload.html")
    return HTMLResponse(template.render(
        token=token,
        site_name=signon.get("site_name") or "your site",
        today=datetime.now().strftime("%a %d %b %Y"),
    ))


@router.post("/p/{token}/upload")
async def photo_upload_submit(token: str, files: list[UploadFile] = File(default=[]),
                              caption: str = Form(default=None)):
    """Receive uploaded photos, store them, anchor to the sign-on."""
    import httpx
    signon_id = verify_photo_token(token)
    if not signon_id:
        return JSONResponse({"success": False, "error": "This link has expired"}, status_code=400)
    async with httpx.AsyncClient(timeout=60.0) as client:
        signon = await get_signon(client, signon_id)
        if not signon:
            return JSONResponse({"success": False, "error": "Sign-on not found"}, status_code=400)
        count = 0
        for f in files:
            data = await f.read()
            ctype = f.content_type or "image/jpeg"
            if not data or not ctype.startswith("image/"):
                continue
            if len(data) > 15 * 1024 * 1024:  # 15 MB cap
                continue
            if await store_uploaded_photo(client, signon, data, ctype, caption=caption):
                count += 1
    return JSONResponse({"success": True, "count": count})
