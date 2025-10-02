"""
Test script to simulate VAPI save-update request and verify transcript capture
"""
import asyncio
import httpx
import json

# Simulate a realistic VAPI tool call request based on actual VAPI format
test_request = {
    "message": {
        "type": "tool-calls",
        "toolCalls": [  # Note: toolCalls not toolCallList
            {
                "id": "call_test123",
                "type": "function",
                "function": {
                    "name": "save_site_progress_update",
                    "arguments": {  # Already parsed as dict, not JSON string
                        "site_id": "ce2052dd-2e6c-4857-a224-6c3ab03864df",
                        "raw_notes": "We poured the slab today. Got some reo delivered. Architects came by to inspect. Everything looks good, no issues."
                    }
                }
            }
        ],
        "call": {
            "id": "test-call-001",
            "messages": [
                {
                    "role": "assistant",
                    "content": "Perfect! Let's get that site update recorded for you. Which site are you calling about?"
                },
                {
                    "role": "user",
                    "content": "Ocean White House"
                },
                {
                    "role": "assistant",
                    "content": "Great! Let's record your site progress update for Ocean White House. Tell me about what's been happening — I'll make sure we cover all the important areas."
                },
                {
                    "role": "user",
                    "content": "We poured the slab today."
                },
                {
                    "role": "assistant",
                    "content": "Got it! Any deliveries come in today? Materials, equipment, anything like that?"
                },
                {
                    "role": "user",
                    "content": "Yeah, we got some reo delivered this morning."
                },
                {
                    "role": "assistant",
                    "content": "Perfect. What did the team work on today? Any milestones hit or major progress?"
                },
                {
                    "role": "user",
                    "content": "Just the slab pour mainly. That was the big job today."
                },
                {
                    "role": "assistant",
                    "content": "Excellent. Any problems or issues come up? Anything that needs to be escalated?"
                },
                {
                    "role": "user",
                    "content": "No issues at all."
                },
                {
                    "role": "assistant",
                    "content": "Great to hear. Did anyone visit the site today like the client, suppliers or designers?"
                },
                {
                    "role": "user",
                    "content": "Yeah, the architects came by to check the slab."
                },
                {
                    "role": "assistant",
                    "content": "Perfect. How are site conditions? Any safety observations or access issues?"
                },
                {
                    "role": "user",
                    "content": "All good, no problems."
                },
                {
                    "role": "assistant",
                    "content": "Excellent. What's on deck for tomorrow? Anything that needs follow-up or upcoming deliveries?"
                },
                {
                    "role": "user",
                    "content": "We'll be cleaning up after the pour tomorrow."
                },
                {
                    "role": "assistant",
                    "content": "Perfect! Let me quickly summarize what I've captured: You poured the slab today, received reo delivery, architects inspected, and tomorrow you'll be cleaning up. Is there anything else important I should know about Ocean White House today?"
                },
                {
                    "role": "user",
                    "content": "No, that's everything."
                }
            ]
        }
    }
}

async def test_save_update():
    """Test the save-update endpoint with simulated VAPI data"""

    print("=" * 80)
    print("Testing transcript capture from VAPI request")
    print("=" * 80)

    # First, create an authentication log entry so session context exists
    import sys
    sys.path.insert(0, '.')
    from app.config import settings

    async with httpx.AsyncClient() as client:
        # Create auth log
        await client.post(
            f"{settings.SUPABASE_URL}/rest/v1/vapi_logs",
            headers={
                "apikey": settings.SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal"
            },
            json={
                "vapi_call_id": "test-call-001",
                "interaction_type": "authentication",
                "user_id": "b784aa16-d49b-44be-a5c8-e20103afa230",
                "tenant_id": "db3d1562-9d17-417d-877b-d105929d2914",
                "caller_phone": "+61412345678",
                "raw_log_data": {"test": True}
            }
        )
        print("✅ Created test authentication session")

        # Now send to save-update endpoint
        response = await client.post(
            "http://localhost:8000/api/v1/skills/site-updates/save-update",
            json=test_request,
            timeout=30.0
        )

        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Body: {json.dumps(response.json(), indent=2)}")

        if response.status_code == 200:
            result = response.json()
            if result.get("results", [{}])[0].get("result", {}).get("success"):
                update_id = result["results"][0]["result"]["update_id"]
                print(f"\n✅ Update created successfully: {update_id}")

                # Now check the database to see if transcript was captured
                print("\n" + "=" * 80)
                print("Checking database for transcript...")
                print("=" * 80)

                db_response = await client.get(
                    f"{settings.SUPABASE_URL}/rest/v1/site_progress_updates",
                    headers={
                        "apikey": settings.SUPABASE_SERVICE_KEY,
                        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}"
                    },
                    params={
                        "id": f"eq.{update_id}",
                        "select": "raw_transcript,main_focus,work_progress,site_visitors"
                    }
                )

                if db_response.status_code == 200:
                    record = db_response.json()[0]
                    print(f"\n📋 Database Record:")
                    print(f"  - raw_transcript length: {len(record.get('raw_transcript', ''))}")
                    print(f"  - main_focus: {record.get('main_focus')}")
                    print(f"  - work_progress: {record.get('work_progress')}")
                    print(f"  - site_visitors: {record.get('site_visitors')}")

                    print(f"\n📝 Raw Transcript Preview (first 500 chars):")
                    transcript = record.get('raw_transcript', '')
                    print(transcript[:500])

                    if transcript and len(transcript) > 100:
                        print("\n✅ SUCCESS: Transcript captured correctly!")
                    else:
                        print("\n❌ ISSUE: Transcript not captured or too short")
                        print(f"   Expected: Tagged conversation with User:/Assistant:")
                        print(f"   Got: {transcript[:200]}")
                else:
                    print(f"❌ Failed to query database: {db_response.status_code}")
            else:
                print("\n❌ Update failed")
                print(result)
        else:
            print("\n❌ Request failed")

if __name__ == "__main__":
    asyncio.run(test_save_update())
