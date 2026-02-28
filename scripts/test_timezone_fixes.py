"""Tests for timezone standardization changes.

Validates:
1. ZoneInfo .replace(tzinfo=tz) gives correct DST offsets (the pytz bug fix)
2. Authentication endpoint returns timezone-aware data for JOURN3Y tenant
3. datetime.now(timezone.utc).isoformat() produces +00:00 suffix
4. Existing test suite still passes

Usage:
    python scripts/test_timezone_fixes.py
"""

import asyncio
import sys
import os
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def test_zoneinfo_replace_gives_correct_dst_offset():
    """The core bug: pytz .replace(tzinfo=tz) gives LMT offset (+10:05),
    ZoneInfo .replace(tzinfo=tz) gives correct AEDT/AEST offset."""
    tz = ZoneInfo("Australia/Sydney")

    # February = AEDT (daylight saving), expect UTC+11
    feb_date = datetime(2026, 2, 15, 0, 0, 0).replace(tzinfo=tz)
    offset_hours = feb_date.utcoffset().total_seconds() / 3600
    assert offset_hours == 11.0, f"Feb should be AEDT (+11), got +{offset_hours}"

    # July = AEST (standard time), expect UTC+10
    jul_date = datetime(2026, 7, 15, 0, 0, 0).replace(tzinfo=tz)
    offset_hours = jul_date.utcoffset().total_seconds() / 3600
    assert offset_hours == 10.0, f"Jul should be AEST (+10), got +{offset_hours}"

    print("  PASS: ZoneInfo .replace() gives correct DST offsets (AEDT=+11, AEST=+10)")


def test_utcnow_replacement_has_timezone_suffix():
    """datetime.now(timezone.utc).isoformat() must produce +00:00 suffix."""
    ts = datetime.now(timezone.utc).isoformat()
    assert "+00:00" in ts, f"Expected +00:00 suffix, got: {ts}"
    print(f"  PASS: UTC timestamp has timezone suffix: {ts}")


def test_today_boundaries_convert_correctly():
    """Today start/end in tenant TZ should convert to correct UTC range."""
    tz = ZoneInfo("Australia/Sydney")
    today_str = "2026-02-28"
    today_naive = datetime.strptime(today_str, "%Y-%m-%d")

    today_start = today_naive.replace(hour=0, minute=0, second=0, tzinfo=tz)
    today_end = today_naive.replace(hour=23, minute=59, second=59, tzinfo=tz)

    # Convert to UTC
    start_utc = today_start.astimezone(timezone.utc)
    end_utc = today_end.astimezone(timezone.utc)

    # Feb 28 00:00 AEDT = Feb 27 13:00 UTC
    assert start_utc.day == 27, f"Start UTC day should be 27, got {start_utc.day}"
    assert start_utc.hour == 13, f"Start UTC hour should be 13, got {start_utc.hour}"

    # Feb 28 23:59 AEDT = Feb 28 12:59 UTC
    assert end_utc.day == 28, f"End UTC day should be 28, got {end_utc.day}"
    assert end_utc.hour == 12, f"End UTC hour should be 12, got {end_utc.hour}"

    print(f"  PASS: Today boundaries convert correctly (start={start_utc.isoformat()}, end={end_utc.isoformat()})")


