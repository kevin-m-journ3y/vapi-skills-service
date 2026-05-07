# app/admin/ai_weekly_draft.py - AI draft generation for Site Weekly AI report
import httpx
import json
import logging
import os
from datetime import date, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

DRAFT_SYSTEM_PROMPT = """You are generating a first draft for a professional construction site weekly progress report.

Given raw data captured from site (timesheet verbal updates, site progress updates, trade activity), produce a structured report draft.

STYLE GUIDE — match this tone exactly:
- Weekly summary: 2–3 short paragraphs. Write like a competent site manager talking directly to a client — natural, plain English, no corporate language. State exactly what happened, nothing more. No filler phrases ("contributing to", "facilitating", "ensuring alignment", "remains on track", "significant efforts", "overall"). If there were no issues, don't mention issues. If a forward-looking sentence has no specific content, omit it entirely. Active voice, past tense.
- Key milestones: Short phrases, not full sentences. No periods. Past-tense verb or noun phrase first. Add brief context after a dash if helpful (e.g. "LVL drilling commenced - framing connections underway"). Use "&" not "and". Keep technical terms.
- BBMK WORKS: Past-tense verb, no subject pronoun. Write as completed achievements (e.g. "Drilled out for LVL (framing connections)", "Commenced joist set out", "Established levels for FF ensuites"). Technical terms as-is. No periods.
- TRADES: Format each entry as "Trade Name - past-tense activity". Write as completed achievements, not ongoing actions (e.g. "Scaffolders - Installed along southern wall and northern boundary", "Steel Contractor - Finalised first-floor steel connections", "Bricklayers - Redirected to alternate works due to block delivery issue"). No periods.
- ADMINISTRATION: Action-first past tense (Re-issued, Finalised, Liaised, Organised, Took quantities). Specific names, companies, document types. Use em dash (—) for pending items (e.g. "Organised site visit with X — Awaiting date confirmation"). No periods.

RULES:
- Write like a competent site manager talking to a client — plain English, no corporate filler
- Banned phrases across all sections: "contributing to", "facilitating", "ensuring alignment", "remains on track", "significant efforts", "overall", "timely", "seamlessly", "successfully", "effectively", "as planned", "moving forward", "in the upcoming weeks", "it is worth noting", "in a timely manner", "ensure"
- If a section has no real content, leave it empty — never pad with generic statements
- Fix speech-to-text errors (e.g. "labyrinth" → "labouring", "medial" → "remedial")
- BBMK WORKS = activities performed by the main contractor's own crew (from timesheet work descriptions)
- TRADES = subcontractors on site and what they did (from staffing notes and trade mentions)
- ADMINISTRATION = coordination, orders, quotes, meetings, procurement tasks
- [Site Note] entries are free-form observations from the team — classify each into BBMK Works, Trades, or Administration based on content
- [Site Note - Issue] entries without "(Resolved)" appear as-is in the risks section (already pre-populated from raw data); do not duplicate them in daily sections
- [Site Note - Issue (Resolved)] entries appear in the risks section with a "Resolved" suffix; do not duplicate them in daily sections
- If a section has no data for a day, return an empty list — do not invent content
- Only include Monday–Friday in the "days" object (skip weekends)

Respond with ONLY valid JSON — no markdown, no preamble."""

DRAFT_USER_TEMPLATE = """Site: {site_name}
Week: {week_label}

Raw data by day:
{daily_data}

Known risks/issues this week:
{risks}

Known follow-up actions:
{plans}

Generate the weekly report draft in this exact JSON format:
{{
  "weekly_summary": "2–3 paragraph narrative of the week",
  "key_milestones": ["Milestone 1", "Milestone 2"],
  "days": {{
    "YYYY-MM-DD": {{
      "bbmk_works": ["Activity 1", "Activity 2"],
      "trades": ["Trade Name - activity description"],
      "administration": ["Admin task 1"]
    }}
  }},
  "risks": ["Risk or issue description"],
  "plans": ["Follow-up action"]
}}"""

