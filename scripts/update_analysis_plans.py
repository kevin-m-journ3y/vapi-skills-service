"""
Update VAPI Assistants with Analysis Plans

Configures analysisPlan on each assistant to automatically score every call
for quality, naturalness, and task completion.

Usage:
    python scripts/update_analysis_plans.py          # Update all assistants
    python scripts/update_analysis_plans.py --dry-run # Preview without updating
"""

import asyncio
import argparse
import os
import sys
import json
import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from scripts.record_prompt_change import record_prompt_change

VAPI_API_KEY = os.getenv("VAPI_API_KEY")

# Assistant IDs in the squad
ASSISTANTS = {
    "JSMB-Jill-authenticate-and-greet": "4300f282-35d2-4a06-9a67-f5b6d45e167f",
    "JSMB-Jill-timesheet": "d3a5e1cf-82cb-4f6e-a406-b0170ede3d10",
    "JSMB-Jill-voice-notes": "8a6f3781-5320-46bb-ad68-6451ee553e81",
    "JSMB-Jill-site-progress": "a88bdc5e-0ed4-410b-9e5a-b136072b22d7",
}

# =====================================================
# ANALYSIS PLAN DEFINITIONS
# =====================================================

GREETER_ANALYSIS_PLAN = {
    "summaryPrompt": (
        "Summarise this call routing interaction in 1-2 sentences. "
        "Include: who called, what skill they were routed to, "
        "and whether routing was successful."
    ),
    "successEvaluationPrompt": (
        "Evaluate whether this greeter call was successful.\n\n"
        "SUCCESS criteria (ALL must be met):\n"
        "1. The caller was authenticated (authenticate_caller returned authorized=true)\n"
        "2. The assistant greeted the user by their first name\n"
        "3. The assistant correctly identified the user's intent (timesheet, voice note, site update)\n"
        "4. The assistant transferred to the correct specialist assistant\n\n"
        "FAILURE criteria (ANY triggers failure):\n"
        "- The caller was not authenticated and the call continued anyway\n"
        "- The assistant asked 'did you mean X?' instead of interpreting phonetic variants\n"
        "- The assistant failed to transfer to the specialist assistant\n"
        "- The assistant tried to handle the skill itself instead of transferring\n"
    ),
    "successEvaluationRubric": "PassFail",
    "structuredDataPrompt": (
        "Extract the following quality signals from this greeter call transcript.\n"
        "Analyse the assistant's behavior carefully.\n\n"
        "- task_completed: Was the caller successfully routed to the right assistant?\n"
        "- repeated_questions: Did the assistant ask the same question more than once?\n"
        "- filler_phrases_used: Did the assistant say 'hold on', 'one moment', 'give me a sec', "
        "'let me check', 'just a moment', or similar waiting/filler phrases?\n"
        "- user_had_to_repeat: Did the user have to say the same thing twice because the assistant didn't understand?\n"
        "- user_sentiment: Based on the user's tone and words, are they positive, neutral, frustrated, or confused?\n"
        "- naturalness_score: Rate 1-5 how natural the conversation felt. "
        "5 = perfectly natural human-like exchange. "
        "4 = mostly natural with minor oddities. "
        "3 = acceptable but clearly AI. "
        "2 = awkward or robotic. "
        "1 = broken or confusing.\n"
        "- improvement_notes: Specific suggestions for how this interaction could have been better. "
        "If it was perfect, say 'None'."
    ),
    "structuredDataSchema": {
        "type": "object",
        "properties": {
            "task_completed": {"type": "boolean", "description": "Was the caller routed successfully?"},
            "repeated_questions": {"type": "boolean", "description": "Did the assistant repeat any question?"},
            "filler_phrases_used": {"type": "boolean", "description": "Did the assistant use filler/waiting phrases?"},
            "user_had_to_repeat": {"type": "boolean", "description": "Did the user have to repeat themselves?"},
            "user_sentiment": {"type": "string", "enum": ["positive", "neutral", "frustrated", "confused"]},
            "naturalness_score": {"type": "integer", "description": "1-5 naturalness rating"},
            "improvement_notes": {"type": "string", "description": "Specific improvement suggestions"}
        }
    }
}

