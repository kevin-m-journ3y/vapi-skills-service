"""Admin routes for QR sign-on management."""

import os
import uuid
import httpx
import logging
from datetime import datetime, date, timedelta
from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse

from app.services.qr_generator import generate_short_code, get_signon_url, generate_qr_image, generate_qr_pdf
from app.services.reminder_scheduler import reschedule_tenant

logger = logging.getLogger(__name__)

router = APIRouter()

# Reuse admin templates (same directory as main admin routes)
templates = Jinja2Templates(directory="app/admin/templates")


def _headers():
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _url():
    return os.getenv("SUPABASE_URL", "")


async def _get_session_user(request: Request) -> dict:
    user_session = request.session.get("user")
    if not user_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_session


# ============================================
# SITES CRUD
# ============================================

@router.get("/admin/sites", response_class=HTMLResponse)
async def sites_page(request: Request):
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    return templates.TemplateResponse("sites/list.html", {"request": request})


@router.post("/admin/sites")
async def create_site(request: Request):
    """Create a new site (entity with entity_type='sites')."""
    user_session = await _get_session_user(request)
    body = await request.json()
    name = body.get("name", "").strip()
    address = body.get("address", "").strip()
    tenant_id = body.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        tenant_id = user_session.get("tenant_id")

    if not name:
        return {"success": False, "error": "Site name is required"}
    if not tenant_id:
        return {"success": False, "error": "No tenant specified"}

    site_data = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "entity_type": "sites",
        "name": name,
        "address": address or None,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_url()}/rest/v1/entities",
            headers={**_headers(), "Prefer": "return=representation"},
            json=site_data,
        )

        if resp.status_code == 201:
            return {"success": True, "site": resp.json()[0]}
        else:
            return {"success": False, "error": resp.text}


@router.put("/admin/sites/{site_id}")
async def update_site(site_id: str, request: Request):
    """Update site name and address."""
    user_session = await _get_session_user(request)
    body = await request.json()
    name = body.get("name", "").strip()
    address = body.get("address", "").strip()

    if not name:
        return {"success": False, "error": "Site name is required"}

    # Verify access
    is_super_admin = user_session.get("role") == "super_admin"
    async with httpx.AsyncClient() as client:
        if not is_super_admin:
            check = await client.get(
                f"{_url()}/rest/v1/entities",
                headers=_headers(),
                params={"id": f"eq.{site_id}", "select": "tenant_id"},
            )
            if check.status_code != 200 or not check.json():
                return {"success": False, "error": "Site not found"}
            if check.json()[0]["tenant_id"] != user_session.get("tenant_id"):
                return {"success": False, "error": "Access denied"}

        resp = await client.patch(
            f"{_url()}/rest/v1/entities",
            headers={**_headers(), "Prefer": "return=minimal"},
            params={"id": f"eq.{site_id}"},
            json={"name": name, "address": address or None},
        )

        if resp.status_code in (200, 204):
            return {"success": True}
        else:
            return {"success": False, "error": resp.text}


@router.delete("/admin/sites/{site_id}")
async def delete_site(site_id: str, request: Request):
    """Delete a site. Will also delete its QR code if any."""
    user_session = await _get_session_user(request)
    is_super_admin = user_session.get("role") == "super_admin"

    async with httpx.AsyncClient() as client:
        # Verify access
        check = await client.get(
            f"{_url()}/rest/v1/entities",
            headers=_headers(),
            params={"id": f"eq.{site_id}", "select": "tenant_id,metadata"},
        )
        if check.status_code != 200 or not check.json():
            return {"success": False, "error": "Site not found"}

        site = check.json()[0]
        if not is_super_admin and site["tenant_id"] != user_session.get("tenant_id"):
            return {"success": False, "error": "Access denied"}

        # Don't allow deleting overhead sites
        if site.get("metadata") and site["metadata"].get("is_overhead"):
            return {"success": False, "error": "Cannot delete overhead sites"}

        # Delete associated QR code first
        await client.delete(
            f"{_url()}/rest/v1/site_qr_codes",
            headers=_headers(),
            params={"site_id": f"eq.{site_id}"},
        )

        # Delete the site
        resp = await client.delete(
            f"{_url()}/rest/v1/entities",
            headers=_headers(),
            params={"id": f"eq.{site_id}"},
        )

        if resp.status_code in (200, 204):
            return {"success": True}
        else:
            return {"success": False, "error": resp.text}


# ============================================
# QR SIGN-ON CONFIG
# ============================================

