"""
OpenAI Processing Pipeline for Site Updates

Extracts structured intelligence from raw site progress updates including:
- Action items with priorities
- Timeline blockers
- Safety and quality concerns
- Summaries
"""

import json
import logging
from typing import Dict, List, Optional
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class SiteUpdateProcessor:
    """
    Processes raw site update data using OpenAI to extract:
    - Summaries (brief and detailed)
    - Action items
    - Blockers
    - Flagged concerns
    - Boolean flags
    """

    def __init__(self):
        self.openai_url = "https://api.openai.com/v1/chat/completions"
        self.model = "gpt-4o-mini"  # Fast and cost-effective

    async def process_update(self, update_data: Dict) -> Dict:
        """
        Process a site update through OpenAI to extract intelligence

        Args:
            update_data: Raw update data from VAPI conversation

        Returns:
            Dict with AI-processed fields ready for database
        """
        # Build comprehensive prompt
        prompt = self._build_processing_prompt(update_data)

        # Call OpenAI
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(
                    self.openai_url,
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are an expert construction project analyst. Extract structured information from site progress updates."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        "temperature": 0.3,  # Lower temperature for consistent extraction
                        "max_tokens": 2000
                    }
                )

                if response.status_code != 200:
                    logger.error(f"OpenAI API error: {response.status_code} - {response.text}")
                    return self._get_fallback_processing(update_data)

                result = response.json()
                ai_response = result["choices"][0]["message"]["content"]

                # Parse JSON response
                try:
                    processed = json.loads(ai_response)
                    logger.info(f"Successfully processed site update with AI")
                    return processed
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse AI response as JSON: {e}")
                    logger.error(f"AI Response: {ai_response}")
                    return self._get_fallback_processing(update_data)

            except Exception as e:
                logger.error(f"Error processing update with OpenAI: {e}")
                return self._get_fallback_processing(update_data)

    def _build_processing_prompt(self, update_data: Dict) -> str:
        """Build the prompt for OpenAI processing"""
        return f"""
Analyze this construction site progress update and extract structured information.

SITE UPDATE DATA:
- Main Focus: {update_data.get('main_focus', 'N/A')}
- Wet Weather Closure: {update_data.get('is_wet_weather_closure', False)}
- Materials/Deliveries: {update_data.get('materials_delivered', 'N/A')}
- Work Progress: {update_data.get('work_progress', 'N/A')}
- Issues: {update_data.get('issues', 'N/A')}
- Delays: {update_data.get('delays', 'N/A')}
- Staffing: {update_data.get('staffing', 'N/A')}
- Site Visitors: {update_data.get('site_visitors', 'N/A')}
- Site Conditions: {update_data.get('site_conditions', 'N/A')}
- Follow-up Actions: {update_data.get('follow_up_actions', 'N/A')}

Extract and return ONLY valid JSON with this exact structure (no markdown, no explanation):

{{
  "summary_brief": "2-3 sentence overview of the day",
  "summary_detailed": "Comprehensive paragraph covering all major points",
  "has_urgent_issues": true/false,
  "has_safety_concerns": true/false,
  "has_delays": true/false,
  "has_material_issues": true/false,
  "extracted_action_items": [
    {{
      "action": "Specific action needed",
      "priority": "high/medium/low",
      "deadline": "estimated completion date or null",
      "assigned_to": "role or person if mentioned, otherwise null"
    }}
  ],
  "identified_blockers": [
    {{
      "blocker_type": "material/weather/staffing/equipment/other",
      "description": "What is blocking progress",
      "impact": "How this affects the project",
      "estimated_resolution": "When this might be resolved or null"
    }}
  ],
  "flagged_concerns": [
    {{
      "concern_type": "safety/quality/schedule/budget/other",
      "severity": "critical/high/medium/low",
      "description": "Details of the concern"
    }}
  ]
}}

IMPORTANT:
- Return ONLY the JSON object
- Use empty arrays [] if no items found in a category
- Be specific and actionable in extracted items
- Identify urgent issues even if not explicitly stated (e.g., safety hazards, critical path delays)
"""

    def _get_fallback_processing(self, update_data: Dict) -> Dict:
        """
        Provide basic processing if OpenAI fails

        Returns minimal processed data with simple heuristics
        """
        # Simple keyword-based detection
        text_content = " ".join([
            str(v) for v in update_data.values() if v and isinstance(v, str)
        ]).lower()

        return {
            "summary_brief": f"Site update recorded for {update_data.get('main_focus', 'general progress')}",
            "summary_detailed": f"Main focus: {update_data.get('main_focus', 'N/A')}. "
                              f"Work progress: {update_data.get('work_progress', 'N/A')}. "
                              f"Issues: {update_data.get('issues', 'None reported')}.",
            "has_urgent_issues": any(word in text_content for word in ['urgent', 'critical', 'emergency', 'immediate']),
            "has_safety_concerns": any(word in text_content for word in ['safety', 'hazard', 'injury', 'dangerous', 'unsafe']),
            "has_delays": any(word in text_content for word in ['delay', 'behind', 'postpone', 'reschedule']),
            "has_material_issues": any(word in text_content for word in ['material', 'delivery', 'supply', 'shortage']),
            "extracted_action_items": [],
            "identified_blockers": [],
            "flagged_concerns": []
        }


# Singleton instance
_processor = None


def get_processor() -> SiteUpdateProcessor:
    """Get or create the site update processor instance"""
    global _processor
    if _processor is None:
        _processor = SiteUpdateProcessor()
    return _processor
