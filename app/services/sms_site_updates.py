"""Business logic for inbound SMS site updates (Phase 1, text).

Called by the thin webhook in twilio_inbound.py. Given a parsed inbound message
(+ resolved tenant/user), this:
  - routes keywords (HELP / STOP / START),
  - replies to unregistered numbers with the manager number,
  - attributes the message to a site via the open sign-on (sign-on first),
  - accumulates notes across the day (stamped onto message_log),
  - captures a finish time and FINALIZES the timesheet (signoff_method='sms_timesheet'),
  - manages short-lived multi-turn state (sms_pending_context).

Returns the reply text to send back (or None for silent). Deterministic parsing
is used for finish time / intent (no LLM) so it's testable; the readback in the
confirmation ("reply WRONG to fix") is the safety net.

NOT in this chunk: MMS media pipeline, AI free-text site matching, the
"no sign-on -> ask which site and record anyway" path (we nudge to scan in).
See docs/SMS_MMS_SITE_UPDATES_DESIGN.md.
"""

import os
import re
import uuid
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import httpx

from app.services.photo_upload import photo_link

logger = logging.getLogger(__name__)

PENDING_TTL_MINUTES = 45
_DONE_WORDS = [
    "done", "finished", "finish", "knock off", "knocked off", "all done",
    "that's it", "thats it", "clocking off", "clock off", "signing off",
    "sign off", "heading home", "home time", "wrapping up", "wrap up", "all good",
]
_STOP_WORDS = {"stop", "unsubscribe", "cancel", "stopall", "quit", "end"}
_START_WORDS = {"start", "subscribe", "unstop", "yes"}
_HELP_WORDS = {"help", "info", "?"}

MEDIA_BUCKET = "mms-photos"
_MEDIA_EXT = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/gif": "gif",
    "image/heic": "heic", "image/heif": "heif", "image/webp": "webp",
}


_PHOTO_WORDS = {"photo", "photos", "pic", "pics", "picture", "pictures", "image", "images"}


def _is_photo_keyword(body: str) -> bool:
    return (body or "").strip().lower() in _PHOTO_WORDS


def _photos_label(n: int) -> str:
    return "photo" if n == 1 else f"{n} photos"


def _url() -> str:
    return os.getenv("SUPABASE_URL", "")


def _headers() -> dict:
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Parsing helpers (deterministic)
# ---------------------------------------------------------------------------
def _classify_keyword(body: str) -> Optional[str]:
    t = (body or "").strip().lower()
    if t in _STOP_WORDS:
        return "stop"
    if t in _START_WORDS:
        return "start"
    if t in _HELP_WORDS:
        return "help"
    return None


def _is_done_signal(body: str) -> bool:
    t = (body or "").lower()
    return any(w in t for w in _DONE_WORDS)


def _parse_finish_time(body: str) -> Optional[str]:
    """Extract a finish time -> 'HH:MM' (24h), or None.

    Handles '3:30pm', '3.30 pm', '3pm', '15:30', '1530', 'at 3'.
    No am/pm + hour 1-7 -> assume PM (afternoon knock-off). Ambiguous results are
    read back to the worker in the confirmation so they can correct.
    """
    t = (body or "").lower()

    m = re.search(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm)?\b", t)
    if m:
        h, mn, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", t)
        if m:
            h, mn, ap = int(m.group(1)), 0, m.group(2)
        else:
            m = re.search(r"\b(\d{2})(\d{2})\b", t)  # 1530
            if m:
                h, mn, ap = int(m.group(1)), int(m.group(2)), None
            else:
                m = re.search(r"\bat\s+(\d{1,2})\b", t)  # "at 3"
                if m:
                    h, mn, ap = int(m.group(1)), 0, None
                else:
                    return None

    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    elif ap is None and 1 <= h <= 7:
        h += 12  # assume afternoon finish

    if not (0 <= h <= 23 and 0 <= mn <= 59):
        return None
    return f"{h:02d}:{mn:02d}"


def _fmt_12h(hhmm: str) -> str:
    h, mn = int(hhmm[:2]), int(hhmm[3:5])
    ap = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{mn:02d}{ap}" if mn else f"{h12}{ap}"


