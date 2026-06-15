"""Inbound Twilio SMS/MMS webhook (site updates feature).

This is the entry point for worker text/photo updates. Unlike the VAPI skill
endpoints, a Twilio webhook:
  - receives form-encoded data (not JSON),
  - returns TwiML / empty 200 (not the VAPI {"results": [...]} shape),
  - must validate the X-Twilio-Signature header itself (no Twilio SDK in repo).

Phase 1 SKELETON: receive -> validate -> resolve tenant/user -> gate on toggle ->
log to message_log -> 200. The business logic (site attribution, per-day
accumulation, finish-time capture, finalization, outbound replies) is marked
with TODO and lands in the next build chunk.

See docs/SMS_MMS_SITE_UPDATES_DESIGN.md.
"""

import os
import hmac
import base64
import hashlib
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.config import settings
from app.services.twilio_service import send_sms
from app.services.sms_site_updates import process_inbound

logger = logging.getLogger(__name__)

router = APIRouter()

# Empty TwiML — "received, no auto-reply". Replies are sent via the REST API
# (twilio_service.send_sms) in the next chunk so we control multi-turn timing.
_EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


def _twiml(body: str = _EMPTY_TWIML) -> Response:
    return Response(content=body, media_type="application/xml", status_code=200)


def _url() -> str:
    return os.getenv("SUPABASE_URL", "")


def _headers() -> dict:
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Twilio signature validation (HMAC-SHA1 of URL + sorted POST params)
# ---------------------------------------------------------------------------
def _expected_signature(url: str, params: dict, auth_token: str) -> str:
    """Twilio's scheme: concat the full URL with each sorted (key + value),
    HMAC-SHA1 with the auth token, base64."""
    data = url
    for key in sorted(params.keys()):
        data += key + (params[key] or "")
    digest = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _validate_signature(request: Request, form: dict) -> bool:
    """Validate X-Twilio-Signature.

    Twilio signs the EXACT public URL it was configured with. Behind a proxy
    (Railway / Cloudflare tunnel) request.url may differ, so we try a few
    candidate URLs and accept if any matches.

    Set TWILIO_SKIP_SIGNATURE_VALIDATION=true ONLY for local dev/testing.
    """
    if os.getenv("TWILIO_SKIP_SIGNATURE_VALIDATION", "").lower() == "true":
        logger.warning("Twilio signature validation SKIPPED (TWILIO_SKIP_SIGNATURE_VALIDATION=true)")
        return True

    auth_token = settings.TWILIO_AUTH_TOKEN or ""
    sig = request.headers.get("X-Twilio-Signature")
    if not auth_token or not sig:
        logger.error("Inbound SMS rejected: missing auth token or signature header")
        return False

    path = request.url.path
    base = settings.webhook_base_url.rstrip("/")
    candidates = [
        f"{base}{path}",          # configured public URL (expected)
        str(request.url).split("?")[0],  # raw url as seen by the app
    ]
    for candidate in candidates:
        if hmac.compare_digest(_expected_signature(candidate, form, auth_token), sig):
            return True

    logger.error("Inbound SMS rejected: signature mismatch (tried %s)", candidates)
    return False


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------
async def _resolve_tenant(client: httpx.AsyncClient, to_number: str) -> Optional[dict]:
    """Map the inbound `To` number -> tenant via qr_signon_config.twilio_from_number.
    Returns the config row (incl. tenant_id, inbound_messaging_enabled) or None."""
    resp = await client.get(
        f"{_url()}/rest/v1/qr_signon_config",
        headers=_headers(),
        params={
            "twilio_from_number": f"eq.{to_number}",
            "select": "tenant_id,inbound_messaging_enabled,manager_phone_number",
        },
    )
    rows = resp.json() if resp.status_code == 200 else []
    return rows[0] if rows else None


async def _resolve_user(client: httpx.AsyncClient, tenant_id: str, from_number: str) -> Optional[dict]:
    """Map the inbound `From` number -> active user within the tenant."""
    resp = await client.get(
        f"{_url()}/rest/v1/users",
        headers=_headers(),
        params={
            "tenant_id": f"eq.{tenant_id}",
            "phone_number": f"eq.{from_number}",
            "is_active": "eq.true",
            "select": "id,name,phone_number,tenant_id",
        },
    )
    rows = resp.json() if resp.status_code == 200 else []
    return rows[0] if rows else None


async def _already_processed(client: httpx.AsyncClient, message_sid: str) -> bool:
    """Idempotency: Twilio retries webhooks. Skip if we've logged this SID."""
    if not message_sid:
        return False
    resp = await client.get(
        f"{_url()}/rest/v1/message_log",
        headers=_headers(),
        params={"twilio_message_sid": f"eq.{message_sid}", "select": "id"},
    )
    return resp.status_code == 200 and bool(resp.json())


