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
    from scripts.vapi_evals.eval_definitions import GREETER_EVALS, TIMESHEET_EVALS, FLOW_EVALS

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
            eval_defs = TIMESHEET_EVALS + FLOW_EVALS
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

        # Update production
        response = await client.patch(
            f"{VAPI_BASE_URL}/assistant/{prod_id}",
            headers=headers,
            json={"model": promoted_model}
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
        choices=["create", "push", "eval", "diff", "promote", "cleanup", "status"],
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


if __name__ == "__main__":
    asyncio.run(main())