@router.get("/admin/qr-signons/config", response_class=HTMLResponse)
async def qr_config_page(request: Request):
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    return templates.TemplateResponse("qr/config.html", {"request": request})


@router.get("/admin/qr-signons/config/data")
async def get_qr_config(request: Request, tenant_id: str = None):
    user_session = await _get_session_user(request)
    is_super_admin = user_session.get("role") == "super_admin"

    # Determine tenant
    if not is_super_admin:
        tenant_id = user_session.get("tenant_id")
    elif not tenant_id:
        return {"success": False, "error": "Select a tenant"}

    if not tenant_id:
        return {"success": False, "error": "No tenant selected"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_url()}/rest/v1/qr_signon_config",
            headers=_headers(),
            params={"tenant_id": f"eq.{tenant_id}", "select": "*"},
        )

        config = resp.json()[0] if resp.status_code == 200 and resp.json() else None

        return {"success": True, "config": config, "tenant_id": tenant_id}


@router.post("/admin/qr-signons/config/update")
async def update_qr_config(request: Request):
    user_session = await _get_session_user(request)
    body = await request.json()
    tenant_id = body.get("tenant_id")
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        tenant_id = user_session.get("tenant_id")

    if not tenant_id:
        return {"success": False, "error": "No tenant specified"}

    config_data = {
        "is_enabled": body.get("is_enabled", False),
        "reminder_enabled": body.get("reminder_enabled", True),
        "first_reminder_time": body.get("first_reminder_time", "17:30"),
        "second_reminder_time": body.get("second_reminder_time", "19:00"),
        "jill_phone_number": body.get("jill_phone_number", ""),
        "manager_phone_number": body.get("manager_phone_number", ""),
        "post_signon_message": body.get("post_signon_message", ""),
        "twilio_from_number": body.get("twilio_from_number", ""),
        "updated_at": datetime.utcnow().isoformat(),
    }

    async with httpx.AsyncClient() as client:
        # Check if config exists
        check = await client.get(
            f"{_url()}/rest/v1/qr_signon_config",
            headers=_headers(),
            params={"tenant_id": f"eq.{tenant_id}", "select": "id"},
        )

        if check.status_code == 200 and check.json():
            # Update
            resp = await client.patch(
                f"{_url()}/rest/v1/qr_signon_config",
                headers={**_headers(), "Prefer": "return=minimal"},
                params={"tenant_id": f"eq.{tenant_id}"},
                json=config_data,
            )
        else:
            # Create
            config_data["id"] = str(uuid.uuid4())
            config_data["tenant_id"] = tenant_id
            resp = await client.post(
                f"{_url()}/rest/v1/qr_signon_config",
                headers={**_headers(), "Prefer": "return=minimal"},
                json=config_data,
            )

        if resp.status_code in (200, 201, 204):
            # Reschedule SMS reminder jobs for this tenant
            try:
                await reschedule_tenant(tenant_id)
            except Exception as e:
                logger.warning("Failed to reschedule reminders for tenant %s: %s", tenant_id, str(e))
            return {"success": True}
        else:
            return {"success": False, "error": resp.text}


# ============================================
# QR CODE GENERATION
# ============================================

@router.get("/admin/qr-signons/sites")
async def get_sites_with_qr(request: Request, tenant_id: str = None):
    """Get sites for a tenant with their QR code status."""
    user_session = await _get_session_user(request)
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        tenant_id = user_session.get("tenant_id")
    if not tenant_id:
        return {"success": True, "sites": []}

    async with httpx.AsyncClient() as client:
        # Get sites
        sites_resp = await client.get(
            f"{_url()}/rest/v1/entities",
            headers=_headers(),
            params={
                "tenant_id": f"eq.{tenant_id}",
                "entity_type": "eq.sites",
                "select": "id,name,address,metadata",
                "order": "name.asc",
            },
        )
        sites = sites_resp.json() if sites_resp.status_code == 200 else []

        # Get QR codes for this tenant
        qr_resp = await client.get(
            f"{_url()}/rest/v1/site_qr_codes",
            headers=_headers(),
            params={
                "tenant_id": f"eq.{tenant_id}",
                "select": "id,site_id,short_code,is_active",
            },
        )
        qr_codes = {qr["site_id"]: qr for qr in (qr_resp.json() if qr_resp.status_code == 200 else [])}

        # Enrich sites with QR info
        for site in sites:
            qr = qr_codes.get(site["id"])
            site["has_qr"] = qr is not None
            site["qr_short_code"] = qr["short_code"] if qr else None
            site["qr_active"] = qr["is_active"] if qr else False
            site["qr_url"] = get_signon_url(qr["short_code"]) if qr else None

        return {"success": True, "sites": sites}


