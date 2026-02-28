"""Admin routes for QR sign-on management."""

import os
import uuid
import httpx
import logging
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Request, HTTPException
from app.auth_utils import hash_password, validate_password_strength
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
        elif resp.status_code == 409 or "violates foreign key constraint" in resp.text:
            return {"success": False, "error": "This site has existing data (timesheets, sign-ons, or updates) and cannot be deleted."}
        else:
            logger.error("Failed to delete site %s: %s", site_id, resp.text)
            return {"success": False, "error": "Failed to delete site"}


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
        "updated_at": datetime.now(timezone.utc).isoformat(),
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

        # Check QR sign-on is enabled for this tenant
        config_resp = await client.get(
            f"{_url()}/rest/v1/qr_signon_config",
            headers=_headers(),
            params={"tenant_id": f"eq.{tenant_id}", "select": "is_enabled"},
        )
        if config_resp.status_code != 200 or not config_resp.json() or not config_resp.json()[0].get("is_enabled"):
            return {"success": False, "error": "QR Sign-On is not enabled for this company. Enable it in Settings first."}

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
    status: str = None,
):
    user_session = await _get_session_user(request)
    is_super_admin = user_session.get("role") == "super_admin"

    if not is_super_admin:
        tenant_id = user_session.get("tenant_id")
    if not tenant_id:
        return {"success": True, "signons": [], "stats": {}}

    async with httpx.AsyncClient() as client:
        # Get tenant timezone for date filtering
        tz_str = "Australia/Sydney"  # default
        tz_resp = await client.get(
            f"{_url()}/rest/v1/tenants",
            headers=_headers(),
            params={"id": f"eq.{tenant_id}", "select": "timezone"},
        )
        if tz_resp.status_code == 200 and tz_resp.json():
            tz_str = tz_resp.json()[0].get("timezone") or tz_str
        if tz_str == "Australia/Sydney":
            logger.warning(f"No timezone for tenant {tenant_id}, defaulting to Australia/Sydney")

        try:
            tz = ZoneInfo(tz_str)
        except Exception:
            tz = ZoneInfo("Australia/Sydney")

        params = {
            "tenant_id": f"eq.{tenant_id}",
            "select": "id,user_id,site_id,signed_on_at,signed_off_at,status,signoff_method,short_code,timesheet_id",
            "order": "signed_on_at.desc",
            "limit": "500",
        }

        if site_id:
            params["site_id"] = f"eq.{site_id}"
        if user_id:
            params["user_id"] = f"eq.{user_id}"
        if status and status != "all":
            params["status"] = f"eq.{status}"

        # Build timezone-aware date filters (ZoneInfo handles DST correctly with .replace)
        if date_from and date_to:
            from_dt = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=tz)
            to_dt = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=tz)
            params["and"] = f"(signed_on_at.gte.{from_dt.isoformat()},signed_on_at.lte.{to_dt.isoformat()})"
        elif date_from:
            from_dt = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=tz)
            params["signed_on_at"] = f"gte.{from_dt.isoformat()}"
        elif date_to:
            to_dt = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=tz)
            params["signed_on_at"] = f"lte.{to_dt.isoformat()}"

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

        # Enrich with linked timesheet data (start_time, end_time, hours_worked)
        timesheet_ids = [s["timesheet_id"] for s in signons if s.get("timesheet_id")]
        ts_map = {}
        if timesheet_ids:
            ts_resp = await client.get(
                f"{_url()}/rest/v1/timesheets",
                headers=_headers(),
                params={
                    "id": f"in.({','.join(timesheet_ids)})",
                    "select": "id,start_time,end_time,hours_worked,work_description,call_transcript",
                },
            )
            if ts_resp.status_code == 200:
                ts_map = {t["id"]: t for t in ts_resp.json()}

        for s in signons:
            s["user_name"] = user_map.get(s["user_id"], "Unknown")
            s["site_name"] = site_map.get(s["site_id"], "Unknown")
            ts = ts_map.get(s.get("timesheet_id"))
            if ts:
                s["start_time"] = ts.get("start_time")
                s["end_time"] = ts.get("end_time")
                s["hours_worked"] = ts.get("hours_worked")
                s["call_transcript"] = ts.get("call_transcript")
            else:
                s["start_time"] = None
                s["end_time"] = None
                s["hours_worked"] = None
                s["call_transcript"] = None

        # Stats
        stats = {
            "total": len(signons),
            "active": sum(1 for s in signons if s["status"] == "active"),
            "signed_off": sum(1 for s in signons if s["status"] == "signed_off"),
        }

        return {"success": True, "signons": signons, "stats": stats}


