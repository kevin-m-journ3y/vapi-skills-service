# app/admin/work_summary.py - AI-powered work summary for site reports
import hashlib
import httpx
import json
import logging
import os
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

WORK_SUMMARY_PROMPT = """You are summarising construction site activities for a professional weekly site report.

Given these raw verbal updates from construction workers (captured via phone call voice-to-text), produce a clean, categorised summary.

INSTRUCTIONS:
1. **Fix speech-to-text errors** - common mistakes include:
   - "labyrinth" → "labouring"
   - "medial" → "remedial"
   - "Aves" → "eaves"
   - "a board" → "A-board" or "bargeboards" depending on context
   - Fix any other obvious STT misrecognitions
2. **Group into categories** from this list (only include categories that have items):
   - Structural & Framing
   - External / Facade
   - Remedial & Defects
   - Demolition & Strip-out
   - Prep & Cleanup
   - Site Management
   - Fitout & Finishing
   - Services (electrical, plumbing, etc.)
3. **Consolidate duplicates** - if a worker logged similar work across multiple days, combine into one clear line
4. **Write clean, professional bullet points** in past tense ("Removed render from north wall" not "removing render")
5. **Include worker initials** after each item using the provided name-to-initials mapping
6. Keep it concise - aim for 1-2 lines per item max

Respond with ONLY valid JSON in this exact format:
{
  "categories": [
    {
      "name": "Category Name",
      "items": [
        {"text": "Clean description of work done", "workers": ["KW", "RM"]}
      ]
    }
  ]
}

Do not include any text before or after the JSON."""


def _get_initials(name: str) -> str:
    """Get initials from a full name."""
    parts = name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    elif parts:
        return parts[0][0].upper()
    return "?"


def _compute_source_hash(work_items: List[Dict[str, Any]]) -> str:
    """Hash the raw work items so we can detect changes."""
    content = json.dumps(work_items, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


async def _get_cached_summary(
    tenant_id: str, site_id: str, week_start: str, week_end: str, source_hash: str
) -> Optional[List[Dict[str, Any]]]:
    """Check Supabase cache for an existing summary."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/work_summary_cache",
                headers={
                    "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "site_id": f"eq.{site_id}",
                    "week_start": f"eq.{week_start}",
                    "week_end": f"eq.{week_end}",
                    "source_hash": f"eq.{source_hash}",
                    "select": "categories"
                }
            )
            if response.status_code == 200 and response.json():
                logger.info(f"Work summary cache hit for site={site_id} week={week_start}")
                return response.json()[0]["categories"]
    except Exception as e:
        logger.warning(f"Cache lookup failed (will regenerate): {e}")
    return None


async def _save_cached_summary(
    tenant_id: str, site_id: str, week_start: str, week_end: str,
    source_hash: str, categories: List[Dict[str, Any]]
):
    """Save summary to Supabase cache. Upsert on the unique constraint."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Delete any existing row for this site+week (source_hash may differ)
            await client.delete(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/work_summary_cache",
                headers={
                    "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                },
                params={
                    "tenant_id": f"eq.{tenant_id}",
                    "site_id": f"eq.{site_id}",
                    "week_start": f"eq.{week_start}",
                    "week_end": f"eq.{week_end}",
                }
            )
            # Insert fresh
            await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/work_summary_cache",
                headers={
                    "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                json={
                    "tenant_id": tenant_id,
                    "site_id": site_id,
                    "week_start": week_start,
                    "week_end": week_end,
                    "source_hash": source_hash,
                    "categories": categories,
                }
            )
            logger.info(f"Work summary cached for site={site_id} week={week_start}")
    except Exception as e:
        logger.warning(f"Failed to cache work summary (non-fatal): {e}")


async def summarise_work_items(
    work_items: List[Dict[str, Any]],
    users: Dict[str, str],
    tenant_id: str = "",
    site_id: str = "",
    week_start: str = "",
    week_end: str = "",
) -> List[Dict[str, Any]]:
    """
    Use GPT-4o-mini to categorise and clean up raw work descriptions.
    Results are cached in Supabase — only calls OpenAI when data changes.

    Args:
        work_items: List of {"text": str, "user": str, "date": str}
        users: Dict of user_id -> full name (for building initials map)
        tenant_id, site_id, week_start, week_end: Cache key fields

    Returns:
        List of {"name": str, "items": [{"text": str, "workers": ["AB"]}]}
        Falls back to uncategorised list on error.
    """
    if not work_items:
        return []

    source_hash = _compute_source_hash(work_items)

    # Check cache first
    if tenant_id and site_id and week_start and week_end:
        cached = await _get_cached_summary(tenant_id, site_id, week_start, week_end, source_hash)
        if cached is not None:
            return cached

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set - returning raw work items")
        return _fallback_format(work_items)

    # Build initials map
    name_initials = {}
    for uid, name in users.items():
        name_initials[name] = _get_initials(name)

    # Format input for the LLM
    lines = []
    for item in work_items:
        user = item.get("user", "Unknown")
        initials = name_initials.get(user, _get_initials(user))
        date = item.get("date", "")
        lines.append(f"- {item['text']} (Worker: {user} [{initials}], Date: {date})")

    user_content = f"""Worker name → initials mapping:
{json.dumps({name: init for name, init in name_initials.items()}, indent=2)}

Raw work updates for this week:
{chr(10).join(lines)}"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": WORK_SUMMARY_PROMPT},
                        {"role": "user", "content": user_content}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1500
                }
            )

            if response.status_code != 200:
                logger.error(f"OpenAI API error: {response.status_code} - {response.text}")
                return _fallback_format(work_items)

            result = response.json()
            content = result["choices"][0]["message"]["content"].strip()

            # Parse JSON response - handle markdown code fences
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                content = content.rsplit("```", 1)[0]

            parsed = json.loads(content)
            categories = parsed.get("categories", [])

            if not categories:
                return _fallback_format(work_items)

            # Cache the result
            if tenant_id and site_id and week_start and week_end:
                await _save_cached_summary(
                    tenant_id, site_id, week_start, week_end, source_hash, categories
                )

            return categories

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse OpenAI response as JSON: {e}")
        return _fallback_format(work_items)
    except Exception as e:
        logger.error(f"Error calling OpenAI for work summary: {e}")
        return _fallback_format(work_items)


def _fallback_format(work_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fallback: return items uncategorised if AI fails."""
    items = []
    for wi in work_items:
        user = wi.get("user", "Unknown")
        initials = _get_initials(user)
        items.append({"text": wi["text"], "workers": [initials]})

    return [{"name": "Work Completed", "items": items}] if items else []
