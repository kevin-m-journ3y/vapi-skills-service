"""Business logic for QR sign-on operations."""

import os
import uuid
import httpx
import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}


def _headers():
    """Build Supabase headers (lazy, so env vars are read at call time)."""
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _url():
    return os.getenv("SUPABASE_URL", "")


async def resolve_short_code(short_code: str) -> Optional[dict]:
    """Look up a QR code by short_code. Returns site + tenant info or None."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_url()}/rest/v1/site_qr_codes",
            headers=_headers(),
            params={
                "short_code": f"eq.{short_code}",
                "is_active": "eq.true",
                "select": "id,tenant_id,site_id,short_code",
            },
        )
        if resp.status_code != 200 or not resp.json():
            return None

        qr = resp.json()[0]

        # Fetch site details
        site_resp = await client.get(
            f"{_url()}/rest/v1/entities",
            headers=_headers(),
            params={
                "id": f"eq.{qr['site_id']}",
                "select": "id,name,address,tenant_id",
            },
        )
        site = site_resp.json()[0] if site_resp.status_code == 200 and site_resp.json() else None

        # Fetch tenant details
        tenant_resp = await client.get(
            f"{_url()}/rest/v1/tenants",
            headers=_headers(),
            params={
                "id": f"eq.{qr['tenant_id']}",
                "select": "id,name,timezone",
            },
        )
        tenant = tenant_resp.json()[0] if tenant_resp.status_code == 200 and tenant_resp.json() else None

        # Fetch QR config for this tenant
        config_resp = await client.get(
            f"{_url()}/rest/v1/qr_signon_config",
            headers=_headers(),
            params={
                "tenant_id": f"eq.{qr['tenant_id']}",
                "is_enabled": "eq.true",
                "select": "post_signon_message,manager_phone_number,jill_phone_number",
            },
        )
        config = config_resp.json()[0] if config_resp.status_code == 200 and config_resp.json() else None

        if not site or not tenant:
            return None

        return {
            "qr_id": qr["id"],
            "short_code": qr["short_code"],
            "site_id": site["id"],
            "site_name": site["name"],
            "site_address": site.get("address"),
            "tenant_id": tenant["id"],
            "tenant_name": tenant["name"],
            "tenant_timezone": tenant.get("timezone") or "Australia/Sydney",
            "post_signon_message": config.get("post_signon_message") if config else None,
            "manager_phone_number": config.get("manager_phone_number") if config else None,
            "jill_phone_number": config.get("jill_phone_number") if config else None,
            "qr_enabled": config is not None,
        }


async def identify_user_by_phone(phone: str, tenant_id: str) -> Optional[dict]:
    """Find a user by phone number within a tenant."""
    # Normalize phone to E.164 (strip spaces, ensure +)
    phone_clean = phone.strip().replace(" ", "").replace("-", "")
    if not phone_clean.startswith("+"):
        # Assume Australian if starts with 0
        if phone_clean.startswith("0"):
            phone_clean = "+61" + phone_clean[1:]
        else:
            phone_clean = "+" + phone_clean

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_url()}/rest/v1/users",
            headers=_headers(),
            params={
                "tenant_id": f"eq.{tenant_id}",
                "phone_number": f"eq.{phone_clean}",
                "is_active": "eq.true",
                "select": "id,name,phone_number,email,tenant_id",
            },
        )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0]
        return None


async def record_signon(
    user_id: str,
    site_id: str,
    tenant_id: str,
    short_code: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict:
    """Record a sign-on. Closes any active sign-on for this user first."""
    async with httpx.AsyncClient() as client:
        # Close any active sign-ons for this user
        active_resp = await client.get(
            f"{_url()}/rest/v1/site_signons",
            headers=_headers(),
            params={
                "user_id": f"eq.{user_id}",
                "status": "eq.active",
                "select": "id",
            },
        )
        if active_resp.status_code == 200 and active_resp.json():
            for active in active_resp.json():
                await client.patch(
                    f"{_url()}/rest/v1/site_signons",
                    headers={**_headers(), "Prefer": "return=minimal"},
                    params={"id": f"eq.{active['id']}"},
                    json={
                        "status": "signed_off",
                        "signoff_method": "auto_next_site",
                        "signed_off_at": datetime.now(timezone.utc).isoformat(),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )

        # Create new sign-on
        signon_id = str(uuid.uuid4())
        signon_data = {
            "id": signon_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "site_id": site_id,
            "short_code": short_code,
            "status": "active",
            "ip_address": ip_address,
            "user_agent": user_agent,
        }

        resp = await client.post(
            f"{_url()}/rest/v1/site_signons",
            headers={**_headers(), "Prefer": "return=representation"},
            json=signon_data,
        )

        if resp.status_code == 201:
            return resp.json()[0]
        else:
            logger.error(f"Failed to create sign-on: {resp.status_code} {resp.text}")
            raise Exception(f"Failed to create sign-on: {resp.text}")


async def get_active_signons_for_user(user_id: str, tenant_timezone: str = "Australia/Sydney") -> list:
    """Get today's sign-on records for a user (for Jill integration)."""
    tz = ZoneInfo(tenant_timezone)
    now_local = datetime.now(tz)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_url()}/rest/v1/site_signons",
            headers=_headers(),
            params={
                "user_id": f"eq.{user_id}",
                "signed_on_at": f"gte.{today_start.isoformat()}",
                "select": "id,site_id,signed_on_at,signed_off_at,status,signoff_method",
                "order": "signed_on_at.asc",
            },
        )

        if resp.status_code != 200:
            return []

        signons = resp.json()

        if not signons:
            return []

        # Enrich with site names
        site_ids = list(set(s["site_id"] for s in signons))
        sites_resp = await client.get(
            f"{_url()}/rest/v1/entities",
            headers=_headers(),
            params={
                "id": f"in.({','.join(site_ids)})",
                "select": "id,name",
            },
        )
        site_map = {}
        if sites_resp.status_code == 200:
            site_map = {s["id"]: s["name"] for s in sites_resp.json()}

        for s in signons:
            s["site_name"] = site_map.get(s["site_id"], "Unknown site")
            # Format time for display
            if s.get("signed_on_at"):
                signed_on_dt = datetime.fromisoformat(s["signed_on_at"].replace("Z", "+00:00"))
                local_time = signed_on_dt.astimezone(tz)
                s["signed_on_time"] = local_time.strftime("%H:%M")
            else:
                s["signed_on_time"] = "Unknown"

        return signons


async def close_signon(signon_id: str, method: str, timesheet_id: Optional[str] = None):
    """Mark a sign-on as signed off."""
    update_data = {
        "status": "signed_off",
        "signoff_method": method,
        "signed_off_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if timesheet_id:
        update_data["timesheet_id"] = timesheet_id

    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{_url()}/rest/v1/site_signons",
            headers={**_headers(), "Prefer": "return=minimal"},
            params={"id": f"eq.{signon_id}"},
            json=update_data,
        )
        return resp.status_code in (200, 204)


async def close_signons_for_user_site(user_id: str, site_id: str, method: str, timesheet_id: Optional[str] = None):
    """Close active sign-ons for a user at a specific site (used by timesheet skill)."""
    async with httpx.AsyncClient() as client:
        # Find active sign-ons for this user+site
        resp = await client.get(
            f"{_url()}/rest/v1/site_signons",
            headers=_headers(),
            params={
                "user_id": f"eq.{user_id}",
                "site_id": f"eq.{site_id}",
                "status": "eq.active",
                "select": "id",
            },
        )
        if resp.status_code == 200 and resp.json():
            for signon in resp.json():
                await close_signon(signon["id"], method, timesheet_id)