def _parse_ts(s: str) -> datetime:
    """Robustly parse a Postgres timestamptz string. Python 3.9's fromisoformat
    rejects 1/2/4/5-digit fractional seconds and short +00 offsets, which would
    otherwise throw mid-finalize and lose a real worker's timesheet."""
    s = (s or "").strip().replace(" ", "T").replace("Z", "+00:00")
    m = re.search(r"([+-]\d{2}):?(\d{2})?$", s)
    if m:
        base, tzs = s[:m.start()], f"{m.group(1)}:{m.group(2) or '00'}"
    else:
        base, tzs = s, "+00:00"
    if "." in base:
        head, frac = base.split(".", 1)
        base = f"{head}.{(frac + '000000')[:6]}"
    return datetime.fromisoformat(f"{base}{tzs}")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
async def _get_tenant_tz(client, tenant_id: str) -> ZoneInfo:
    resp = await client.get(f"{_url()}/rest/v1/tenants", headers=_headers(),
                            params={"id": f"eq.{tenant_id}", "select": "timezone"})
    rows = resp.json() if resp.status_code == 200 else []
    tz = (rows[0].get("timezone") if rows else None) or "Australia/Sydney"
    try:
        return ZoneInfo(tz)
    except Exception:
        return ZoneInfo("Australia/Sydney")


async def _active_signons(client, user_id: str) -> list:
    """Active sign-ons for the user, enriched with site name."""
    resp = await client.get(f"{_url()}/rest/v1/site_signons", headers=_headers(), params={
        "user_id": f"eq.{user_id}", "status": "eq.active",
        "select": "id,site_id,signed_on_at,entities(name)",
        "order": "signed_on_at.desc",
    })
    rows = resp.json() if resp.status_code == 200 else []
    for r in rows:
        ent = r.get("entities") or {}
        r["site_name"] = ent.get("name") if isinstance(ent, dict) else None
    return rows


async def _stamp_message(client, message_log_id: Optional[str], *, site_id=None,
                         signon_id=None, category=None) -> None:
    if not message_log_id:
        return
    patch = {}
    if site_id is not None:
        patch["site_id"] = site_id
    if signon_id is not None:
        patch["signon_id"] = signon_id
    if category is not None:
        patch["category"] = category
    if patch:
        await client.patch(f"{_url()}/rest/v1/message_log",
                           headers={**_headers(), "Prefer": "return=minimal"},
                           params={"id": f"eq.{message_log_id}"}, json=patch)


async def _gather_notes(client, signon_id: str) -> list:
    resp = await client.get(f"{_url()}/rest/v1/message_log", headers=_headers(), params={
        "signon_id": f"eq.{signon_id}", "direction": "eq.inbound",
        "category": "in.(note,finish)", "select": "body", "order": "created_at.asc",
    })
    rows = resp.json() if resp.status_code == 200 else []
    return [r["body"] for r in rows if (r.get("body") or "").strip()]


async def _set_reminders_enabled(client, user_id: str, enabled: bool) -> None:
    await client.patch(f"{_url()}/rest/v1/users",
                       headers={**_headers(), "Prefer": "return=minimal"},
                       params={"id": f"eq.{user_id}"}, json={"sms_reminders_enabled": enabled})


# ---- pending context (multi-turn state) ----
async def _get_pending(client, tenant_id: str, from_number: str) -> Optional[dict]:
    now = datetime.now(timezone.utc).isoformat()
    resp = await client.get(f"{_url()}/rest/v1/sms_pending_context", headers=_headers(), params={
        "tenant_id": f"eq.{tenant_id}", "from_number": f"eq.{from_number}",
        "expires_at": f"gt.{now}", "select": "state,payload",
    })
    rows = resp.json() if resp.status_code == 200 else []
    return rows[0] if rows else None