@router.post("/admin/qr-signons/{signon_id}/update")
async def update_signon(signon_id: str, request: Request):
    """Update sign-on or sign-off time for a record."""
    user_session = await _get_session_user(request)
    is_super_admin = user_session.get("role") == "super_admin"
    body = await request.json()

    async with httpx.AsyncClient() as client:
        # Verify access - fetch the record
        check = await client.get(
            f"{_url()}/rest/v1/site_signons",
            headers=_headers(),
            params={"id": f"eq.{signon_id}", "select": "id,tenant_id"},
        )
        if check.status_code != 200 or not check.json():
            return {"success": False, "error": "Sign-on record not found"}

        record = check.json()[0]
        if not is_super_admin and record["tenant_id"] != user_session.get("tenant_id"):
            return {"success": False, "error": "Access denied"}

        # Build update payload - only allow specific fields
        update_data = {}
        if "signed_on_at" in body and body["signed_on_at"]:
            update_data["signed_on_at"] = body["signed_on_at"]
        if "signed_off_at" in body:
            update_data["signed_off_at"] = body["signed_off_at"] or None
            # If setting a sign-off time, mark as signed_off
            if body["signed_off_at"]:
                update_data["status"] = "signed_off"
                if not body.get("signoff_method"):
                    update_data["signoff_method"] = "manual"

        if not update_data:
            return {"success": False, "error": "No changes provided"}

        resp = await client.patch(
            f"{_url()}/rest/v1/site_signons",
            headers={**_headers(), "Prefer": "return=representation"},
            params={"id": f"eq.{signon_id}"},
            json=update_data,
        )

        if resp.status_code in (200, 204):
            updated = resp.json()[0] if resp.json() else {}
            return {"success": True, "signon": updated}
        else:
            logger.error("Failed to update signon %s: %s", signon_id, resp.text)
            return {"success": False, "error": "Failed to update"}


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
                "select": "id,name,phone_number,role,sms_reminders_enabled",
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
            params={"id": f"eq.{user_id}", "select": "id,sms_reminders_enabled,tenant_id"},
        )
        if user_resp.status_code != 200 or not user_resp.json():
            return {"success": False, "error": "User not found"}

        user = user_resp.json()[0]
        new_status = not user.get("sms_reminders_enabled", False)

        # Verify tenant access
        is_super_admin = user_session.get("role") == "super_admin"
        if not is_super_admin and user["tenant_id"] != user_session.get("tenant_id"):
            return {"success": False, "error": "Access denied"}

        resp = await client.patch(
            f"{_url()}/rest/v1/users",
            headers={**_headers(), "Prefer": "return=minimal"},
            params={"id": f"eq.{user_id}"},
            json={"sms_reminders_enabled": new_status},
        )

        if resp.status_code in (200, 204):
            return {"success": True, "enrolled": new_status}
        else:
            return {"success": False, "error": resp.text}


# ============================================
# TENANT ADMIN MANAGEMENT
# ============================================

@router.get("/admin/tenants/{tenant_id}/admins")
async def get_tenant_admins(tenant_id: str, request: Request):
    """Get all admin users for a tenant."""
    user_session = await _get_session_user(request)
    is_super_admin = user_session.get("role") == "super_admin"

    # Tenant admins can view but only for their own tenant
    if not is_super_admin and tenant_id != user_session.get("tenant_id"):
        return {"success": False, "error": "Access denied"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_url()}/rest/v1/admin_users",
            headers=_headers(),
            params={
                "tenant_id": f"eq.{tenant_id}",
                "select": "id,username,email,role,is_active,last_login_at,created_at",
                "order": "created_at.asc",
            },
        )
        admins = resp.json() if resp.status_code == 200 else []

        # Get permissions for each admin
        for admin in admins:
            perm_resp = await client.get(
                f"{_url()}/rest/v1/admin_user_permissions",
                headers=_headers(),
                params={
                    "admin_user_id": f"eq.{admin['id']}",
                    "select": "permission_type",
                },
            )
            admin["permissions"] = [p["permission_type"] for p in (perm_resp.json() if perm_resp.status_code == 200 else [])]

        return {"success": True, "admins": admins}


