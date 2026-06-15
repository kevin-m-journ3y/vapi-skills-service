"""Web photo-upload links (workaround for Twilio's lack of inbound MMS in AU).

Workers receive a signed, short-lived link via SMS that opens a mobile page to
upload photos over HTTPS. Photos land in Supabase Storage + timesheet_media,
anchored to the worker's open sign-on — the same downstream as the (AU-blocked)
MMS pipeline. See docs/SMS_MMS_SITE_UPDATES_DESIGN.md.
"""

import os
import uuid
import logging

import httpx
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.config import settings

logger = logging.getLogger(__name__)

BUCKET = "mms-photos"
TOKEN_SALT = "photo-upload-v1"
TOKEN_MAX_AGE = 36 * 3600  # 36h — covers a long shift + a bit
_EXT = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/gif": "gif",
    "image/heic": "heic", "image/heif": "heif", "image/webp": "webp",
}


def _url() -> str:
    return os.getenv("SUPABASE_URL", "")


def _headers() -> dict:
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("SESSION_SECRET_KEY", "change-me-in-production")
    return URLSafeTimedSerializer(secret, salt=TOKEN_SALT)


def make_photo_token(signon_id: str) -> str:
    return _serializer().dumps({"signon_id": signon_id})


def verify_photo_token(token: str):
    """Return signon_id if the token is valid and unexpired, else None."""
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE)
        return data.get("signon_id")
    except (BadSignature, SignatureExpired):
        return None


def photo_link(signon_id: str) -> str:
    base = settings.webhook_base_url.rstrip("/")
    return f"{base}/p/{make_photo_token(signon_id)}"


async def get_signon(client: httpx.AsyncClient, signon_id: str):
    """Fetch sign-on (+ site name) for the upload page / storage anchoring."""
    resp = await client.get(
        f"{_url()}/rest/v1/site_signons", headers=_headers(),
        params={"id": f"eq.{signon_id}",
                "select": "id,tenant_id,user_id,site_id,status,signed_on_at,entities(name)"})
    rows = resp.json() if resp.status_code == 200 else []
    if not rows:
        return None
    s = rows[0]
    ent = s.get("entities") or {}
    s["site_name"] = ent.get("name") if isinstance(ent, dict) else None
    return s


async def store_uploaded_photo(client: httpx.AsyncClient, signon: dict, file_bytes: bytes,
                               content_type: str, caption=None) -> bool:
    """Upload a web-submitted photo to Storage + record in timesheet_media,
    anchored to the sign-on (backfilled to the timesheet on finalize)."""
    ext = _EXT.get((content_type or "").split(";")[0].strip().lower(), "bin")
    path = f"{signon['tenant_id']}/web_{uuid.uuid4()}.{ext}"
    up = await client.post(
        f"{_url()}/storage/v1/object/{BUCKET}/{path}",
        headers={**_headers(), "Content-Type": content_type or "image/jpeg", "x-upsert": "true"},
        content=file_bytes,
    )
    if up.status_code not in (200, 201):
        logger.error("Web photo upload failed: %s %s", up.status_code, up.text[:160])
        return False
    media_url = f"{_url()}/storage/v1/object/public/{BUCKET}/{path}"
    await client.post(
        f"{_url()}/rest/v1/timesheet_media",
        headers={**_headers(), "Content-Type": "application/json", "Prefer": "return=minimal"},
        json={"tenant_id": signon["tenant_id"], "user_id": signon.get("user_id"),
              "site_id": signon.get("site_id"), "signon_id": signon["id"],
              "media_url": media_url, "content_type": content_type,
              "caption": caption, "source": "web_upload"},
    )
    return True
