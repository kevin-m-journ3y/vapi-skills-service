"""SMS reminder scheduler for QR sign-on users who haven't called Jill.

Uses APScheduler AsyncIOScheduler with CronTrigger per tenant.
Each enabled tenant gets two cron jobs (first + second reminder time).
Jobs query for users who signed on today but have no timesheet entry.
"""

import os
import fcntl
import logging
import tempfile
from datetime import datetime, date
from typing import Optional

import httpx
from datetime import timezone
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.twilio_service import send_sms

logger = logging.getLogger(__name__)

# Module-level scheduler instance
scheduler = AsyncIOScheduler()

# File lock to ensure only one worker runs the scheduler (multi-worker safe)
_lock_file = None
_is_scheduler_owner = False

SUPABASE_URL = ""
SUPABASE_KEY = ""


def _headers():
    global SUPABASE_KEY
    if not SUPABASE_KEY:
        SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
    key = SUPABASE_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _url():
    global SUPABASE_URL
    if not SUPABASE_URL:
        SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    return SUPABASE_URL


async def _get_enabled_tenants() -> list:
    """Fetch all tenants with QR sign-on and reminders enabled."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_url()}/rest/v1/qr_signon_config",
            headers=_headers(),
            params={
                "is_enabled": "eq.true",
                "reminder_enabled": "eq.true",
                "select": "tenant_id,first_reminder_time,second_reminder_time,jill_phone_number,twilio_from_number,inbound_messaging_enabled",
            },
        )
        if resp.status_code != 200:
            logger.error("Failed to fetch QR configs: %s", resp.text)
            return []

        configs = resp.json()
        if not configs:
            return []

        # Fetch tenant timezones
        tenant_ids = [c["tenant_id"] for c in configs]
        tenant_resp = await client.get(
            f"{_url()}/rest/v1/tenants",
            headers=_headers(),
            params={
                "id": f"in.({','.join(tenant_ids)})",
                "select": "id,name,timezone",
            },
        )
        tz_map = {}
        if tenant_resp.status_code == 200:
            tz_map = {t["id"]: t.get("timezone", "Australia/Sydney") for t in tenant_resp.json()}

        for c in configs:
            c["timezone"] = tz_map.get(c["tenant_id"], "Australia/Sydney")
            if not tz_map.get(c["tenant_id"]):
                logger.warning("No timezone for tenant %s, defaulting to Australia/Sydney", c["tenant_id"])

        return configs


async def _find_users_needing_reminder(tenant_id: str, timezone_str: str) -> list:
    """Find enrolled users who signed on today but have unlogged sites.

    Checks per-site completeness: a user needs a reminder if they have
    sign-on sites without matching timesheet entries (not just zero timesheets).
    """
    tz = ZoneInfo(timezone_str)
    now_local = datetime.now(tz)
    today = now_local.date()

    # Build date boundaries in UTC for querying
    today_start_local = datetime.combine(today, datetime.min.time()).replace(tzinfo=tz)
    today_end_local = datetime.combine(today, datetime.max.time()).replace(tzinfo=tz)
    today_start_utc = today_start_local.astimezone(timezone.utc).isoformat()

    async with httpx.AsyncClient() as client:
        # Get all sign-ons today (active OR signed_off — not just active)
        signons_resp = await client.get(
            f"{_url()}/rest/v1/site_signons",
            headers=_headers(),
            params={
                "tenant_id": f"eq.{tenant_id}",
                "signed_on_at": f"gte.{today_start_utc}",
                "status": "in.(active,signed_off)",
                "select": "user_id,site_id",
            },
        )
        if signons_resp.status_code != 200 or not signons_resp.json():
            return []

        # Build per-user set of sign-on site_ids
        user_signon_sites = {}
        for s in signons_resp.json():
            uid = s["user_id"]
            if uid not in user_signon_sites:
                user_signon_sites[uid] = set()
            user_signon_sites[uid].add(s["site_id"])

        all_user_ids = list(user_signon_sites.keys())

        # Get timesheets for today for these users (with site_id)
        timesheets_resp = await client.get(
            f"{_url()}/rest/v1/timesheets",
            headers=_headers(),
            params={
                "tenant_id": f"eq.{tenant_id}",
                "work_date": f"eq.{today.isoformat()}",
                "user_id": f"in.({','.join(all_user_ids)})",
                "select": "user_id,site_id",
            },
        )
        user_timesheet_sites = {}
        if timesheets_resp.status_code == 200 and timesheets_resp.json():
            for t in timesheets_resp.json():
                uid = t["user_id"]
                if uid not in user_timesheet_sites:
                    user_timesheet_sites[uid] = set()
                user_timesheet_sites[uid].add(t["site_id"])

        # Users who have sign-on sites without matching timesheets
        missing_user_ids = []
        for uid, signon_sites in user_signon_sites.items():
            logged_sites = user_timesheet_sites.get(uid, set())
            if signon_sites - logged_sites:  # Any unlogged sites?
                missing_user_ids.append(uid)

        if not missing_user_ids:
            return []

        # Fetch user details (only enrolled users with phone numbers)
        users_resp = await client.get(
            f"{_url()}/rest/v1/users",
            headers=_headers(),
            params={
                "id": f"in.({','.join(missing_user_ids)})",
                "sms_reminders_enabled": "eq.true",
                "is_active": "eq.true",
                "select": "id,name,phone_number",
            },
        )
        if users_resp.status_code != 200:
            return []

        return users_resp.json()


async def _send_reminders_for_tenant(
    tenant_id: str, timezone_str: str, jill_phone: str,
    from_number: Optional[str] = None, inbound_enabled: bool = False
):
    """Send SMS reminders to all users needing one for this tenant."""
    try:
        users = await _find_users_needing_reminder(tenant_id, timezone_str)
        if not users:
            logger.info("No reminders needed for tenant %s", tenant_id)
            return

        for user in users:
            phone = user.get("phone_number")
            name = user.get("name", "").split()[0] if user.get("name") else "there"

            if not phone:
                logger.warning("User %s has no phone number, skipping", user["id"])
                continue

            if inbound_enabled:
                # Tenant has Text & Photo Updates on: the reminder is sent from the
                # same number that handles both SMS and Jill, so they can just reply.
                call_part = f", or call {jill_phone} to talk to Jill" if jill_phone else ""
                message = (
                    f"Hey {name}, you still have timesheet entries to log for today. "
                    f"Reply with what you did and your finish time{call_part}."
                )
            elif jill_phone:
                message = (
                    f"Hey {name}, you still have timesheet entries to log for today. "
                    f"Call Jill on {jill_phone} to finish up."
                )
            else:
                message = (
                    f"Hey {name}, you still have timesheet entries to log for today. "
                    f"Call in to finish up."
                )

            result = await send_sms(phone, message, from_number=from_number or None)
            if result["success"]:
                logger.info("Reminder sent to %s (%s)", name, phone)
            else:
                logger.error("Failed to send reminder to %s: %s", phone, result.get("error"))

    except Exception as e:
        logger.error("Error sending reminders for tenant %s: %s", tenant_id, str(e))


def _job_id(tenant_id: str, reminder_num: int) -> str:
    """Generate a consistent job ID for a tenant's reminder."""
    return f"reminder_{tenant_id}_{reminder_num}"


