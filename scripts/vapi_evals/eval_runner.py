#!/usr/bin/env python3
"""
VAPI Eval Runner

Creates and runs evals to test Jill assistants for phonetic variant handling.

Usage:
    python scripts/vapi_evals/eval_runner.py list          # List existing evals
    python scripts/vapi_evals/eval_runner.py create        # Create all evals in VAPI
    python scripts/vapi_evals/eval_runner.py run           # Run all evals
    python scripts/vapi_evals/eval_runner.py run --name X  # Run specific eval
    python scripts/vapi_evals/eval_runner.py results       # View recent results
    python scripts/vapi_evals/eval_runner.py delete        # Delete all evals (cleanup)
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()

from scripts.vapi_evals.eval_definitions import ALL_EVALS, GREETER_EVALS, TIMESHEET_EVALS, FLOW_EVALS

VAPI_API_KEY = os.getenv("VAPI_API_KEY")
VAPI_BASE_URL = "https://api.vapi.ai"

# Assistant IDs - these need to match your VAPI setup
GREETER_ASSISTANT_NAME = "JSMB-Jill-authenticate-and-greet"
TIMESHEET_ASSISTANT_NAME = "JSMB-Jill-timesheet"


class VAPIEvalsRunner:
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {VAPI_API_KEY}",
            "Content-Type": "application/json"
        }
        self.assistant_ids: Dict[str, str] = {}
        self.eval_ids: Dict[str, str] = {}  # name -> eval_id mapping

    async def get_assistants(self) -> Dict[str, str]:
        """Fetch assistant IDs by name"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{VAPI_BASE_URL}/assistant",
                headers=self.headers
            )
            assistants = response.json()

            for a in assistants:
                name = a.get("name", "")
                if name == GREETER_ASSISTANT_NAME:
                    self.assistant_ids["greeter"] = a["id"]
                elif name == TIMESHEET_ASSISTANT_NAME:
                    self.assistant_ids["timesheet"] = a["id"]

            return self.assistant_ids

    async def list_evals(self) -> List[Dict]:
        """List all existing evals"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{VAPI_BASE_URL}/eval",
                headers=self.headers
            )
            if response.status_code == 200:
                data = response.json()
                # Response is paginated: {"results": [...], "metadata": {...}}
                return data.get("results", [])
            else:
                print(f"Error listing evals: {response.status_code}")
                return []

    async def create_eval(self, eval_def: Dict, assistant_type: str) -> Optional[str]:
        """Create a single eval in VAPI"""
        assistant_id = self.assistant_ids.get(assistant_type)
        if not assistant_id:
            print(f"  ✗ No assistant ID for {assistant_type}")
            return None

        payload = {
            "name": eval_def["name"],
            "type": "chat.mockConversation",
            "messages": eval_def["messages"]
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{VAPI_BASE_URL}/eval",
                headers=self.headers,
                json=payload
            )

            if response.status_code == 201:
                result = response.json()
                eval_id = result.get("id")
                print(f"  ✓ Created: {eval_def['name']} ({eval_id})")
                return eval_id
            else:
                print(f"  ✗ Failed to create {eval_def['name']}: {response.status_code}")
                print(f"    {response.text[:200]}")
                return None

    async def create_all_evals(self):
        """Create all eval definitions in VAPI"""
        print("\n" + "=" * 60)
        print("CREATING VAPI EVALS")
        print("=" * 60)

        # Get assistant IDs first
        await self.get_assistants()
        print(f"\nFound assistants:")
        print(f"  Greeter: {self.assistant_ids.get('greeter', 'NOT FOUND')}")
        print(f"  Timesheet: {self.assistant_ids.get('timesheet', 'NOT FOUND')}")

        if not self.assistant_ids.get("greeter") or not self.assistant_ids.get("timesheet"):
            print("\n✗ Could not find required assistants. Aborting.")
            return

        # Check for existing evals
        existing = await self.list_evals()
        existing_names = {e.get("name") for e in existing}

        # Create greeter evals
        print(f"\nCreating Greeter evals ({len(GREETER_EVALS)} tests):")
        for eval_def in GREETER_EVALS:
            if eval_def["name"] in existing_names:
                print(f"  - Skipping {eval_def['name']} (already exists)")
                continue
            eval_id = await self.create_eval(eval_def, "greeter")
            if eval_id:
                self.eval_ids[eval_def["name"]] = eval_id

        # Create timesheet evals
        print(f"\nCreating Timesheet evals ({len(TIMESHEET_EVALS)} tests):")
        for eval_def in TIMESHEET_EVALS:
            if eval_def["name"] in existing_names:
                print(f"  - Skipping {eval_def['name']} (already exists)")
                continue
            eval_id = await self.create_eval(eval_def, "timesheet")
            if eval_id:
                self.eval_ids[eval_def["name"]] = eval_id

        # Create flow evals (run against timesheet assistant)
        print(f"\nCreating Flow evals ({len(FLOW_EVALS)} tests):")
        for eval_def in FLOW_EVALS:
            if eval_def["name"] in existing_names:
                print(f"  - Skipping {eval_def['name']} (already exists)")
                continue
            eval_id = await self.create_eval(eval_def, "timesheet")
            if eval_id:
                self.eval_ids[eval_def["name"]] = eval_id

        print(f"\n✓ Created {len(self.eval_ids)} new evals")

    async def run_eval(self, eval_id: str, eval_name: str, assistant_id: str) -> Dict:
        """Run a single eval and return results"""
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Start the eval run
            response = await client.post(
                f"{VAPI_BASE_URL}/eval/run",
                headers=self.headers,
                json={
                    "type": "eval",
                    "evalId": eval_id,
                    "target": {
                        "type": "assistant",
                        "assistantId": assistant_id
                    }
                }
            )

            if response.status_code != 201:
                return {
                    "name": eval_name,
                    "status": "error",
                    "error": f"Failed to start: {response.status_code}"
                }

            run_data = response.json()
            run_id = run_data.get("evalRunId") or run_data.get("id")

            # Poll for completion
            max_attempts = 30
            for attempt in range(max_attempts):
                await asyncio.sleep(2)

                status_response = await client.get(
                    f"{VAPI_BASE_URL}/eval/run/{run_id}",
                    headers=self.headers
                )

                if status_response.status_code != 200:
                    continue

                status_data = status_response.json()
                status = status_data.get("status")

                if status == "ended":
                    # Extract results
                    results = status_data.get("results", [])

                    # Check pass/fail: each result has a status field,
                    # AND judge verdicts are nested inside messages
                    all_passed = True
                    for r in results:
                        # Check top-level result status
                        if r.get("status") == "fail":
                            all_passed = False
                            break
                        # Also check nested judge in messages
                        for msg in r.get("messages", []):
                            judge = msg.get("judge", {})
                            if judge.get("status") == "fail":
                                all_passed = False
                                break
                        if not all_passed:
                            break

                    return {
                        "name": eval_name,
                        "status": "pass" if all_passed else "fail",
                        "run_id": run_id,
                        "results": results,
                        "ended_reason": status_data.get("endedReason")
                    }

            return {
                "name": eval_name,
                "status": "timeout",
                "run_id": run_id
            }

    async def run_all_evals(self, filter_name: Optional[str] = None):
        """Run all evals and report results"""
        print("\n" + "=" * 60)
        print("RUNNING VAPI EVALS")
        print("=" * 60)

        # Get assistant IDs
        await self.get_assistants()

        # Get existing evals
        existing = await self.list_evals()
        eval_map = {e.get("name"): e.get("id") for e in existing}

        results = []
        passed = 0
        failed = 0

        # Determine which evals to run
        evals_to_run = []

        for eval_def in GREETER_EVALS:
            if filter_name and filter_name not in eval_def["name"]:
                continue
            if eval_def["name"] in eval_map:
                evals_to_run.append({
                    "name": eval_def["name"],
                    "eval_id": eval_map[eval_def["name"]],
                    "assistant_id": self.assistant_ids.get("greeter"),
                    "type": "greeter"
                })

        for eval_def in TIMESHEET_EVALS:
            if filter_name and filter_name not in eval_def["name"]:
                continue
            if eval_def["name"] in eval_map:
                evals_to_run.append({
                    "name": eval_def["name"],
                    "eval_id": eval_map[eval_def["name"]],
                    "assistant_id": self.assistant_ids.get("timesheet"),
                    "type": "timesheet"
                })

        for eval_def in FLOW_EVALS:
            if filter_name and filter_name not in eval_def["name"]:
                continue
            if eval_def["name"] in eval_map:
                evals_to_run.append({
                    "name": eval_def["name"],
                    "eval_id": eval_map[eval_def["name"]],
                    "assistant_id": self.assistant_ids.get("timesheet"),
                    "type": "flow"
                })

        if not evals_to_run:
            print("\n✗ No evals found to run. Create them first with 'create' command.")
            return

        print(f"\nRunning {len(evals_to_run)} evals...\n")

        for eval_info in evals_to_run:
            print(f"Running: {eval_info['name']}...", end=" ", flush=True)

            result = await self.run_eval(
                eval_info["eval_id"],
                eval_info["name"],
                eval_info["assistant_id"]
            )

            results.append(result)

            if result["status"] == "pass":
                print("✓ PASS")
                passed += 1
            elif result["status"] == "fail":
                print("✗ FAIL")
                failed += 1
                # Show failure details from nested messages
                for r in result.get("results", []):
                    for msg in r.get("messages", []):
                        judge = msg.get("judge", {})
                        if judge.get("status") == "fail":
                            print(f"    Reason: {judge.get('failureReason', 'Unknown')[:100]}")
            else:
                print(f"? {result['status'].upper()}")
                failed += 1

        # Summary
        print("\n" + "=" * 60)
        print("RESULTS SUMMARY")
        print("=" * 60)
        print(f"\n  Total:  {len(results)}")
        print(f"  Passed: {passed} ✓")
        print(f"  Failed: {failed} ✗")
        print(f"  Rate:   {(passed/len(results)*100):.1f}%")

        # Save results
        results_dir = os.path.join(os.path.dirname(__file__), "results")
        os.makedirs(results_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = os.path.join(results_dir, f"eval_results_{timestamp}.json")

        with open(results_file, "w") as f:
            json.dump({
                "timestamp": timestamp,
                "total": len(results),
                "passed": passed,
                "failed": failed,
                "results": results
            }, f, indent=2)

        print(f"\n  Results saved to: {results_file}")

    async def show_results(self):
        """Show recent eval run results"""
        results_dir = os.path.join(os.path.dirname(__file__), "results")

        if not os.path.exists(results_dir):
            print("No results found. Run evals first.")
            return

        files = sorted(os.listdir(results_dir), reverse=True)
        if not files:
            print("No results found. Run evals first.")
            return

        # Show most recent
        latest = files[0]
        with open(os.path.join(results_dir, latest)) as f:
            data = json.load(f)

        print(f"\n" + "=" * 60)
        print(f"EVAL RESULTS - {data['timestamp']}")
        print("=" * 60)

        print(f"\nSummary: {data['passed']}/{data['total']} passed ({data['passed']/data['total']*100:.1f}%)\n")

        for result in data["results"]:
            status_icon = "✓" if result["status"] == "pass" else "✗"
            print(f"  {status_icon} {result['name']}")

    async def delete_all_evals(self):
        """Delete all evals (for cleanup)"""
        print("\n" + "=" * 60)
        print("DELETING ALL EVALS")
        print("=" * 60)

        existing = await self.list_evals()

        if not existing:
            print("\nNo evals to delete.")
            return

        print(f"\nDeleting {len(existing)} evals...")

        async with httpx.AsyncClient(timeout=30.0) as client:
            for eval_item in existing:
                eval_id = eval_item.get("id")
                eval_name = eval_item.get("name")

                response = await client.delete(
                    f"{VAPI_BASE_URL}/eval/{eval_id}",
                    headers=self.headers
                )

                if response.status_code == 200:
                    print(f"  ✓ Deleted: {eval_name}")
                else:
                    print(f"  ✗ Failed to delete: {eval_name}")

        print("\n✓ Cleanup complete")


async def main():
    parser = argparse.ArgumentParser(description="VAPI Eval Runner")
    parser.add_argument("command", choices=["list", "create", "run", "results", "delete"],
                        help="Command to execute")
    parser.add_argument("--name", help="Filter evals by name (for run command)")

    args = parser.parse_args()

    runner = VAPIEvalsRunner()

    if args.command == "list":
        evals = await runner.list_evals()
        print(f"\nFound {len(evals)} evals:")
        for e in evals:
            print(f"  - {e.get('name')} ({e.get('id')})")

    elif args.command == "create":
        await runner.create_all_evals()

    elif args.command == "run":
        await runner.run_all_evals(filter_name=args.name)

    elif args.command == "results":
        await runner.show_results()

    elif args.command == "delete":
        confirm = input("Are you sure you want to delete all evals? (yes/no): ")
        if confirm.lower() == "yes":
            await runner.delete_all_evals()
        else:
            print("Cancelled.")


if __name__ == "__main__":
    asyncio.run(main())