TIMESHEET_ANALYSIS_PLAN = {
    "summaryPrompt": (
        "Summarise this timesheet logging call in 2-3 sentences. "
        "Include: user name, site(s) logged, total hours, "
        "and whether the entry was saved successfully."
    ),
    "successEvaluationPrompt": (
        "Evaluate whether this timesheet call was successful.\n\n"
        "SUCCESS criteria (ALL must be met):\n"
        "1. At least one timesheet entry was saved (save_timesheet_entry tool returned success=true)\n"
        "2. All required fields were collected: site, start time, end time, work description\n"
        "3. The hours calculated are reasonable (not negative, not over 24)\n\n"
        "PARTIAL SUCCESS:\n"
        "- Data was saved but the assistant repeated questions or used filler phrases\n"
        "- Data was saved but flow steps were skipped (e.g. no confirmation readback)\n\n"
        "FAILURE criteria (ANY triggers failure):\n"
        "- No timesheet entry was saved\n"
        "- The user hung up before completing the flow\n"
        "- The assistant could not identify the site\n"
        "- Required fields were missing from the saved entry\n"
    ),
    "successEvaluationRubric": "PassFail",
    "structuredDataPrompt": (
        "Extract the following quality signals from this timesheet call transcript.\n"
        "Analyse the assistant's behavior carefully.\n\n"
        "- task_completed: Was at least one timesheet entry saved successfully?\n"
        "- sites_logged: How many different sites were timesheet entries saved for? (integer)\n"
        "- repeated_questions: Did the assistant ask the SAME question more than once? "
        "(e.g. asking 'what time did you finish?' twice in a row)\n"
        "- filler_phrases_used: Did the assistant say 'hold on', 'one moment', 'give me a sec', "
        "'this will just take a sec', 'let me check', 'just a moment', or similar waiting phrases? "
        "The assistant should stay SILENT while tools process.\n"
        "- user_had_to_repeat: Did the user have to say the same information twice "
        "because the assistant didn't hear or process it the first time?\n"
        "- user_sentiment: Based on the user's tone and words throughout the call. "
        "positive = friendly, satisfied. neutral = matter-of-fact. "
        "frustrated = annoyed or impatient. confused = uncertain what to do.\n"
        "- naturalness_score: Rate 1-5 how natural the conversation felt. "
        "5 = perfectly natural, like talking to a helpful colleague. "
        "4 = mostly natural with minor oddities. "
        "3 = acceptable but clearly talking to an AI. "
        "2 = awkward, robotic, or stilted. "
        "1 = broken, confusing, or painful.\n"
        "- flow_steps_skipped: List any of these steps that were SKIPPED: "
        "'check_more_sites' (should ask 'did you work anywhere else?'), "
        "'confirmation_readback' (should read back all entries before final save), "
        "'work_description' (should ask what they worked on), "
        "'escalation_check' (should ask if anything needs escalating). "
        "Return an empty array if all steps were followed.\n"
        "- improvement_notes: Specific, actionable suggestions for improving this interaction. "
        "Focus on naturalness, efficiency, and user experience. If it was perfect, say 'None'."
    ),
    "structuredDataSchema": {
        "type": "object",
        "properties": {
            "task_completed": {"type": "boolean", "description": "Was a timesheet entry saved?"},
            "sites_logged": {"type": "integer", "description": "Number of sites logged"},
            "repeated_questions": {"type": "boolean", "description": "Did the assistant repeat any question?"},
            "filler_phrases_used": {"type": "boolean", "description": "Did the assistant use filler/waiting phrases?"},
            "user_had_to_repeat": {"type": "boolean", "description": "Did the user have to repeat info?"},
            "user_sentiment": {"type": "string", "enum": ["positive", "neutral", "frustrated", "confused"]},
            "naturalness_score": {"type": "integer", "description": "1-5 naturalness rating"},
            "flow_steps_skipped": {"type": "array", "items": {"type": "string"}, "description": "Steps that were skipped"},
            "improvement_notes": {"type": "string", "description": "Specific improvement suggestions"}
        }
    }
}

VOICE_NOTES_ANALYSIS_PLAN = {
    "summaryPrompt": (
        "Summarise this voice note call in 1-2 sentences. "
        "Include: user name, what the note was about, and whether it was saved."
    ),
    "successEvaluationPrompt": (
        "Evaluate whether this voice note call was successful.\n\n"
        "SUCCESS: The voice note was captured and saved.\n"
        "FAILURE: The user hung up before the note was saved, or the note failed to save.\n"
    ),
    "successEvaluationRubric": "PassFail",
    "structuredDataPrompt": (
        "Extract quality signals from this voice note call:\n"
        "- task_completed: Was the voice note saved?\n"
        "- repeated_questions: Did the assistant repeat any question?\n"
        "- filler_phrases_used: Did the assistant use waiting/filler phrases?\n"
        "- user_had_to_repeat: Did the user have to repeat themselves?\n"
        "- user_sentiment: positive, neutral, frustrated, or confused\n"
        "- naturalness_score: 1-5 naturalness rating\n"
        "- improvement_notes: Specific suggestions or 'None'\n"
    ),
    "structuredDataSchema": {
        "type": "object",
        "properties": {
            "task_completed": {"type": "boolean"},
            "repeated_questions": {"type": "boolean"},
            "filler_phrases_used": {"type": "boolean"},
            "user_had_to_repeat": {"type": "boolean"},
            "user_sentiment": {"type": "string", "enum": ["positive", "neutral", "frustrated", "confused"]},
            "naturalness_score": {"type": "integer"},
            "improvement_notes": {"type": "string"}
        }
    }
}