def _remove_tenant_jobs(tenant_id: str):
    """Remove all reminder jobs for a tenant."""
    for num in (1, 2):
        job_id = _job_id(tenant_id, num)
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            logger.info("Removed job %s", job_id)


def _schedule_tenant_jobs(config: dict):
    """Schedule reminder jobs for a single tenant config."""
    tenant_id = config["tenant_id"]
    timezone_str = config.get("timezone", "Australia/Sydney")
    jill_phone = config.get("jill_phone_number", "")
    from_number = config.get("twilio_from_number", "") or None
    inbound_enabled = bool(config.get("inbound_messaging_enabled"))

    # Remove existing jobs first
    _remove_tenant_jobs(tenant_id)

    for num, time_field in [(1, "first_reminder_time"), (2, "second_reminder_time")]:
        time_str = config.get(time_field, "17:30" if num == 1 else "19:00")
        if not time_str:
            continue

        try:
            parts = time_str.split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            logger.warning("Invalid time '%s' for tenant %s, skipping", time_str, tenant_id)
            continue

        job_id = _job_id(tenant_id, num)
        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            timezone=timezone_str,
        )

        scheduler.add_job(
            _send_reminders_for_tenant,
            trigger=trigger,
            id=job_id,
            args=[tenant_id, timezone_str, jill_phone, from_number, inbound_enabled],
            replace_existing=True,
            name=f"Reminder {num} for tenant {tenant_id}",
        )
        logger.info(
            "Scheduled reminder %d for tenant %s at %02d:%02d (%s)",
            num, tenant_id, hour, minute, timezone_str,
        )


