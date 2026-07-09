"""Jill-style SMS detail capture.

When a worker finalizes a shift with no description, we don't want a blank
record. This module lets "Jill" ask a short, contextual follow-up — the way she
would on a voice call — using what she already knows (the site, hours, the photo
they just sent, their recent work) to make the question specific, not generic.

Bounded: at most two questions, then she's satisfied. Best-effort — every call
falls back to a deterministic question if the LLM is unavailable, so the core
timesheet flow never depends on it.
"""

import os
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"
MAX_QUESTIONS = 2

SYSTEM_PROMPT = (
    "You are Jill, a warm, efficient assistant who collects construction workers' "
    "daily site updates by SMS. Your goal is a useful one or two line record of what "
    "they actually did today that their office can turn into an update for their own "
    "client. You already know some context about the shift. Ask ONE short, specific, "
    "friendly question at a time to draw out what they worked on — reference what you "
    "already know (the site, a photo they sent, their recent work) so it feels personal, "
    "never generic.\n\n"
    "Be easily satisfied: the questioning exists ONLY to rescue empty or vague updates. "
    "The moment the worker has given any real, specific detail about what they did, "
    "reply with exactly DONE and stop — do not fish for more. Only ask a follow-up when "
    "their answer is still empty or vague (e.g. 'stuff', 'work', 'the usual', 'bits and "
    "pieces'). Never ask more than two questions in total. Never nitpick a genuine "
    "answer.\n\n"
    "Keep each message under 160 characters. Output only the SMS text to send, or DONE."
)


def _url() -> str:
    return os.getenv("SUPABASE_URL", "")


def _headers() -> dict:
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _plural(n: int) -> str:
    return f"{n} photo" + ("" if n == 1 else "s")


async def build_context(client: httpx.AsyncClient, *, user_id: str, signon: dict, hours) -> dict:
    """Assemble what Jill knows about this shift: worker, site, hours, today's
    photos (+ captions), and the worker's recent descriptions (for style/phase)."""
    ctx = {"site": signon.get("site_name") or "the site", "hours": None,
           "first_name": "", "photo_count": 0, "photo_captions": [], "recent_work": []}
    try:
        ctx["hours"] = round(float(hours), 2) if hours is not None else None
    except (TypeError, ValueError):
        ctx["hours"] = None

    # Worker first name
    try:
        ur = await client.get(f"{_url()}/rest/v1/users", headers=_headers(),
                              params={"id": f"eq.{user_id}", "select": "name"})
        if ur.status_code == 200 and ur.json():
            ctx["first_name"] = (ur.json()[0].get("name") or "").split()[0] if ur.json()[0].get("name") else ""
    except Exception:
        pass

    # Today's photos for this sign-on
    try:
        pr = await client.get(f"{_url()}/rest/v1/timesheet_media", headers=_headers(),
                              params={"signon_id": f"eq.{signon['id']}", "select": "caption"})
        rows = pr.json() if pr.status_code == 200 else []
        ctx["photo_count"] = len(rows)
        ctx["photo_captions"] = [r["caption"].strip() for r in rows if (r.get("caption") or "").strip()]
    except Exception:
        pass

    # Worker's recent, real descriptions (context for phase/style — deduped)
    try:
        tr = await client.get(f"{_url()}/rest/v1/timesheets", headers=_headers(), params={
            "user_id": f"eq.{user_id}", "work_description": "not.is.null",
            "select": "work_description", "order": "work_date.desc", "limit": "15"})
        seen, recent = set(), []
        for row in (tr.json() if tr.status_code == 200 else []):
            d = (row.get("work_description") or "").strip()
            if not d or d == "(logged via SMS, no description)":
                continue
            short = d.split("|")[0].strip()[:60].strip()
            k = short.lower()
            if short and k not in seen:
                seen.add(k); recent.append(short)
            if len(recent) >= 4:
                break
        ctx["recent_work"] = recent
    except Exception:
        pass

    return ctx


def _fallback_question(context: dict, conversation: list) -> Optional[str]:
    """Deterministic question when the LLM is unavailable. Only opens the
    conversation (returns None for follow-ups, so we don't push blindly)."""
    if conversation:
        return None  # without AI, don't guess at follow-ups
    if context.get("photo_count"):
        return (f"You added {_plural(context['photo_count'])} today — "
                f"what were you working on? A line is plenty.")
    recent = context.get("recent_work") or []
    if recent:
        egs = " or ".join(f"\"{r}\"" for r in recent[:2])
        return f"What did you focus on today? A line is plenty (e.g. {egs})."
    return ("What did you focus on today? A line is plenty "
            "(e.g. \"poured slab, formwork for stage 2\").")


async def next_question(context: dict, conversation: list) -> Optional[str]:
    """Return Jill's next SMS question, or None when she has enough.

    conversation: list of {"q": <asked>, "a": <reply or None>} in order.
    """
    # Hard cap regardless of the model's opinion.
    asked = sum(1 for turn in conversation if turn.get("q"))
    if asked >= MAX_QUESTIONS:
        return None

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return _fallback_question(context, conversation)

    convo_lines = []
    for turn in conversation:
        if turn.get("q"):
            convo_lines.append(f"Jill: {turn['q']}")
        if turn.get("a"):
            convo_lines.append(f"Worker: {turn['a']}")
    user_content = (
        "Shift context (what you already know):\n"
        + json.dumps({
            "worker_first_name": context.get("first_name") or "",
            "site": context.get("site"),
            "hours_worked": context.get("hours"),
            "photos_added_today": context.get("photo_count", 0),
            "photo_captions": context.get("photo_captions", []),
            "workers_recent_updates": context.get("recent_work", []),
        }, indent=2)
        + "\n\nConversation so far:\n"
        + ("\n".join(convo_lines) if convo_lines else "(none yet)")
        + "\n\nReply with the next SMS to send, or DONE."
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": MODEL, "temperature": 0.5, "max_tokens": 60,
                      "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                   {"role": "user", "content": user_content}]},
            )
        if resp.status_code != 200:
            logger.warning("Detail-AI OpenAI error %s: %s", resp.status_code, resp.text[:160])
            return _fallback_question(context, conversation)
        text = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
        # The model sometimes echoes the "Jill:" speaker label from the transcript.
        if text.lower().startswith("jill:"):
            text = text[len("jill:"):].strip()
        if not text or text.upper().rstrip(".!") == "DONE":
            return None
        return text[:300]
    except Exception as e:
        logger.warning("Detail-AI call failed: %s", e)
        return _fallback_question(context, conversation)
