#!/usr/bin/env python3
"""
VAPI Assistant Staging Pipeline

Safely test prompt/config changes before pushing to production.

Commands:
    python scripts/staging.py create [assistant]    # Clone production → staging
    python scripts/staging.py push [assistant]      # Push code changes to staging
    python scripts/staging.py eval [assistant]      # Run evals against staging
    python scripts/staging.py diff [assistant]      # Show prompt diff (staging vs production)
    python scripts/staging.py promote [assistant]   # Copy staging config → production
    python scripts/staging.py cleanup [assistant]   # Delete staging assistant
    python scripts/staging.py status                # Show all staging assistants
    python scripts/staging.py create-squad          # Create full staging squad + assign test phone
    python scripts/staging.py teardown-squad        # Delete staging squad + restore phone to prod

Arguments:
    assistant: timesheet, greeter, voice_notes, site_progress (default: timesheet)

Examples:
    python scripts/staging.py create timesheet
    python scripts/staging.py push timesheet --summary "Added forgot-to-sign-in handling"
    python scripts/staging.py eval timesheet
    python scripts/staging.py diff timesheet
    python scripts/staging.py promote timesheet
    python scripts/staging.py cleanup timesheet
"""

import argparse
import asyncio
import difflib
import json
import os
import sys
from datetime import datetime
from typing import Optional

import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

VAPI_API_KEY = os.getenv("VAPI_API_KEY")
VAPI_BASE_URL = "https://api.vapi.ai"

# Production assistant names → staging names
ASSISTANT_MAP = {
    "timesheet": "JSMB-Jill-timesheet",
    "greeter": "JSMB-Jill-authenticate-and-greet",
    "voice_notes": "JSMB-Jill-voice-notes",
    "site_progress": "JSMB-Jill-site-progress",
}

STAGING_SUFFIX = "-staging"

# Production squad and phone numbers
PROD_SQUAD_ID = "30016c3e-f038-4c18-9b33-5717be011eac"
PROD_SQUAD_NAME = "JSMB-Jill-multi-skill-squad"
STAGING_SQUAD_NAME = "JSMB-Jill-multi-skill-squad-staging"
TEST_PHONE_NUMBER_ID = "dbf0544d-8fe8-4f48-a1ce-b2f3888916b3"  # JOURN3Y +61468086094


def staging_name(prod_name: str) -> str:
    return f"{prod_name}{STAGING_SUFFIX}"


def get_assistant_class(key: str):
    """Import and return the assistant class for a given key"""
    if key == "timesheet":
        from app.assistants.timesheet import TimesheetAssistant
        return TimesheetAssistant()
    elif key == "greeter":
        from app.assistants.greeter import GreeterAssistant
        return GreeterAssistant()
    elif key == "voice_notes":
        from app.assistants.jill_voice_notes import JillVoiceNotesAssistant
        return JillVoiceNotesAssistant()
    elif key == "site_progress":
        from app.assistants.site_progress import SiteProgressAssistant
        return SiteProgressAssistant()
    else:
        raise ValueError(f"Unknown assistant: {key}")


async def find_assistant(client, headers, name: str) -> Optional[dict]:
    """Find a VAPI assistant by exact name"""
    response = await client.get(f"{VAPI_BASE_URL}/assistant", headers=headers)
    if response.status_code != 200:
        return None
    for a in response.json():
        if a.get("name") == name:
            return a
    return None


async def get_assistant_by_id(client, headers, assistant_id: str) -> Optional[dict]:
    """Get full assistant config by ID"""
    response = await client.get(
        f"{VAPI_BASE_URL}/assistant/{assistant_id}",
        headers=headers
    )
    if response.status_code == 200:
        return response.json()
    return None


# ─── COMMANDS ────────────────────────────────────────────────