ENHANCE_PROMPTS = {
    "weekly_summary": (
        "Rewrite this construction site weekly summary so it reads naturally — like a competent site manager talking directly to a client. "
        "Rules: "
        "(1) Write 2–3 short paragraphs. Active voice, past tense. "
        "(2) State exactly what happened. No filler, no inflation of significance. "
        "(3) Strictly banned phrases and patterns: 'contributing to', 'facilitating', 'ensuring alignment', 'remains on track', 'significant efforts', 'overall', 'timely', 'seamlessly', 'successfully', 'effectively', 'as planned', 'it is worth noting', 'moving forward', 'in the upcoming weeks', 'The team remains'. "
        "(4) If there were no issues, do not mention issues at all — no 'No major issues were reported'. "
        "(5) Only include a forward-looking sentence if there is a specific next step from the data. Never invent one. "
        "(6) Preserve every fact exactly — do not add, invent or remove any detail. "
        "(7) One idea per sentence. Keep sentences short."
    ),
    "key_milestones": (
        "Rewrite these construction site milestones to match the style of a professional site report. "
        "Rules: "
        "(1) Keep every fact exactly as given — do not add, invent or remove any detail. "
        "(2) Write short phrases, not full sentences — no periods at the end. "
        "(3) Lead with a past-tense verb or noun phrase (e.g. 'LVL drilling commenced', 'First-floor steel connections finalised', 'Mosaic tiles signed off and ordered'). "
        "(4) Add brief context after a dash where it helps (e.g. 'LVL drilling commenced - framing connections underway'). "
        "(5) Use '&' not 'and'. Keep technical construction terms exactly as given. "
        "(6) One milestone per line. No bullet markers, no hyphens, no numbering — plain text only. "
        "(7) No padding: never use 'successfully', 'effectively', 'as planned'."
    ),
    "bbmk_works": (
        "Rewrite these BBMK construction activities to match the style of a professional, achievement-focused site report. "
        "Rules: "
        "(1) Preserve every fact — do not add, invent or remove any detail. "
        "(2) Use past-tense verbs — write as completed achievements, not ongoing actions. "
        "Convert gerunds to past tense: 'Drilling' → 'Drilled', 'Working out' → 'Established', 'Setting up' → 'Set up', 'Installing' → 'Installed'. "
        "Examples: 'Drilled out for LVL (framing connections)', 'Commenced joist set out', 'Established levels for FF ensuites'. "
        "(3) No subject pronoun. Keep all technical construction terms exactly as given. "
        "(4) No periods. One activity per line, plain text only."
    ),
    "trades": (
        "Rewrite these trade activities to match the style of a professional, achievement-focused site report. "
        "Rules: "
        "(1) Preserve every fact — do not add, invent or remove any detail. "
        "(2) Format each entry as 'Trade Name - past-tense activity'. "
        "(3) Write trade activities as completed achievements — convert gerunds and present tense to past tense. "
        "'Installing' → 'Installed', 'Finishing' → 'Finalised', 'Setting up' → 'Set up', 'Delivering' → 'Delivered'. "
        "Examples: 'Scaffolders - Installed along southern wall and northern boundary for blockwork', "
        "'Steel Contractor & Welder - Finalised first-floor steel connections', "
        "'Bricklayers - Redirected to alternate works due to block delivery issue'. "
        "(4) No periods. One trade per line, plain text only."
    ),
    "administration": (
        "Rewrite these administration items to match the style of a professional site report. "
        "Rules: "
        "(1) Preserve every fact — do not add, invent or remove any detail. "
        "(2) Use action-first past tense with no subject pronoun (e.g. 'Re-issued budget to Jake / John & DSD', 'Finalised order of cat door and sent to Steela offices', 'Liaised with steel contractor regarding carport (RLs)'). "
        "(3) Specific names, companies and document types must be kept exactly as given. "
        "(4) Chain related actions in one line where natural (e.g. 'Took quantities, signed off and ordered mosaic tiles'). "
        "(5) Use em dash (—) for items still pending (e.g. 'Organised site visit with X — Awaiting date confirmation'). "
        "(6) No periods. One item per line, plain text only."
    ),
    "risks": (
        "Rewrite these risks and issues in plain, direct language — like a site manager describing a problem to a client. "
        "Rules: "
        "(1) Preserve every fact exactly — do not add, invent or remove any detail. "
        "(2) State what happened and what is being done about it. No alarm, no inflation. "
        "(3) No filler: never use 'it is worth noting', 'significant impact', 'timely resolution', 'moving forward'. "
        "(4) Past tense. Specific and concise. One item per line, plain text only. No periods."
    ),
    "plans": (
        "Rewrite these follow-up actions in plain, direct language. "
        "Rules: "
        "(1) Preserve every fact exactly — do not add, invent or remove any detail. "
        "(2) Action-first (e.g. 'Follow up with MBS regarding block delivery', 'Confirm site visit date with Richard Custom Works'). "
        "(3) Specific — include trade names, companies and subject matter from the original. "
        "(4) No filler: never use 'ensure', 'facilitate', 'moving forward', 'in a timely manner'. "
        "(5) No periods. One item per line, plain text only."
    ),
    "looking_ahead": (
        "Improve the wording of this 'Looking Ahead' section from a construction site weekly report. "
        "Rules: "
        "(1) Preserve every activity mentioned — do not add, invent or remove any planned work. "
        "(2) Write in a clear, professional but natural tone — like a site manager briefing a client on what's coming up. "
        "(3) Keep it concise and future-focused. Present or future tense. "
        "(4) No filler phrases: avoid 'moving forward', 'ensuring', 'facilitating', 'seamlessly', 'timely'. "
        "(5) Maintain paragraph or free-form text — do not convert to bullet points. "
        "(6) Output plain text only."
    ),
}