@router.post("/admin/tenants/{tenant_id}/admins")
async def create_tenant_admin(tenant_id: str, request: Request):
    """Create a new tenant admin user. Super admin only."""
    user_session = await _get_session_user(request)
    if user_session.get("role") != "super_admin":
        return {"success": False, "error": "Super admin access required"}

    body = await request.json()
    username = body.get("username", "").strip()
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")

    if not username or not email or not password:
        return {"success": False, "error": "Username, email, and password are required"}

    # Validate password strength
    validation = validate_password_strength(password)
    if not validation["valid"]:
        return {"success": False, "error": "Password does not meet requirements", "requirements": validation["requirements"]}

    async with httpx.AsyncClient() as client:
        # Check for duplicate username or email
        dup_check = await client.get(
            f"{_url()}/rest/v1/admin_users",
            headers=_headers(),
            params={
                "or": f"(username.ilike.{username},email.ilike.{email})",
                "select": "id,username,email",
            },
        )
        if dup_check.status_code == 200 and dup_check.json():
            existing = dup_check.json()[0]
            if existing["username"].lower() == username.lower():
                return {"success": False, "error": "Username already exists"}
            if existing["email"].lower() == email:
                return {"success": False, "error": "Email already exists"}

        # Create the admin user
        admin_data = {
            "id": str(uuid.uuid4()),
            "username": username,
            "email": email,
            "password_hash": hash_password(password),
            "role": "tenant_admin",
            "tenant_id": tenant_id,
            "is_active": True,
        }

        resp = await client.post(
            f"{_url()}/rest/v1/admin_users",
            headers={**_headers(), "Prefer": "return=representation"},
            json=admin_data,
        )

        if resp.status_code == 201:
            created = resp.json()[0]
            # Set default permissions
            default_perms = ["view_timesheets", "view_voice_notes", "view_reports"]
            for perm in default_perms:
                await client.post(
                    f"{_url()}/rest/v1/admin_user_permissions",
                    headers={**_headers(), "Prefer": "return=minimal"},
                    json={
                        "id": str(uuid.uuid4()),
                        "admin_user_id": created["id"],
                        "permission_type": perm,
                    },
                )

            logger.info("Created tenant admin %s for tenant %s", username, tenant_id)
            return {
                "success": True,
                "admin": {
                    "id": created["id"],
                    "username": created["username"],
                    "email": created["email"],
                    "role": created["role"],
                    "is_active": created["is_active"],
                    "created_at": created.get("created_at"),
                    "permissions": default_perms,
                },
            }
        else:
            logger.error("Failed to create admin: %s", resp.text)
            return {"success": False, "error": "Failed to create admin user"}


@router.post("/admin/tenants/{tenant_id}/admins/{admin_id}/toggle")
async def toggle_tenant_admin(tenant_id: str, admin_id: str, request: Request):
    """Toggle a tenant admin's active status. Super admin only."""
    user_session = await _get_session_user(request)
    if user_session.get("role") != "super_admin":
        return {"success": False, "error": "Super admin access required"}

    async with httpx.AsyncClient() as client:
        # Verify admin belongs to this tenant
        check = await client.get(
            f"{_url()}/rest/v1/admin_users",
            headers=_headers(),
            params={"id": f"eq.{admin_id}", "tenant_id": f"eq.{tenant_id}", "select": "id,is_active,username"},
        )
        if check.status_code != 200 or not check.json():
            return {"success": False, "error": "Admin user not found"}

        admin = check.json()[0]
        new_status = not admin["is_active"]

        resp = await client.patch(
            f"{_url()}/rest/v1/admin_users",
            headers={**_headers(), "Prefer": "return=minimal"},
            params={"id": f"eq.{admin_id}"},
            json={"is_active": new_status},
        )

        if resp.status_code in (200, 204):
            logger.info("Toggled admin %s active=%s", admin["username"], new_status)
            return {"success": True, "is_active": new_status}
        else:
            return {"success": False, "error": "Failed to update"}


@router.post("/admin/tenants/{tenant_id}/admins/{admin_id}/reset-password")
async def reset_admin_password(tenant_id: str, admin_id: str, request: Request):
    """Reset a tenant admin's password. Super admin only."""
    user_session = await _get_session_user(request)
    if user_session.get("role") != "super_admin":
        return {"success": False, "error": "Super admin access required"}

    body = await request.json()
    new_password = body.get("password", "")

    if not new_password:
        return {"success": False, "error": "Password is required"}

    validation = validate_password_strength(new_password)
    if not validation["valid"]:
        return {"success": False, "error": "Password does not meet requirements"}

    async with httpx.AsyncClient() as client:
        # Verify admin belongs to this tenant
        check = await client.get(
            f"{_url()}/rest/v1/admin_users",
            headers=_headers(),
            params={"id": f"eq.{admin_id}", "tenant_id": f"eq.{tenant_id}", "select": "id,username"},
        )
        if check.status_code != 200 or not check.json():
            return {"success": False, "error": "Admin user not found"}

        resp = await client.patch(
            f"{_url()}/rest/v1/admin_users",
            headers={**_headers(), "Prefer": "return=minimal"},
            params={"id": f"eq.{admin_id}"},
            json={"password_hash": hash_password(new_password)},
        )

        if resp.status_code in (200, 204):
            logger.info("Reset password for admin %s", check.json()[0]["username"])
            return {"success": True}
        else:
            return {"success": False, "error": "Failed to reset password"}