async def cmd_create(assistant_key: str):
    """Clone production assistant → staging copy"""
    prod_name = ASSISTANT_MAP[assistant_key]
    stg_name = staging_name(prod_name)

    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Check if staging already exists
        existing = await find_assistant(client, headers, stg_name)
        if existing:
            print(f"Staging assistant already exists: {stg_name} ({existing['id']})")
            print("Use 'push' to update it, or 'cleanup' to delete and recreate.")
            return

        # Get production config
        prod = await find_assistant(client, headers, prod_name)
        if not prod:
            print(f"ERROR: Production assistant not found: {prod_name}")
            return

        print(f"Cloning {prod_name} → {stg_name}")

        # Build staging config (clone everything, change name)
        # Remove fields VAPI won't accept on create
        excluded_keys = {"id", "orgId", "createdAt", "updatedAt", "isServerUrlSecretSet"}
        staging_config = {k: v for k, v in prod.items() if k not in excluded_keys}
        staging_config["name"] = stg_name

        response = await client.post(
            f"{VAPI_BASE_URL}/assistant",
            headers=headers,
            json=staging_config
        )

        if response.status_code == 201:
            result = response.json()
            print(f"✓ Created staging assistant: {stg_name}")
            print(f"  ID: {result['id']}")
            print(f"  Model: {result.get('model', {}).get('model')}")
            print(f"\nNext: python scripts/staging.py push {assistant_key}")
        else:
            print(f"✗ Failed to create: {response.status_code}")
            print(response.text[:500])


async def cmd_push(assistant_key: str, summary: str = ""):
    """Push local code changes to staging assistant only"""
    prod_name = ASSISTANT_MAP[assistant_key]
    stg_name = staging_name(prod_name)

    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Find staging assistant
        staging = await find_assistant(client, headers, stg_name)
        if not staging:
            print(f"ERROR: No staging assistant found: {stg_name}")
            print(f"Create one first: python scripts/staging.py create {assistant_key}")
            return

        staging_id = staging["id"]

        # Get new config from code
        assistant_obj = get_assistant_class(assistant_key)
        new_prompt = assistant_obj.get_system_prompt()
        new_model_config = assistant_obj.get_model_config()
        new_first_message = assistant_obj.get_first_message()

        # Get current staging config to merge
        current = await get_assistant_by_id(client, headers, staging_id)
        if not current:
            print("ERROR: Could not fetch staging config")
            return

        # Build update: new prompt + model config, preserve tools/voice/etc
        current_model = current.get("model", {})
        updated_model = {
            **current_model,
            "provider": new_model_config.get("provider"),
            "model": new_model_config.get("model"),
            "temperature": new_model_config.get("temperature"),
            "messages": [{"role": "system", "content": new_prompt}],
        }
        if "maxTokens" in new_model_config:
            updated_model["maxTokens"] = new_model_config["maxTokens"]
        if "toolIds" in current_model:
            updated_model["toolIds"] = current_model["toolIds"]

        update_payload = {"model": updated_model}
        if new_first_message is not None:
            update_payload["firstMessage"] = new_first_message

        # Also push transcriber and speaking plan configs from code
        if hasattr(assistant_obj, 'get_transcriber_config'):
            update_payload["transcriber"] = assistant_obj.get_transcriber_config()
        if hasattr(assistant_obj, 'get_start_speaking_plan'):
            update_payload["startSpeakingPlan"] = assistant_obj.get_start_speaking_plan()
        if hasattr(assistant_obj, 'get_stop_speaking_plan'):
            update_payload["stopSpeakingPlan"] = assistant_obj.get_stop_speaking_plan()

        response = await client.patch(
            f"{VAPI_BASE_URL}/assistant/{staging_id}",
            headers=headers,
            json=update_payload
        )

        if response.status_code == 200:
            print(f"✓ Pushed to staging: {stg_name}")
            print(f"  Model: {new_model_config.get('model')}")
            print(f"  Temperature: {new_model_config.get('temperature')}")
            print(f"  Prompt length: {len(new_prompt)} chars")
            if summary:
                print(f"  Summary: {summary}")
            print(f"\nNext: python scripts/staging.py eval {assistant_key}")
        else:
            print(f"✗ Failed: {response.status_code}")
            print(response.text[:500])