SITE_PROGRESS_ANALYSIS_PLAN = {
    "summaryPrompt": (
        "Summarise this site progress update call in 1-2 sentences. "
        "Include: user name, site, update type, and whether it was saved."
    ),
    "successEvaluationPrompt": (
        "Evaluate whether this site update call was successful.\n\n"
        "SUCCESS: A site update was captured and saved.\n"
        "FAILURE: The user hung up before the update was saved, or it failed.\n"
    ),
    "successEvaluationRubric": "PassFail",
    "structuredDataPrompt": (
        "Extract quality signals from this site update call:\n"
        "- task_completed: Was the site update saved?\n"
        "- repeated_questions: Did the assistant repeat any question?\n"
        "- filler_phrases_used: Did the assistant use waiting/filler phrases?\n"
        "- user_had_to_repeat: Did the user have to repeat themselves?\n"
        "- user_sentiment: positive, neutral, frustrated, or confused\n"
        "- naturalness_score: 1-5 naturalness rating\n"
        "- improvement_notes: Specific suggestions or 'None'\n"
    ),
    "structuredDataSchema": {
        "type": "object",
        "properties": {
            "task_completed": {"type": "boolean"},
            "repeated_questions": {"type": "boolean"},
            "filler_phrases_used": {"type": "boolean"},
            "user_had_to_repeat": {"type": "boolean"},
            "user_sentiment": {"type": "string", "enum": ["positive", "neutral", "frustrated", "confused"]},
            "naturalness_score": {"type": "integer"},
            "improvement_notes": {"type": "string"}
        }
    }
}

ANALYSIS_PLANS = {
    "JSMB-Jill-authenticate-and-greet": GREETER_ANALYSIS_PLAN,
    "JSMB-Jill-timesheet": TIMESHEET_ANALYSIS_PLAN,
    "JSMB-Jill-voice-notes": VOICE_NOTES_ANALYSIS_PLAN,
    "JSMB-Jill-site-progress": SITE_PROGRESS_ANALYSIS_PLAN,
}


async def main():
    parser = argparse.ArgumentParser(description="Update VAPI analysis plans")
    parser.add_argument("--dry-run", action="store_true", help="Preview without updating")
    parser.add_argument("--summary", default="Analysis plan updated", help="Description of what changed")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("UPDATING VAPI ASSISTANT ANALYSIS PLANS")
    print("=" * 60)
    print()

    if args.dry_run:
        print("DRY RUN - no changes will be made")
        print()

    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        for name, assistant_id in ASSISTANTS.items():
            plan = ANALYSIS_PLANS.get(name)
            if not plan:
                print(f"  SKIP: No analysis plan defined for {name}")
                continue

            print(f"  {name} ({assistant_id})")

            if args.dry_run:
                print(f"    Would set analysisPlan with:")
                print(f"      summaryPrompt: {plan['summaryPrompt'][:60]}...")
                print(f"      successEvaluationRubric: {plan['successEvaluationRubric']}")
                schema_fields = list(plan['structuredDataSchema']['properties'].keys())
                print(f"      structuredData fields: {schema_fields}")
                print()
                continue

            update_payload = {"analysisPlan": plan}

            response = await client.patch(
                f"https://api.vapi.ai/assistant/{assistant_id}",
                headers=headers,
                json=update_payload
            )

            if response.status_code == 200:
                print(f"    ✓ Analysis plan updated successfully")
                if not args.dry_run:
                    await record_prompt_change(
                        assistant_key=name,
                        assistant_id=assistant_id,
                        change_summary=args.summary,
                        change_category="analysis_plan",
                        prompt_content=json.dumps(plan),
                    )
            else:
                print(f"    ✗ Failed: {response.status_code}")
                print(f"      {response.text[:200]}")
            print()

    print("Done!")
    if not args.dry_run:
        print()
        print("Every call will now be automatically scored for:")
        print("  - Task completion (was the job done?)")
        print("  - Naturalness (1-5 scale)")
        print("  - Repeated questions")
        print("  - Filler phrase usage")
        print("  - User sentiment")
        print("  - Flow step adherence")
        print("  - Improvement suggestions")
        print()
        print("Results will appear in call_quality_assessments table")
        print("and on the admin Call Quality dashboard.")


if __name__ == "__main__":
    asyncio.run(main())