async def _log_inbound(client: httpx.AsyncClient, *, tenant_id: str, user_id: Optional[str],
                       from_number: str, to_number: str, body: str, num_media: int,
                       num_segments: Optional[int], message_sid: str) -> Optional[str]:
    """Insert the inbound row and return its id. site_id/signon_id/category are
    stamped later by the business logic."""
    channel = "mms" if num_media > 0 else "sms"
    resp = await client.post(
        f"{_url()}/rest/v1/message_log",
        headers={**_headers(), "Prefer": "return=representation"},
        json={
            "tenant_id": tenant_id,
            "user_id": user_id,
            "direction": "inbound",
            "channel": channel,
            "from_number": from_number,
            "to_number": to_number,
            "body": body,
            "num_media": num_media,
            "num_segments": num_segments,
            "twilio_message_sid": message_sid,
            "status": "received",
        },
    )
    if resp.status_code == 201 and resp.json():
        return resp.json()[0].get("id")
    return None


async def _log_outbound(client: httpx.AsyncClient, *, tenant_id: str, user_id: Optional[str],
                        from_number: str, to_number: str, body: str, message_sid: Optional[str]) -> None:
    """Record a reply we sent (metering + audit)."""
    await client.post(
        f"{_url()}/rest/v1/message_log",
        headers={**_headers(), "Prefer": "return=minimal"},
        json={
            "tenant_id": tenant_id, "user_id": user_id, "direction": "outbound",
            "channel": "sms", "from_number": from_number, "to_number": to_number,
            "body": body, "twilio_message_sid": message_sid, "status": "sent",
        },
    )


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------
@router.post("/api/v1/twilio/sms/inbound")
async def inbound_sms(request: Request):
    """Receive an inbound Twilio SMS/MMS. Always returns 200 (empty TwiML) so
    Twilio doesn't retry on our business errors."""
    form_data = await request.form()
    form = {k: str(v) for k, v in form_data.items()}

    # 1. Signature validation
    if not _validate_signature(request, form):
        # 403 so Twilio (and any spoofer) gets a clear rejection.
        return Response(status_code=403)

    from_number = form.get("From", "")
    to_number = form.get("To", "")
    body = form.get("Body", "") or ""
    message_sid = form.get("MessageSid", "") or form.get("SmsSid", "")
    num_media = int(form.get("NumMedia", "0") or 0)
    num_segments = int(form.get("NumSegments", "0") or 0) or None

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 2. Idempotency (Twilio retries)
        if await _already_processed(client, message_sid):
            logger.info("Duplicate inbound SMS %s ignored", message_sid)
            return _twiml()

        # 3. Resolve tenant from the To number
        tenant_cfg = await _resolve_tenant(client, to_number)
        if not tenant_cfg:
            logger.warning("Inbound SMS to unmapped number %s — ignored", to_number)
            return _twiml()
        tenant_id = tenant_cfg["tenant_id"]

        # 4. Toggle gate
        if not tenant_cfg.get("inbound_messaging_enabled"):
            logger.info("Inbound messaging disabled for tenant %s — ignored", tenant_id)
            return _twiml()

        # 5. Resolve user from the From number
        user = await _resolve_user(client, tenant_id, from_number)
        user_id = user["id"] if user else None

        # 6. Log inbound (always — metering + note source)
        message_log_id = await _log_inbound(
            client,
            tenant_id=tenant_id,
            user_id=user_id,
            from_number=from_number,
            to_number=to_number,
            body=body,
            num_media=num_media,
            num_segments=num_segments,
            message_sid=message_sid,
        )

        # 7. Business logic -> reply text
        # TODO(Phase 2): if num_media > 0, ingest media -> Supabase Storage -> timesheet_media.
        reply = await process_inbound(
            client, tenant_cfg=tenant_cfg, user=user,
            from_number=from_number, body=body, message_log_id=message_log_id,
        )

        # 8. Send the reply (from the tenant number) and log it
        if reply:
            result = await send_sms(to_number=from_number, message=reply, from_number=to_number)
            await _log_outbound(
                client, tenant_id=tenant_id, user_id=user_id,
                from_number=to_number, to_number=from_number, body=reply,
                message_sid=result.get("sid") if result.get("success") else None,
            )

    logger.info(
        "Inbound %s handled: tenant=%s user=%s media=%d replied=%s sid=%s",
        "MMS" if num_media else "SMS", tenant_id, user_id, num_media, bool(reply), message_sid,
    )
    return _twiml()