async def cmd_eval(assistant_key: str):
    """Run evals against the staging assistant"""
    from scripts.vapi_evals.eval_definitions import GREETER_EVALS, TIMESHEET_EVALS, FLOW_EVALS, QR_EVALS

    prod_name = ASSISTANT_MAP[assistant_key]
    stg_name = staging_name(prod_name)

    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Find staging assistant
        staging = await find_assistant(client, headers, stg_name)
        if not staging:
            print(f"ERROR: No staging assistant found: {stg_name}")
            print(f"Create one first: python scripts/staging.py create {assistant_key}")
            return

        staging_id = staging["id"]

        # Also find production for comparison
        prod = await find_assistant(client, headers, prod_name)
        prod_id = prod["id"] if prod else None

        # Get eval definitions for this assistant type
        if assistant_key == "greeter":
            eval_defs = GREETER_EVALS
        elif assistant_key == "timesheet":
            eval_defs = TIMESHEET_EVALS + FLOW_EVALS + QR_EVALS
        else:
            print(f"No evals defined for {assistant_key}")
            return

        # Get existing evals from VAPI
        response = await client.get(f"{VAPI_BASE_URL}/eval", headers=headers)
        if response.status_code != 200:
            print(f"ERROR: Could not fetch evals: {response.status_code}")
            return

        eval_list = response.json().get("results", [])
        eval_map = {e.get("name"): e.get("id") for e in eval_list}

        # Build eval run list
        evals_to_run = []
        for eval_def in eval_defs:
            if eval_def["name"] in eval_map:
                evals_to_run.append({
                    "name": eval_def["name"],
                    "eval_id": eval_map[eval_def["name"]],
                })

        if not evals_to_run:
            print("No evals found in VAPI. Create them first:")
            print("  python scripts/vapi_evals/eval_runner.py create")
            return

        print(f"Running {len(evals_to_run)} evals against STAGING ({stg_name})")
        print(f"Staging ID: {staging_id}")
        print()

        results = []
        passed = 0
        failed = 0

        for eval_info in evals_to_run:
            print(f"  {eval_info['name']}...", end=" ", flush=True)

            # Run against staging
            response = await client.post(
                f"{VAPI_BASE_URL}/eval/run",
                headers=headers,
                json={
                    "type": "eval",
                    "evalId": eval_info["eval_id"],
                    "target": {
                        "type": "assistant",
                        "assistantId": staging_id
                    }
                }
            )

            if response.status_code != 201:
                print(f"ERROR ({response.status_code})")
                results.append({"name": eval_info["name"], "status": "error"})
                failed += 1
                continue

            run_data = response.json()
            run_id = run_data.get("evalRunId") or run_data.get("id")

            # Poll for completion
            final_status = "timeout"
            failure_reason = None
            for _ in range(30):
                await asyncio.sleep(2)
                status_resp = await client.get(
                    f"{VAPI_BASE_URL}/eval/run/{run_id}",
                    headers=headers
                )
                if status_resp.status_code != 200:
                    continue

                status_data = status_resp.json()
                if status_data.get("status") == "ended":
                    all_passed = True
                    for r in status_data.get("results", []):
                        if r.get("status") == "fail":
                            all_passed = False
                        for msg in r.get("messages", []):
                            judge = msg.get("judge", {})
                            if judge.get("status") == "fail":
                                all_passed = False
                                failure_reason = judge.get("failureReason", "")[:120]
                    final_status = "pass" if all_passed else "fail"
                    break

            if final_status == "pass":
                print("✓ PASS")
                passed += 1
            elif final_status == "fail":
                print("✗ FAIL")
                if failure_reason:
                    print(f"    → {failure_reason}")
                failed += 1
            else:
                print("? TIMEOUT")
                failed += 1

            results.append({
                "name": eval_info["name"],
                "status": final_status,
                "failure_reason": failure_reason,
            })

        # Summary
        total = len(results)
        rate = (passed / total * 100) if total > 0 else 0

        print()
        print("=" * 50)
        print(f"STAGING EVAL RESULTS: {passed}/{total} passed ({rate:.1f}%)")
        print("=" * 50)

        for r in results:
            icon = "✓" if r["status"] == "pass" else "✗"
            print(f"  {icon} {r['name']}")

        # Save results
        results_dir = os.path.join(os.path.dirname(__file__), "vapi_evals", "results")
        os.makedirs(results_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = os.path.join(results_dir, f"staging_{assistant_key}_{timestamp}.json")
        with open(results_file, "w") as f:
            json.dump({
                "timestamp": timestamp,
                "environment": "staging",
                "assistant": assistant_key,
                "staging_id": staging_id,
                "total": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": rate,
                "results": results,
            }, f, indent=2)

        print(f"\nResults saved: {results_file}")

        if rate >= 75:
            print(f"\n✓ Pass rate OK. To promote:")
            print(f"  python scripts/staging.py promote {assistant_key}")
        else:
            print(f"\n✗ Pass rate below 75%. Review failures before promoting.")


async def cmd_diff(assistant_key: str):
    """Show prompt diff between staging and production"""
    prod_name = ASSISTANT_MAP[assistant_key]
    stg_name = staging_name(prod_name)

    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        prod = await find_assistant(client, headers, prod_name)
        staging = await find_assistant(client, headers, stg_name)

        if not prod:
            print(f"ERROR: Production assistant not found: {prod_name}")
            return
        if not staging:
            print(f"ERROR: Staging assistant not found: {stg_name}")
            return

        # Get full configs
        prod_full = await get_assistant_by_id(client, headers, prod["id"])
        stg_full = await get_assistant_by_id(client, headers, staging["id"])

        prod_prompt = ""
        stg_prompt = ""

        for msg in prod_full.get("model", {}).get("messages", []):
            if msg.get("role") == "system":
                prod_prompt = msg.get("content", "")
        for msg in stg_full.get("model", {}).get("messages", []):
            if msg.get("role") == "system":
                stg_prompt = msg.get("content", "")

        # Model config diff
        prod_model = prod_full.get("model", {})
        stg_model = stg_full.get("model", {})

        print(f"{'='*60}")
        print(f"DIFF: {prod_name} (production) vs {stg_name} (staging)")
        print(f"{'='*60}")
        print()

        # Config comparison
        config_fields = ["model", "temperature", "maxTokens"]
        config_changed = False
        for field in config_fields:
            pv = prod_model.get(field)
            sv = stg_model.get(field)
            if pv != sv:
                print(f"  {field}: {pv} → {sv}")
                config_changed = True
        if not config_changed:
            print("  Model config: identical")
        print()

        # Prompt diff
        if prod_prompt == stg_prompt:
            print("  Prompt: identical")
        else:
            prod_lines = prod_prompt.splitlines(keepends=True)
            stg_lines = stg_prompt.splitlines(keepends=True)

            diff = difflib.unified_diff(
                prod_lines, stg_lines,
                fromfile="production",
                tofile="staging",
                lineterm=""
            )
            diff_text = "".join(diff)
            if diff_text:
                print("PROMPT DIFF:")
                print(diff_text)
            else:
                print("  Prompt: identical (whitespace differences only)")


async def cmd_promote(assistant_key: str):
    """Copy staging prompt/config → production"""
    prod_name = ASSISTANT_MAP[assistant_key]
    stg_name = staging_name(prod_name)

    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        prod = await find_assistant(client, headers, prod_name)
        staging = await find_assistant(client, headers, stg_name)

        if not prod:
            print(f"ERROR: Production assistant not found: {prod_name}")
            return
        if not staging:
            print(f"ERROR: Staging assistant not found: {stg_name}")
            return

        prod_id = prod["id"]
        staging_id = staging["id"]

        # Get full staging config
        stg_full = await get_assistant_by_id(client, headers, staging_id)
        if not stg_full:
            print("ERROR: Could not fetch staging config")
            return

        # Extract what we're promoting: model config (prompt + LLM settings)
        stg_model = stg_full.get("model", {})

        # Get production config to preserve toolIds and other fields
        prod_full = await get_assistant_by_id(client, headers, prod_id)
        prod_model = prod_full.get("model", {})

        # Merge: staging prompt/model settings, production toolIds
        promoted_model = {
            **stg_model,
        }
        if "toolIds" in prod_model:
            promoted_model["toolIds"] = prod_model["toolIds"]

        # Show what's changing
        print(f"PROMOTING: {stg_name} → {prod_name}")
        print()

        stg_prompt_len = 0
        for msg in stg_model.get("messages", []):
            if msg.get("role") == "system":
                stg_prompt_len = len(msg.get("content", ""))

        print(f"  Model: {stg_model.get('model')}")
        print(f"  Temperature: {stg_model.get('temperature')}")
        print(f"  Prompt length: {stg_prompt_len} chars")
        print()

        # Confirm
        confirm = input("Promote staging → production? (yes/no): ")
        if confirm.lower() != "yes":
            print("Cancelled.")
            return

        # Build promote payload: model + transcriber + speaking plans
        promote_payload = {"model": promoted_model}
        # Carry over transcriber and speaking plan if staging has them
        for field in ("transcriber", "startSpeakingPlan", "stopSpeakingPlan"):
            if field in stg_full:
                promote_payload[field] = stg_full[field]

        # Update production
        response = await client.patch(
            f"{VAPI_BASE_URL}/assistant/{prod_id}",
            headers=headers,
            json=promote_payload
        )

        if response.status_code == 200:
            print(f"\n✓ Production updated: {prod_name}")
            print(f"  ID: {prod_id}")

            # Record the change
            try:
                from scripts.record_prompt_change import record_prompt_change
                prompt_content = ""
                for msg in promoted_model.get("messages", []):
                    if msg.get("role") == "system":
                        prompt_content = msg.get("content", "")
                await record_prompt_change(
                    assistant_key=prod_name,
                    assistant_id=prod_id,
                    change_summary=f"Promoted from staging",
                    change_category="prompt",
                    prompt_content=prompt_content,
                )
                print("  ✓ Change recorded in learning loop")
            except Exception as e:
                print(f"  ⚠ Could not record change: {e}")

            print(f"\nNext: python scripts/staging.py cleanup {assistant_key}")
        else:
            print(f"✗ Failed: {response.status_code}")
            print(response.text[:500])


async def cmd_cleanup(assistant_key: str):
    """Delete the staging assistant"""
    prod_name = ASSISTANT_MAP[assistant_key]
    stg_name = staging_name(prod_name)

    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        staging = await find_assistant(client, headers, stg_name)
        if not staging:
            print(f"No staging assistant found: {stg_name}")
            return

        staging_id = staging["id"]

        confirm = input(f"Delete staging assistant {stg_name} ({staging_id})? (yes/no): ")
        if confirm.lower() != "yes":
            print("Cancelled.")
            return

        response = await client.delete(
            f"{VAPI_BASE_URL}/assistant/{staging_id}",
            headers=headers
        )

        if response.status_code == 200:
            print(f"✓ Deleted: {stg_name}")
        else:
            print(f"✗ Failed: {response.status_code}")
            print(response.text[:200])


async def cmd_status():
    """Show all staging assistants"""
    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{VAPI_BASE_URL}/assistant", headers=headers)
        if response.status_code != 200:
            print(f"ERROR: {response.status_code}")
            return

        assistants = response.json()

        staging_found = []
        prod_found = []
        for a in assistants:
            name = a.get("name", "")
            if name.endswith(STAGING_SUFFIX):
                staging_found.append(a)
            elif name in ASSISTANT_MAP.values():
                prod_found.append(a)

        print(f"{'='*60}")
        print("VAPI ASSISTANT STATUS")
        print(f"{'='*60}")
        print()

        print("PRODUCTION:")
        for a in sorted(prod_found, key=lambda x: x["name"]):
            model = a.get("model", {}).get("model", "?")
            temp = a.get("model", {}).get("temperature", "?")
            print(f"  ✓ {a['name']}")
            print(f"    ID: {a['id']} | Model: {model} | Temp: {temp}")
        print()

        if staging_found:
            print("STAGING:")
            for a in sorted(staging_found, key=lambda x: x["name"]):
                model = a.get("model", {}).get("model", "?")
                temp = a.get("model", {}).get("temperature", "?")
                created = a.get("createdAt", "")[:10]
                print(f"  ⚡ {a['name']}")
                print(f"    ID: {a['id']} | Model: {model} | Temp: {temp} | Created: {created}")
        else:
            print("STAGING: none")

        print()


async def cmd_create_squad():
    """Create a full staging squad with cloned assistants and assign test phone number"""
    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Check if staging squad already exists
        response = await client.get(f"{VAPI_BASE_URL}/squad", headers=headers)
        for s in response.json():
            if s.get("name") == STAGING_SQUAD_NAME:
                print(f"Staging squad already exists: {STAGING_SQUAD_NAME} ({s['id']})")
                print("Use 'teardown-squad' first if you want to recreate it.")
                return

        # Step 1: Clone all production assistants → staging
        print("Step 1: Cloning production assistants...")
        staging_ids = {}

        for key, prod_name in ASSISTANT_MAP.items():
            stg_name = staging_name(prod_name)

            # Check if staging already exists
            existing = await find_assistant(client, headers, stg_name)
            if existing:
                print(f"  ✓ {stg_name} already exists ({existing['id']})")
                staging_ids[key] = existing["id"]
                continue

            # Get production config
            prod = await find_assistant(client, headers, prod_name)
            if not prod:
                print(f"  ✗ Production assistant not found: {prod_name}")
                continue

            # Clone it
            excluded_keys = {"id", "orgId", "createdAt", "updatedAt", "isServerUrlSecretSet"}
            staging_config = {k: v for k, v in prod.items() if k not in excluded_keys}
            staging_config["name"] = stg_name

            resp = await client.post(
                f"{VAPI_BASE_URL}/assistant",
                headers=headers,
                json=staging_config
            )

            if resp.status_code == 201:
                result = resp.json()
                staging_ids[key] = result["id"]
                print(f"  ✓ Created {stg_name} ({result['id']})")
            else:
                print(f"  ✗ Failed to create {stg_name}: {resp.status_code}")
                print(f"    {resp.text[:200]}")

        if len(staging_ids) != len(ASSISTANT_MAP):
            print("\n✗ Not all assistants were cloned. Fix errors above and retry.")
            return

        # Step 2: Create staging squad
        print("\nStep 2: Creating staging squad...")

        # Build member list — greeter routes to staging assistant names
        greeter_destinations = []
        for key, prod_name in ASSISTANT_MAP.items():
            if key == "greeter":
                continue
            greeter_destinations.append({
                "message": "",
                "type": "assistant",
                "assistantName": staging_name(prod_name),
            })

        members = [
            {
                "assistantId": staging_ids["greeter"],
                "assistantDestinations": greeter_destinations,
            }
        ]
        for key in ["voice_notes", "site_progress", "timesheet"]:
            members.append({
                "assistantId": staging_ids[key],
                "assistantDestinations": [],
            })

        squad_resp = await client.post(
            f"{VAPI_BASE_URL}/squad",
            headers=headers,
            json={
                "name": STAGING_SQUAD_NAME,
                "members": members,
            }
        )

        if squad_resp.status_code != 201:
            print(f"  ✗ Failed to create squad: {squad_resp.status_code}")
            print(f"    {squad_resp.text[:300]}")
            return

        staging_squad_id = squad_resp.json()["id"]
        print(f"  ✓ Created staging squad ({staging_squad_id})")

        # Step 3: Point JOURN3Y phone number to staging squad
        print("\nStep 3: Assigning JOURN3Y phone to staging squad...")

        phone_resp = await client.patch(
            f"{VAPI_BASE_URL}/phone-number/{TEST_PHONE_NUMBER_ID}",
            headers=headers,
            json={
                "squadId": staging_squad_id,
                "assistantId": None,
            }
        )

        if phone_resp.status_code == 200:
            phone_data = phone_resp.json()
            print(f"  ✓ Phone {phone_data.get('number')} → staging squad")
        else:
            print(f"  ✗ Failed to reassign phone: {phone_resp.status_code}")
            print(f"    {phone_resp.text[:200]}")

        # Summary
        print()
        print("=" * 60)
        print("STAGING SQUAD READY")
        print("=" * 60)
        print(f"  Squad: {STAGING_SQUAD_NAME} ({staging_squad_id})")
        for key, sid in staging_ids.items():
            print(f"  {key}: {sid}")
        print()
        print(f"  Call +61468086094 to test the staging squad.")
        print(f"  Use 'push' to update individual assistants.")
        print(f"  Use 'eval' to run evals against staging.")
        print()
        print("  When done: python scripts/staging.py teardown-squad")


async def cmd_teardown_squad():
    """Delete staging squad, all staging assistants, point phone back to production"""
    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Find staging squad
        response = await client.get(f"{VAPI_BASE_URL}/squad", headers=headers)
        staging_squad = None
        for s in response.json():
            if s.get("name") == STAGING_SQUAD_NAME:
                staging_squad = s
                break

        if not staging_squad:
            print("No staging squad found.")
            # Still check for orphaned staging assistants
        else:
            print(f"Found staging squad: {staging_squad['id']}")

        # Step 1: Point phone back to production
        print("\nStep 1: Restoring phone to production squad...")
        phone_resp = await client.patch(
            f"{VAPI_BASE_URL}/phone-number/{TEST_PHONE_NUMBER_ID}",
            headers=headers,
            json={
                "squadId": PROD_SQUAD_ID,
                "assistantId": None,
            }
        )

        if phone_resp.status_code == 200:
            print(f"  ✓ Phone → production squad ({PROD_SQUAD_ID})")
        else:
            print(f"  ✗ Failed: {phone_resp.status_code}")

        # Step 2: Delete staging squad
        if staging_squad:
            print("\nStep 2: Deleting staging squad...")
            del_resp = await client.delete(
                f"{VAPI_BASE_URL}/squad/{staging_squad['id']}",
                headers=headers
            )
            if del_resp.status_code == 200:
                print(f"  ✓ Deleted squad {STAGING_SQUAD_NAME}")
            else:
                print(f"  ✗ Failed: {del_resp.status_code}")

        # Step 3: Delete staging assistants
        print("\nStep 3: Cleaning up staging assistants...")
        for key, prod_name in ASSISTANT_MAP.items():
            stg_name = staging_name(prod_name)
            staging = await find_assistant(client, headers, stg_name)
            if staging:
                del_resp = await client.delete(
                    f"{VAPI_BASE_URL}/assistant/{staging['id']}",
                    headers=headers
                )
                if del_resp.status_code == 200:
                    print(f"  ✓ Deleted {stg_name}")
                else:
                    print(f"  ✗ Failed to delete {stg_name}: {del_resp.status_code}")
            else:
                print(f"  - {stg_name} not found (already cleaned)")

        print()
        print("=" * 60)
        print("STAGING SQUAD TORN DOWN")
        print("=" * 60)
        print(f"  Phone restored to production squad.")
        print(f"  All staging assistants deleted.")


async def main():
    parser = argparse.ArgumentParser(
        description="VAPI Assistant Staging Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  1. staging.py create timesheet     # Clone prod → staging
  2. (edit prompt in code)
  3. staging.py push timesheet       # Push code → staging
  4. staging.py eval timesheet       # Run evals against staging
  5. staging.py diff timesheet       # Review changes
  6. staging.py promote timesheet    # Push staging → prod
  7. staging.py cleanup timesheet    # Delete staging copy
        """
    )

    parser.add_argument(
        "command",
        choices=["create", "push", "eval", "diff", "promote", "cleanup", "status",
                 "create-squad", "teardown-squad"],
        help="Action to perform"
    )
    parser.add_argument(
        "assistant",
        nargs="?",
        default="timesheet",
        choices=list(ASSISTANT_MAP.keys()),
        help="Assistant to operate on (default: timesheet)"
    )
    parser.add_argument(
        "--summary", "-s",
        default="",
        help="Change summary (for push command)"
    )

    args = parser.parse_args()

    if not VAPI_API_KEY:
        print("ERROR: VAPI_API_KEY not found in environment")
        sys.exit(1)

    if args.command == "create":
        await cmd_create(args.assistant)
    elif args.command == "push":
        await cmd_push(args.assistant, args.summary)
    elif args.command == "eval":
        await cmd_eval(args.assistant)
    elif args.command == "diff":
        await cmd_diff(args.assistant)
    elif args.command == "promote":
        await cmd_promote(args.assistant)
    elif args.command == "cleanup":
        await cmd_cleanup(args.assistant)
    elif args.command == "status":
        await cmd_status()
    elif args.command == "create-squad":
        await cmd_create_squad()
    elif args.command == "teardown-squad":
        await cmd_teardown_squad()


if __name__ == "__main__":
    asyncio.run(main())
