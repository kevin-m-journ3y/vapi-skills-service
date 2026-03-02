#!/usr/bin/env python3
"""
Backfill missing call_transcript in timesheets table from VAPI API.

For each timesheet that has a vapi_call_id but no call_transcript,
fetches the call data from VAPI API and extracts the transcript.
"""
import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.config import settings


async def backfill_transcripts():
    supabase_url = os.getenv("SUPABASE_URL") or settings.SUPABASE_URL
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY") or settings.SUPABASE_SERVICE_KEY
    vapi_key = os.getenv("VAPI_API_KEY") or settings.VAPI_API_KEY

    if not all([supabase_url, supabase_key, vapi_key]):
        print("Error: Missing SUPABASE_URL, SUPABASE_SERVICE_KEY, or VAPI_API_KEY")
        return

    sb_headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
    }
    vapi_headers = {
        "Authorization": f"Bearer {vapi_key}",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get timesheets missing transcripts
        print("Fetching timesheets missing call_transcript...")
        resp = await client.get(
            f"{supabase_url}/rest/v1/timesheets",
            headers=sb_headers,
            params={
                "select": "id,vapi_call_id,work_date",
                "call_transcript": "is.null",
                "vapi_call_id": "not.is.null",
                "order": "work_date.desc",
            },
        )

        if resp.status_code != 200:
            print(f"Error fetching timesheets: {resp.status_code} - {resp.text}")
            return

        timesheets = resp.json()
        print(f"Found {len(timesheets)} timesheets missing transcripts\n")

        if not timesheets:
            print("Nothing to backfill!")
            return

        updated = 0
        failed = 0

        for ts in timesheets:
            call_id = ts["vapi_call_id"]
            print(f"  [{ts['work_date']}] Call {call_id}...", end=" ")

            # Fetch call from VAPI
            call_resp = await client.get(
                f"https://api.vapi.ai/call/{call_id}",
                headers=vapi_headers,
            )

            if call_resp.status_code != 200:
                print(f"VAPI error {call_resp.status_code}")
                failed += 1
                continue

            call_data = call_resp.json()
            messages = call_data.get("messages", [])

            if not messages:
                # Try artifact.messages
                artifact = call_data.get("artifact", {})
                messages = artifact.get("messages", [])

            if not messages:
                print("no messages found")
                failed += 1
                continue

            # Build transcript
            transcript = ""
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "") or msg.get("message", "")
                if content:
                    if role == "user":
                        transcript += f"User: {content}\n"
                    elif role in ("assistant", "bot"):
                        transcript += f"Assistant: {content}\n"

            if not transcript.strip():
                print("empty transcript")
                failed += 1
                continue

            # Update timesheet
            patch_resp = await client.patch(
                f"{supabase_url}/rest/v1/timesheets",
                headers={**sb_headers, "Prefer": "return=minimal"},
                params={"id": f"eq.{ts['id']}"},
                json={"call_transcript": transcript},
            )

            if patch_resp.status_code in (200, 204):
                print(f"OK ({len(transcript)} chars)")
                updated += 1
            else:
                print(f"update failed: {patch_resp.status_code}")
                failed += 1

            # Small delay to avoid rate limits
            await asyncio.sleep(0.3)

        print(f"\nDone! Updated: {updated}, Failed: {failed}")


if __name__ == "__main__":
    asyncio.run(backfill_transcripts())