def _iso_dates_for_week(week_start: str) -> List[str]:
    """Return Mon–Fri ISO dates for a given week_start (Monday)."""
    start = date.fromisoformat(week_start)
    return [(start + timedelta(days=i)).isoformat() for i in range(5)]


def _format_day_label(iso: str) -> str:
    d = date.fromisoformat(iso)
    return d.strftime("%A %-d %B %Y")


async def generate_weekly_draft(
    timesheets: List[Dict[str, Any]],
    site_updates: List[Dict[str, Any]],
    site_name: str,
    week_start: str,
    week_end: str,
    users: Dict[str, str],
    site_notes: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Generate an AI first draft of the weekly report from raw site data.
    Returns the content dict to store in weekly_ai_reports.content.
    Falls back to a structured empty draft if AI unavailable.
    """
    work_days = _iso_dates_for_week(week_start)
    week_label = f"{_format_day_label(week_start)} – {_format_day_label(week_end)}"

    # Group data by day
    ts_by_day: Dict[str, List[Dict]] = {d: [] for d in work_days}
    for ts in timesheets:
        d = ts.get("work_date", "")
        if d in ts_by_day:
            ts_by_day[d].append(ts)

    su_by_day: Dict[str, List[Dict]] = {d: [] for d in work_days}
    for su in site_updates:
        d = su.get("update_date", "")
        if d in su_by_day:
            su_by_day[d].append(su)

    sn_by_day: Dict[str, List[Dict]] = {d: [] for d in work_days}
    for sn in (site_notes or []):
        d = sn.get("note_date", "")
        if d in sn_by_day:
            sn_by_day[d].append(sn)

    # Build readable daily data block for the prompt
    daily_lines = []
    for iso in work_days:
        label = _format_day_label(iso)
        entries = []

        for ts in ts_by_day[iso]:
            worker = users.get(ts.get("user_id", ""), "Unknown")
            desc = (ts.get("work_description") or "").strip()
            if desc:
                entries.append(f"  [Timesheet - {worker}]: {desc}")

        for su in su_by_day[iso]:
            worker = users.get(su.get("user_id", ""), "Unknown")
            for field, label_prefix in [
                ("main_focus", "Focus"),
                ("work_progress", "Progress"),
                ("staffing", "Staffing/Trades"),
                ("follow_up_actions", "Admin/Follow-up"),
                ("issues", "Issue"),
                ("delays", "Delay"),
                ("site_conditions", "Site conditions"),
            ]:
                val = (su.get(field) or "").strip()
                if val:
                    entries.append(f"  [{label_prefix} - {worker}]: {val}")
            for item in (su.get("extracted_action_items") or []):
                if isinstance(item, dict) and item.get("action"):
                    entries.append(f"  [Admin action]: {item['action']}")

        for sn in sn_by_day[iso]:
            text = (sn.get("note_text") or "").strip()
            author_obj = sn.get("admin_users") or {}
            author = author_obj.get("username") or author_obj.get("email") or "Team"
            if text:
                tag = "[Site Note - Issue" if sn.get("is_issue") else "[Site Note"
                if sn.get("is_issue") and sn.get("is_resolved"):
                    tag += " (Resolved)"
                tag += f" - {author}]"
                entries.append(f"  {tag}: {text}")

        daily_lines.append(f"{label} ({iso}):")
        if entries:
            daily_lines.extend(entries)
        else:
            daily_lines.append("  (no data recorded)")

    # Build risks and plans
    risks_raw = []
    plans_raw = []
    for su in site_updates:
        if su.get("issues"):
            risks_raw.append(su["issues"].strip())
        if su.get("delays"):
            risks_raw.append(su["delays"].strip())
        for b in (su.get("identified_blockers") or []):
            if isinstance(b, dict) and b.get("description"):
                risks_raw.append(b["description"])
        for c in (su.get("flagged_concerns") or []):
            if isinstance(c, dict) and c.get("description"):
                risks_raw.append(c["description"])
        if su.get("follow_up_actions"):
            plans_raw.append(su["follow_up_actions"].strip())
        for a in (su.get("extracted_action_items") or []):
            if isinstance(a, dict) and a.get("action"):
                plans_raw.append(a["action"])
    for ts in timesheets:
        p = (ts.get("plans_for_tomorrow") or "").strip()
        if p:
            plans_raw.append(p)

    # Site notes: open issues → risks, resolved issues → risks with tag
    for sn in (site_notes or []):
        if sn.get("is_issue"):
            text = (sn.get("note_text") or "").strip()
            if text:
                if sn.get("is_resolved"):
                    risks_raw.append(f"{text} [Resolved]")
                else:
                    risks_raw.append(text)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — returning empty draft structure")
        return _empty_draft(work_days)

    user_content = DRAFT_USER_TEMPLATE.format(
        site_name=site_name,
        week_label=week_label,
        daily_data="\n".join(daily_lines),
        risks="\n".join(f"- {r}" for r in risks_raw) if risks_raw else "(none recorded)",
        plans="\n".join(f"- {p}" for p in plans_raw) if plans_raw else "(none recorded)",
    )

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 2500,
                },
            )

        if resp.status_code != 200:
            logger.error(f"OpenAI error {resp.status_code}: {resp.text}")
            return _empty_draft(work_days)

        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            content = content.rsplit("```", 1)[0]

        parsed = json.loads(content)

        # Ensure all working days exist in the days dict
        days = parsed.get("days", {})
        for iso in work_days:
            if iso not in days:
                days[iso] = {"bbmk_works": [], "trades": [], "administration": []}
        parsed["days"] = days

        return parsed

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse draft JSON: {e}")
        return _empty_draft(work_days)
    except Exception as e:
        logger.error(f"Error generating weekly draft: {e}")
        return _empty_draft(work_days)


async def enhance_section(
    section_type: str,
    content: str,
    context: str = "",
) -> str:
    """
    Polish a single report section using AI.
    Returns enhanced text (same format: plain text or newline-separated bullets).
    Falls back to original content on error.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return content

    system_prompt = ENHANCE_PROMPTS.get(
        section_type,
        "Rewrite this construction site report section to be clear, professional, and well-written. Preserve all facts.",
    )

    user_msg = content
    if context:
        user_msg = f"Context: {context}\n\nContent to enhance:\n{content}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 800,
                },
            )

        if resp.status_code != 200:
            logger.error(f"OpenAI enhance error {resp.status_code}")
            return content

        return resp.json()["choices"][0]["message"]["content"].strip()

    except Exception as e:
        logger.error(f"Error enhancing section: {e}")
        return content


def _empty_draft(work_days: List[str]) -> Dict[str, Any]:
    return {
        "weekly_summary": "",
        "key_milestones": [],
        "days": {
            iso: {"bbmk_works": [], "trades": [], "administration": []}
            for iso in work_days
        },
        "risks": [],
        "plans": [],
    }
