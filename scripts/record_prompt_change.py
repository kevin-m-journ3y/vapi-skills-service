"""
Shared utility to record prompt changes in the database.

Usage:
    from scripts.record_prompt_change import record_prompt_change

    await record_prompt_change(
        assistant_key="JSMB-Jill-timesheet",
        assistant_id="d3a5e1cf-82cb-4f6e-a406-b0170ede3d10",
        change_summary="Added half seven time parsing",
        change_category="prompt",
        prompt_content=new_prompt,   # optional, for hashing
        changed_by="script",
    )
"""

import hashlib
import os
import httpx


async def record_prompt_change(
    assistant_key: str,
    assistant_id: str = None,
    change_summary: str = "Prompt updated",
    change_category: str = "prompt",
    prompt_content: str = None,
    changed_by: str = "script",
):
    """Record a prompt change in the prompt_changes table."""
    prompt_hash = None
    if prompt_content:
        prompt_hash = hashlib.sha256(prompt_content.encode()).hexdigest()[:16]

    record = {
        "assistant_key": assistant_key,
        "assistant_id": assistant_id,
        "change_summary": change_summary,
        "change_category": change_category,
        "prompt_hash": prompt_hash,
        "changed_by": changed_by,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/prompt_changes",
            headers={
                "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=record
        )

        if response.status_code in [200, 201, 204]:
            print(f"  Recorded prompt change in learning loop")
        else:
            print(f"  Warning: Failed to record prompt change: {response.status_code}")