@router.post("/admin/sites/{site_id}/qr/generate")
async def generate_site_qr(site_id: str, request: Request):
    """Generate a QR code for a site."""
    user_session = await _get_session_user(request)

    async with httpx.AsyncClient() as client:
        # Get site to find tenant_id
        site_resp = await client.get(
            f"{_url()}/rest/v1/entities",
            headers=_headers(),
            params={"id": f"eq.{site_id}", "select": "id,name,tenant_id"},
        )
        if site_resp.status_code != 200 or not site_resp.json():
            return {"success": False, "error": "Site not found"}

        site = site_resp.json()[0]
        tenant_id = site["tenant_id"]

        # Check if QR already exists
        existing = await client.get(
            f"{_url()}/rest/v1/site_qr_codes",
            headers=_headers(),
            params={"site_id": f"eq.{site_id}", "select": "id,short_code"},
        )
        if existing.status_code == 200 and existing.json():
            qr = existing.json()[0]
            return {
                "success": True,
                "short_code": qr["short_code"],
                "url": get_signon_url(qr["short_code"]),
                "already_existed": True,
            }

        # Generate new QR code
        short_code = generate_short_code()
        qr_data = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "site_id": site_id,
            "short_code": short_code,
            "is_active": True,
            "created_by": user_session.get("user_id"),
        }

        resp = await client.post(
            f"{_url()}/rest/v1/site_qr_codes",
            headers={**_headers(), "Prefer": "return=representation"},
            json=qr_data,
        )

        if resp.status_code == 201:
            return {
                "success": True,
                "short_code": short_code,
                "url": get_signon_url(short_code),
                "already_existed": False,
            }
        else:
            return {"success": False, "error": resp.text}


@router.get("/admin/sites/{site_id}/qr/image")
async def get_site_qr_image(site_id: str, request: Request):
    """Return QR code as PNG image."""
    await _get_session_user(request)

    async with httpx.AsyncClient() as client:
        qr_resp = await client.get(
            f"{_url()}/rest/v1/site_qr_codes",
            headers=_headers(),
            params={"site_id": f"eq.{site_id}", "select": "short_code"},
        )
        if qr_resp.status_code != 200 or not qr_resp.json():
            raise HTTPException(status_code=404, detail="No QR code for this site")

        short_code = qr_resp.json()[0]["short_code"]
        url = get_signon_url(short_code)
        png_bytes = generate_qr_image(url)

        return Response(content=png_bytes, media_type="image/png")


@router.get("/admin/sites/{site_id}/qr/pdf")
async def get_site_qr_pdf(site_id: str, request: Request):
    """Download QR code as printable A4 PDF."""
    await _get_session_user(request)

    async with httpx.AsyncClient() as client:
        # Get site info
        site_resp = await client.get(
            f"{_url()}/rest/v1/entities",
            headers=_headers(),
            params={"id": f"eq.{site_id}", "select": "id,name,address"},
        )
        if site_resp.status_code != 200 or not site_resp.json():
            raise HTTPException(status_code=404, detail="Site not found")

        site = site_resp.json()[0]

        # Get QR code
        qr_resp = await client.get(
            f"{_url()}/rest/v1/site_qr_codes",
            headers=_headers(),
            params={"site_id": f"eq.{site_id}", "select": "short_code"},
        )
        if qr_resp.status_code != 200 or not qr_resp.json():
            raise HTTPException(status_code=404, detail="No QR code for this site. Generate one first.")

        short_code = qr_resp.json()[0]["short_code"]
        url = get_signon_url(short_code)

        pdf_bytes = generate_qr_pdf(site["name"], site.get("address"), url)
        safe_name = site["name"].replace(" ", "_").replace("/", "-")

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}-qr-signon.pdf"'},
        )


# ============================================
# SIGN-ON REPORTING
# ============================================

@router.get("/admin/qr-signons", response_class=HTMLResponse)
async def signons_page(request: Request):
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    return templates.TemplateResponse("qr/signons.html", {"request": request})