async def reschedule_tenant(tenant_id: str):
    """Reschedule jobs for a specific tenant (called when admin updates config)."""
    if not scheduler.running:
        logger.warning("Scheduler not running, skipping reschedule for %s", tenant_id)
        return

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_url()}/rest/v1/qr_signon_config",
            headers=_headers(),
            params={
                "tenant_id": f"eq.{tenant_id}",
                "select": "tenant_id,is_enabled,reminder_enabled,first_reminder_time,second_reminder_time,jill_phone_number,twilio_from_number,inbound_messaging_enabled",
            },
        )
        if resp.status_code != 200 or not resp.json():
            _remove_tenant_jobs(tenant_id)
            return

        config = resp.json()[0]

        if not config.get("is_enabled") or not config.get("reminder_enabled"):
            _remove_tenant_jobs(tenant_id)
            logger.info("Reminders disabled for tenant %s, jobs removed", tenant_id)
            return

        # Fetch tenant timezone
        tenant_resp = await client.get(
            f"{_url()}/rest/v1/tenants",
            headers=_headers(),
            params={
                "id": f"eq.{tenant_id}",
                "select": "timezone",
            },
        )
        tz = "Australia/Sydney"
        if tenant_resp.status_code == 200 and tenant_resp.json():
            tz = tenant_resp.json()[0].get("timezone") or "Australia/Sydney"
        if tz == "Australia/Sydney":
            logger.warning("No timezone for tenant %s, defaulting to Australia/Sydney", tenant_id)

        config["timezone"] = tz
        _schedule_tenant_jobs(config)


def _acquire_scheduler_lock() -> bool:
    """Try to acquire an exclusive file lock so only one worker runs the scheduler."""
    global _lock_file, _is_scheduler_owner
    try:
        lock_path = os.path.join(tempfile.gettempdir(), "journ3y_scheduler.lock")
        _lock_file = open(lock_path, "w")
        fcntl.flock(_lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _is_scheduler_owner = True
        logger.info("Acquired scheduler lock (pid=%d)", os.getpid())
        return True
    except (OSError, IOError):
        logger.info("Another worker owns the scheduler, skipping (pid=%d)", os.getpid())
        if _lock_file:
            _lock_file.close()
            _lock_file = None
        return False


async def start_scheduler():
    """Start the scheduler and load all tenant jobs. Called on app startup."""
    # Safety: local/dev instances must not run the reminder scheduler against the
    # shared prod DB (would double-send real reminders alongside Railway).
    if os.getenv("DISABLE_SCHEDULER", "").lower() == "true":
        logger.info("Reminder scheduler disabled (DISABLE_SCHEDULER=true)")
        return

    if not _acquire_scheduler_lock():
        return

    try:
        configs = await _get_enabled_tenants()
        for config in configs:
            _schedule_tenant_jobs(config)

        scheduler.start()
        logger.info(
            "Reminder scheduler started with %d jobs for %d tenants",
            len(scheduler.get_jobs()),
            len(configs),
        )
    except Exception as e:
        logger.error("Failed to start reminder scheduler: %s", str(e))


def stop_scheduler():
    """Stop the scheduler. Called on app shutdown."""
    global _lock_file, _is_scheduler_owner
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Reminder scheduler stopped")
    if _lock_file:
        try:
            fcntl.flock(_lock_file.fileno(), fcntl.LOCK_UN)
            _lock_file.close()
        except Exception:
            pass
        _lock_file = None
        _is_scheduler_owner = False