async def _set_pending(client, tenant_id, from_number, user_id, state, payload) -> None:
    expires = (datetime.now(timezone.utc) + timedelta(minutes=PENDING_TTL_MINUTES)).isoformat()
    await client.post(
        f"{_url()}/rest/v1/sms_pending_context",
        headers={**_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"},
        params={"on_conflict": "tenant_id,from_number"},
        json={"tenant_id": tenant_id, "from_number": from_number, "user_id": user_id,
              "state": state, "payload": payload, "expires_at": expires,
              "updated_at": datetime.now(timezone.utc).isoformat()},
    )


async def _clear_pending(client, tenant_id, from_number) -> None:
    await client.delete(f"{_url()}/rest/v1/sms_pending_context",
                        headers={**_headers(), "Prefer": "return=minimal"},
                        params={"tenant_id": f"eq.{tenant_id}", "from_number": f"eq.{from_number}"})


# ---------------------------------------------------------------------------
# MMS media ingest: Twilio media -> Supabase Storage -> timesheet_media
# ---------------------------------------------------------------------------
async def _download_twilio_media(url, fallback_ctype):
    """Download a Twilio media URL (auth + follow redirect to the CDN).
    Returns (bytes, content_type, media_sid)."""
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    tok = os.getenv("TWILIO_AUTH_TOKEN", "")
    media_sid = url.rstrip("/").split("/")[-1]
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as c:
        r = await c.get(url, auth=(sid, tok))
        if r.status_code != 200:
            raise RuntimeError(f"download status {r.status_code}")
        ctype = r.headers.get("Content-Type") or fallback_ctype or "application/octet-stream"
        return r.content, ctype, media_sid


async def _upload_media(client, path, data, content_type) -> bool:
    r = await client.post(
        f"{_url()}/storage/v1/object/{MEDIA_BUCKET}/{path}",
        headers={**_headers(), "Content-Type": content_type or "image/jpeg", "x-upsert": "true"},
        content=data,
    )
    if r.status_code not in (200, 201):
        logger.error("MMS storage upload failed: %s %s", r.status_code, r.text[:160])
        return False
    return True


async def _ingest_media(client, media, *, tenant_id, user_id, signon, caption) -> int:
    """Store each MMS photo, anchored to the sign-on. Returns count stored."""
    count = 0
    for m in (media or []):
        url = m.get("url")
        if not url:
            continue
        try:
            data, ctype, media_sid = await _download_twilio_media(url, m.get("content_type"))
        except Exception as e:
            logger.error("MMS download failed (%s): %s", url, e)
            continue
        if not data:
            continue
        ext = _MEDIA_EXT.get((ctype or "").split(";")[0].strip().lower(), "bin")
        path = f"{tenant_id}/{media_sid or str(uuid.uuid4())}.{ext}"
        if not await _upload_media(client, path, data, ctype):
            continue
        media_url = f"{_url()}/storage/v1/object/public/{MEDIA_BUCKET}/{path}"
        await client.post(
            f"{_url()}/rest/v1/timesheet_media",
            headers={**_headers(), "Prefer": "return=minimal,resolution=ignore-duplicates"},
            params={"on_conflict": "twilio_media_sid"},
            json={"tenant_id": tenant_id, "user_id": user_id, "site_id": signon.get("site_id"),
                  "signon_id": signon.get("id"), "media_url": media_url, "content_type": ctype,
                  "caption": (caption or None), "source": "sms_mms", "twilio_media_sid": media_sid},
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# Finalization
# ---------------------------------------------------------------------------
async def _finalize(client, *, tenant_id, user_id, signon, finish_hhmm, tz) -> str:
    """Create the day's timesheet from accumulated notes + sign-on start + finish
    time, close the sign-on, return the confirmation reply."""
    start_dt = _parse_ts(signon["signed_on_at"]).astimezone(tz)
    work_date = start_dt.date().isoformat()
    start_hhmm = start_dt.strftime("%H:%M")

    fh, fm = int(finish_hhmm[:2]), int(finish_hhmm[3:5])
    end_dt = start_dt.replace(hour=fh, minute=fm, second=0, microsecond=0)
    hours = round((end_dt - start_dt).total_seconds() / 3600.0, 2)
    incomplete = hours <= 0  # finish before start -> flag, don't guess

    notes = await _gather_notes(client, signon["id"])
    work_description = " | ".join(notes) if notes else "(logged via SMS, no description)"

    ts_id = str(uuid.uuid4())
    await client.post(f"{_url()}/rest/v1/timesheets",
                      headers={**_headers(), "Prefer": "return=minimal"},
                      json={
                          "id": ts_id, "tenant_id": tenant_id, "user_id": user_id,
                          "site_id": signon["site_id"], "vapi_call_id": None,
                          "work_date": work_date, "start_time": start_hhmm,
                          "end_time": None if incomplete else f"{fh:02d}:{fm:02d}",
                          "hours_worked": None if incomplete else hours,
                          "work_description": work_description,
                      })

    await client.patch(f"{_url()}/rest/v1/site_signons",
                       headers={**_headers(), "Prefer": "return=minimal"},
                       params={"id": f"eq.{signon['id']}"},
                       json={"status": "signed_off", "signoff_method": "sms_timesheet",
                             "signed_off_at": datetime.now(timezone.utc).isoformat(),
                             "timesheet_id": ts_id})

    # Backfill any photos for this sign-on to the new timesheet
    await client.patch(f"{_url()}/rest/v1/timesheet_media",
                       headers={**_headers(), "Prefer": "return=minimal"},
                       params={"signon_id": f"eq.{signon['id']}", "timesheet_id": "is.null"},
                       json={"timesheet_id": ts_id})

    site = signon.get("site_name") or "your site"
    if incomplete:
        return {"reply": (f"Saved to {site} ✅ — but the finish time looked off, so I've left "
                          f"hours for your manager to confirm. Reply with your finish time to fix."),
                "ts_id": ts_id, "needs_detail": False}
    if not notes:
        # No substantive detail was captured today — save the hours, then ask for
        # a one-line description so the client has usable data (not just a time).
        return {"reply": (f"Logged {hours:g}h at {site} ✅. Quick one — what did you focus on "
                          f"today? A line is plenty (e.g. \"poured slab, formwork for stage 2\")."),
                "ts_id": ts_id, "needs_detail": True}
    return {"reply": (f"Saved to {site}, {_fmt_12h(start_hhmm)}–{_fmt_12h(finish_hhmm)} "
                      f"({hours:g}h) ✅. Reply WRONG if that's not right."),
            "ts_id": ts_id, "needs_detail": False}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def process_inbound(client: httpx.AsyncClient, *, tenant_cfg: dict, user: Optional[dict],
                          from_number: str, body: str, message_log_id: Optional[str],
                          media: Optional[list] = None) -> Optional[str]:
    tenant_id = tenant_cfg["tenant_id"]
    body = body or ""

    # 1. Keywords first (work even for unregistered)
    kw = _classify_keyword(body)
    if kw == "help":
        await _stamp_message(client, message_log_id, category="help")
        return ("Text us what you did at your site and your finish time (e.g. \"poured slab, "
                "done 3:30\"). Reply PHOTO for a photo-upload link. Reply STOP to mute reminders.")
    if user and kw in ("stop", "start"):
        await _set_reminders_enabled(client, user["id"], kw == "start")
        await _stamp_message(client, message_log_id, category=kw)
        return ("You've been unsubscribed from reminders. Reply START to resume."
                if kw == "stop" else "You're subscribed to reminders again.")

    # 2. Unregistered number
    if not user:
        await _stamp_message(client, message_log_id, category="other")
        mgr = tenant_cfg.get("manager_phone_number")
        return (f"This number isn't registered. Please contact your manager"
                + (f" on {mgr}." if mgr else ".")) if mgr is not None else None

    user_id = user["id"]
    tz = await _get_tenant_tz(client, tenant_id)

    # 3. Resolve the sign-on (sign-on first) — honouring any pending question
    pending = await _get_pending(client, tenant_id, from_number)
    signon = None

    if pending and pending["state"] == "awaiting_finish_time":
        signon_id = (pending.get("payload") or {}).get("signon_id")
        finish = _parse_finish_time(body)
        signons = await _active_signons(client, user_id)
        signon = next((s for s in signons if s["id"] == signon_id), None)
        if not signon:
            await _clear_pending(client, tenant_id, from_number)
            return "That sign-on has already been closed. Scan in again to log a new shift."
        if not finish:
            return "Sorry, I didn't catch a time. What time did you finish? (e.g. 3:30pm)"
        await _stamp_message(client, message_log_id, site_id=signon["site_id"],
                             signon_id=signon["id"], category="finish")
        await _clear_pending(client, tenant_id, from_number)
        res = await _finalize(client, tenant_id=tenant_id, user_id=user_id,
                              signon=signon, finish_hhmm=finish, tz=tz)
        if res.get("needs_detail"):
            await _set_pending(client, tenant_id, from_number, user_id, "awaiting_detail",
                               {"timesheet_id": res["ts_id"], "site_name": signon.get("site_name"),
                                "site_id": signon.get("site_id"), "signon_id": signon["id"]})
        return res["reply"]

    if pending and pending["state"] == "awaiting_detail":
        # We finalized a shift with no description and asked what they focused on.
        # Their reply becomes the work_description (STOP/HELP already handled above).
        payload = pending.get("payload") or {}
        site = payload.get("site_name") or "your site"
        if _is_photo_keyword(body) and payload.get("signon_id"):
            # Honour a photo request but keep waiting for the detail line.
            return (f"📷 Add photos for {site}:\n{photo_link(payload['signon_id'])}\n\n"
                    f"And a quick line on what you focused on today?")
        detail = (body or "").strip()
        await _clear_pending(client, tenant_id, from_number)
        ts_id = payload.get("timesheet_id")
        if ts_id and detail:
            await client.patch(f"{_url()}/rest/v1/timesheets",
                               headers={**_headers(), "Prefer": "return=minimal"},
                               params={"id": f"eq.{ts_id}"},
                               json={"work_description": detail})
            await _stamp_message(client, message_log_id, site_id=payload.get("site_id"),
                                 category="detail")
            return f"Perfect — added to your {site} log ✅. Thanks!"
        return f"No worries — reply any time with what you focused on at {site}."

    signons = await _active_signons(client, user_id)

    if pending and pending["state"] == "awaiting_site":
        # Worker is answering "which site?" — match their reply to a candidate.
        options = (pending.get("payload") or {}).get("options", [])
        choice = next((o for o in options
                       if o.get("site_name") and o["site_name"].lower() in body.lower()), None)
        if not choice:
            names = " or ".join(o.get("site_name", "?") for o in options)
            return f"Which site — {names}?"
        signon = next((s for s in signons if s["id"] == choice["signon_id"]), None)
        await _clear_pending(client, tenant_id, from_number)
        if not signon:
            return "That sign-on has already been closed. Scan in again to log a new shift."
    elif len(signons) == 1:
        signon = signons[0]
    elif len(signons) == 0:
        await _stamp_message(client, message_log_id, category="other")
        return ("Looks like you haven't signed in at a site today. Please scan the QR to sign "
                "in, then text your update.")
    else:
        # Multiple active sign-ons — ask which.
        options = [{"signon_id": s["id"], "site_name": s["site_name"]} for s in signons]
        await _set_pending(client, tenant_id, from_number, user_id, "awaiting_site",
                           {"options": options})
        names = " or ".join(o["site_name"] or "?" for o in options)
        return f"Which site is this for — {names}?"

    # 4. We have a sign-on.
    site = signon.get("site_name") or "your site"

    # PHOTO keyword -> reply with a web upload link (AU Twilio can't receive MMS)
    if _is_photo_keyword(body) and not media:
        await _stamp_message(client, message_log_id, site_id=signon["site_id"],
                             signon_id=signon["id"], category="other")
        return f"📷 Add photos for {site}:\n{photo_link(signon['id'])}"

    # Ingest any photos (MMS — works outside AU), then handle text (note vs finish).
    photo_count = 0
    if media:
        photo_count = await _ingest_media(client, media, tenant_id=tenant_id, user_id=user_id,
                                          signon=signon, caption=body)
    # An MMS reached the webhook but nothing landed (AU inbound MMS is unreliable
    # and usually can't be retrieved). Don't fake success — point them at the link.
    media_failed = bool(media) and photo_count == 0

    finish = _parse_finish_time(body)
    done = _is_done_signal(body) or finish is not None

    if done and finish:
        await _stamp_message(client, message_log_id, site_id=signon["site_id"],
                             signon_id=signon["id"], category="finish")
        res = await _finalize(client, tenant_id=tenant_id, user_id=user_id,
                              signon=signon, finish_hhmm=finish, tz=tz)
        if res.get("needs_detail"):
            await _set_pending(client, tenant_id, from_number, user_id, "awaiting_detail",
                               {"timesheet_id": res["ts_id"], "site_name": signon.get("site_name"),
                                "site_id": signon.get("site_id"), "signon_id": signon["id"]})
        return res["reply"]

    if done and not finish:
        # "done" but no time — record as a note, then ask for the time.
        await _stamp_message(client, message_log_id, site_id=signon["site_id"],
                             signon_id=signon["id"], category="note")
        await _set_pending(client, tenant_id, from_number, user_id, "awaiting_finish_time",
                           {"signon_id": signon["id"]})
        return "Got it. What time did you finish? (e.g. 3:30pm)"

    # Photo and/or plain note — accumulate, light ack.
    has_text = bool((body or "").strip())
    if photo_count and not has_text:
        cat = "photo"
    elif has_text:
        cat = "note"
    else:
        cat = "other"  # e.g. an MMS we couldn't ingest, no text
    await _stamp_message(client, message_log_id, site_id=signon["site_id"],
                         signon_id=signon["id"], category=cat)

    if media_failed:
        if has_text:
            return (f"Got your note for {site} ✅ — but I can't receive photos directly here. "
                    f"Reply PHOTO for an upload link.")
        return ("I can't receive photos directly on this number. "
                "Reply PHOTO and I'll send you an upload link.")
    if photo_count and has_text:
        return f"Got it — note + {_photos_label(photo_count)} added to {site} ✅"
    if photo_count:
        return f"Got your {_photos_label(photo_count)} for {site} ✅"
    return f"Got it — added to {site} ✅ (reply PHOTO to add a photo)"
