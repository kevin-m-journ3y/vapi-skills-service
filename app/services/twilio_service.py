"""Twilio SMS service using httpx (async, consistent with codebase)."""

import os
import base64
import logging
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"


def _twilio_config():
    """Get Twilio config from env vars. Returns None if not configured."""
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER")
    if not all([sid, token, from_number]):
        return None
    return {"sid": sid, "token": token, "from_number": from_number}


async def send_sms(
    to_number: str,
    message: str,
    from_number: Optional[str] = None,
) -> dict:
    """Send an SMS via Twilio REST API.

    Returns dict with 'success', 'sid' (message SID), and 'error' if failed.
    """
    config = _twilio_config()
    if not config:
        logger.warning("Twilio not configured - SMS not sent to %s", to_number)
        return {"success": False, "error": "Twilio not configured"}

    send_from = from_number or config["from_number"]
    url = f"{TWILIO_API_BASE}/Accounts/{config['sid']}/Messages.json"

    # Twilio uses HTTP Basic Auth: AccountSID:AuthToken
    auth_str = base64.b64encode(
        f"{config['sid']}:{config['token']}".encode()
    ).decode()

    headers = {
        "Authorization": f"Basic {auth_str}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "To": to_number,
        "From": send_from,
        "Body": message,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, data=data, timeout=15.0)

        if resp.status_code == 201:
            result = resp.json()
            logger.info(
                "SMS sent to %s (SID: %s)", to_number, result.get("sid")
            )
            return {"success": True, "sid": result.get("sid")}
        else:
            error_msg = resp.text
            logger.error(
                "Twilio SMS failed (status=%d): %s", resp.status_code, error_msg
            )
            return {"success": False, "error": error_msg}

    except Exception as e:
        logger.error("Twilio SMS exception: %s", str(e))
        return {"success": False, "error": str(e)}