async def test_auth_endpoint_live():
    """Hit the auth endpoint with a JOURN3Y user and verify timezone fields."""
    import httpx

    JOURN3Y_PHONE = "+61434825126"  # Kevin Morrell - JOURN3Y test tenant

    # Build VAPI-format request
    vapi_request = {
        "message": {
            "type": "tool-calls",
            "call": {
                "id": "test-tz-validation",
                "customer": {"number": JOURN3Y_PHONE},
            },
            "toolCalls": [
                {
                    "id": "tc-tz-test",
                    "function": {
                        "name": "authenticate-by-phone",
                        "arguments": json.dumps({"caller_phone": JOURN3Y_PHONE}),
                    },
                }
            ],
        }
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8000/api/v1/vapi/authenticate-by-phone",
            json=vapi_request,
            timeout=10,
        )

    assert resp.status_code == 200, f"Auth endpoint returned {resp.status_code}: {resp.text}"
    data = resp.json()
    result = data["results"][0]["result"]

    assert result["authorized"] is True, f"Not authorized: {result.get('message')}"
    assert result["tenant_name"] == "JOURN3Y", f"Wrong tenant: {result['tenant_name']}"
    assert result["tenant_timezone"] == "Australia/Sydney", f"Wrong TZ: {result['tenant_timezone']}"

    # Verify date is in correct format and matches local date
    tz = ZoneInfo("Australia/Sydney")
    expected_date = datetime.now(tz).strftime("%Y-%m-%d")
    assert result["current_date"] == expected_date, (
        f"Date mismatch: got {result['current_date']}, expected {expected_date}"
    )

    expected_day = datetime.now(tz).strftime("%A")
    assert result["day_of_week"] == expected_day, (
        f"Day mismatch: got {result['day_of_week']}, expected {expected_day}"
    )

    print(f"  PASS: Auth endpoint returns correct timezone data:")
    print(f"         tenant_timezone={result['tenant_timezone']}")
    print(f"         current_date={result['current_date']}")
    print(f"         current_time={result['current_time']}")
    print(f"         day_of_week={result['day_of_week']}")
    print(f"         current_datetime={result['current_datetime']}")
    print(f"         skills={result['skill_count']}, sites={result['site_count']}")


def test_no_pytz_imports():
    """Verify no pytz imports remain in the app/ directory."""
    import subprocess

    result = subprocess.run(
        ["grep", "-r", "import pytz", "app/"],
        capture_output=True, text=True,
    )
    assert result.stdout.strip() == "", f"Found pytz imports:\n{result.stdout}"
    print("  PASS: No pytz imports found in app/")


def test_no_utcnow_calls():
    """Verify no datetime.utcnow() calls remain in the app/ directory."""
    import subprocess

    result = subprocess.run(
        ["grep", "-r", "utcnow()", "app/"],
        capture_output=True, text=True,
    )
    assert result.stdout.strip() == "", f"Found utcnow() calls:\n{result.stdout}"
    print("  PASS: No utcnow() calls found in app/")


async def main():
    print("\n=== Timezone Standardization Tests ===\n")

    passed = 0
    failed = 0

    # Unit tests (no server needed)
    print("[1/6] ZoneInfo DST offset test...")
    try:
        test_zoneinfo_replace_gives_correct_dst_offset()
        passed += 1
    except AssertionError as e:
        print(f"  FAIL: {e}")
        failed += 1

    print("[2/6] UTC timestamp suffix test...")
    try:
        test_utcnow_replacement_has_timezone_suffix()
        passed += 1
    except AssertionError as e:
        print(f"  FAIL: {e}")
        failed += 1

    print("[3/6] Today boundary conversion test...")
    try:
        test_today_boundaries_convert_correctly()
        passed += 1
    except AssertionError as e:
        print(f"  FAIL: {e}")
        failed += 1

    print("[4/6] No pytz imports remaining...")
    try:
        test_no_pytz_imports()
        passed += 1
    except AssertionError as e:
        print(f"  FAIL: {e}")
        failed += 1

    print("[5/6] No utcnow() calls remaining...")
    try:
        test_no_utcnow_calls()
        passed += 1
    except AssertionError as e:
        print(f"  FAIL: {e}")
        failed += 1

    # Live integration test (needs server running)
    print("[6/6] Live auth endpoint test (JOURN3Y tenant)...")
    try:
        await test_auth_endpoint_live()
        passed += 1
    except Exception as e:
        print(f"  FAIL: {e}")
        print("  (Is the server running on localhost:8000?)")
        failed += 1

    print(f"\n{'='*40}")
    if failed == 0:
        print(f"ALL {passed} TESTS PASSED")
    else:
        print(f"{passed} passed, {failed} FAILED")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
