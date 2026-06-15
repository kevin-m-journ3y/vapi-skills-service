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
# Finalization
# ---------------------------------------------------------------------------
async def _finalize(client, *, tenant_id, user_id, signon, finish_hhmm, tz) -> str:
    """Create the day's timesheet from accumulated notes + sign-on start + finish
    time, close the sign-on, return the confirmation reply."""
    start_dt = datetime.fromisoformat(signon["signed_on_at"].replace("Z", "+00:00")).astimezone(tz)
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

    site = signon.get("site_name") or "your site"
    if incomplete:
        return (f"Saved to {site} ✅ — but the finish time looked off, so I've left hours "
                f"for your manager to confirm. Reply with your finish time to fix.")
    return (f"Saved to {site}, {_fmt_12h(start_hhmm)}–{_fmt_12h(finish_hhmm)} "
            f"({hours:g}h) ✅. Reply WRONG if that's not right.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def process_inbound(client: httpx.AsyncClient, *, tenant_cfg: dict, user: Optional[dict],
                          from_number: str, body: str, message_log_id: Optional[str]) -> Optional[str]:
    tenant_id = tenant_cfg["tenant_id"]
    body = body or ""

    # 1. Keywords first (work even for unregistered)
    kw = _classify_keyword(body)
    if kw == "help":
        await _stamp_message(client, message_log_id, category="help")
        return ("Text us what you did at your site and your finish time (e.g. \"poured slab, "
                "done 3:30\"). Reply STOP to mute reminders.")
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
        return await _finalize(client, tenant_id=tenant_id, user_id=user_id,
                               signon=signon, finish_hhmm=finish, tz=tz)

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

    # 4. We have a sign-on. Note vs finish.
    finish = _parse_finish_time(body)
    done = _is_done_signal(body) or finish is not None

    if done and finish:
        await _stamp_message(client, message_log_id, site_id=signon["site_id"],
                             signon_id=signon["id"], category="finish")
        return await _finalize(client, tenant_id=tenant_id, user_id=user_id,
                               signon=signon, finish_hhmm=finish, tz=tz)

    if done and not finish:
        # "done" but no time — record as a note, then ask for the time.
        await _stamp_message(client, message_log_id, site_id=signon["site_id"],
                             signon_id=signon["id"], category="note")
        await _set_pending(client, tenant_id, from_number, user_id, "awaiting_finish_time",
                           {"signon_id": signon["id"]})
        return "Got it. What time did you finish? (e.g. 3:30pm)"

    # Plain note — accumulate, light ack.
    await _stamp_message(client, message_log_id, site_id=signon["site_id"],
                         signon_id=signon["id"], category="note")
    site = signon.get("site_name") or "your site"
    return f"Got it — added to {site} ✅"