@router.get("/admin/qr-signons/data")
async def get_signons_data(
    request: Request,
    tenant_id: str = None,
    site_id: str = None,
    user_id: str = None,
    date_from: str = None,
    date_to: str = None,
):
    user_session = await _get_session_user(request)
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        tenant_id = user_session.get("tenant_id")
    if not tenant_id:
        return {"success": True, "signons": [], "stats": {}}

    async with httpx.AsyncClient() as client:
        params = {
            "tenant_id": f"eq.{tenant_id}",
            "select": "id,user_id,site_id,signed_on_at,signed_off_at,status,signoff_method,short_code",
            "order": "signed_on_at.desc",
            "limit": "500",
        }

        if site_id:
            params["site_id"] = f"eq.{site_id}"
        if user_id:
            params["user_id"] = f"eq.{user_id}"
        if date_from:
            params["signed_on_at"] = f"gte.{date_from}T00:00:00"
        if date_to:
            # Append to existing filter with AND
            if "signed_on_at" in params:
                params["and"] = f"(signed_on_at.gte.{date_from}T00:00:00,signed_on_at.lte.{date_to}T23:59:59)"
                del params["signed_on_at"]
            else:
                params["signed_on_at"] = f"lte.{date_to}T23:59:59"

        resp = await client.get(
            f"{_url()}/rest/v1/site_signons",
            headers=_headers(),
            params=params,
        )
        signons = resp.json() if resp.status_code == 200 else []

        if not signons:
            return {"success": True, "signons": [], "stats": {"total": 0, "active": 0, "missing_signoff": 0}}

        # Enrich with user and site names
        user_ids = list(set(s["user_id"] for s in signons))
        site_ids = list(set(s["site_id"] for s in signons))

        users_resp = await client.get(
            f"{_url()}/rest/v1/users",
            headers=_headers(),
            params={"id": f"in.({','.join(user_ids)})", "select": "id,name"},
        )
        user_map = {u["id"]: u["name"] for u in (users_resp.json() if users_resp.status_code == 200 else [])}

        sites_resp = await client.get(
            f"{_url()}/rest/v1/entities",
            headers=_headers(),
            params={"id": f"in.({','.join(site_ids)})", "select": "id,name"},
        )
        site_map = {s["id"]: s["name"] for s in (sites_resp.json() if sites_resp.status_code == 200 else [])}

        for s in signons:
            s["user_name"] = user_map.get(s["user_id"], "Unknown")
            s["site_name"] = site_map.get(s["site_id"], "Unknown")

        # Stats
        stats = {
            "total": len(signons),
            "active": sum(1 for s in signons if s["status"] == "active"),
            "signed_off": sum(1 for s in signons if s["status"] == "signed_off"),
        }

        return {"success": True, "signons": signons, "stats": stats}


# ============================================
# USER ENROLLMENT
# ============================================

@router.get("/admin/qr-signons/enrollment", response_class=HTMLResponse)
async def enrollment_page(request: Request):
    user_session = request.session.get("user")
    if not user_session:
        return RedirectResponse(url="/admin/login", status_code=302)
    return templates.TemplateResponse("qr/enrollment.html", {"request": request})


@router.get("/admin/qr-signons/enrollment/data")
async def get_enrollment_data(request: Request, tenant_id: str = None):
    user_session = await _get_session_user(request)
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        tenant_id = user_session.get("tenant_id")
    if not tenant_id:
        return {"success": True, "users": []}

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_url()}/rest/v1/users",
            headers=_headers(),
            params={
                "tenant_id": f"eq.{tenant_id}",
                "is_active": "eq.true",
                "select": "id,name,phone_number,role,qr_signon_enrolled",
                "order": "name.asc",
            },
        )
        users = resp.json() if resp.status_code == 200 else []
        return {"success": True, "users": users}


@router.post("/admin/users/{user_id}/qr-enrollment/toggle")
async def toggle_enrollment(user_id: str, request: Request):
    user_session = await _get_session_user(request)

    async with httpx.AsyncClient() as client:
        # Get current state
        user_resp = await client.get(
            f"{_url()}/rest/v1/users",
            headers=_headers(),
            params={"id": f"eq.{user_id}", "select": "id,qr_signon_enrolled,tenant_id"},
        )
        if user_resp.status_code != 200 or not user_resp.json():
            return {"success": False, "error": "User not found"}

        user = user_resp.json()[0]
        new_status = not user.get("qr_signon_enrolled", False)

        # Verify tenant access
        is_super_admin = user_session.get("role") == "super_admin"
        if not is_super_admin and user["tenant_id"] != user_session.get("tenant_id"):
            return {"success": False, "error": "Access denied"}

        resp = await client.patch(
            f"{_url()}/rest/v1/users",
            headers={**_headers(), "Prefer": "return=minimal"},
            params={"id": f"eq.{user_id}"},
            json={"qr_signon_enrolled": new_status},
        )

        if resp.status_code in (200, 204):
            return {"success": True, "enrolled": new_status}
        else:
            return {"success": False, "error": resp.text}
