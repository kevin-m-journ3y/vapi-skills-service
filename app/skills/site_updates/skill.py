"""
Site Updates Skill

Manages site progress updates with AI-powered intelligence extraction.
"""

from typing import Dict, List, Optional
from app.skills.base_skill import BaseSkill


class SiteUpdatesSkill(BaseSkill):
    """
    Site Progress Updates Skill

    Allows users to provide structured daily progress updates for construction sites,
    with AI processing to extract action items, blockers, and concerns.
    """

    def __init__(self):
        super().__init__(
            skill_key="site_updates",
            name="Site Progress Updates",
            description="Record daily site progress updates with structured data collection and AI analysis",
            version="1.0.0"
        )

    def get_required_tools(self) -> List[Dict]:
        """
        Define VAPI tools needed for this skill

        Returns list of tool definitions that will be registered with VAPI
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "identify_site_for_update",
                    "description": "Identify which construction site the user wants to provide an update for",
                    "strict": True,
                    "parameters": {
                        "type": "object",
                        "required": ["user_input"],
                        "properties": {
                            "user_input": {
                                "type": "string",
                                "description": "The user's description of which site they want to update"
                            }
                        }
                    }
                },
                "server": {
                    "url": "{WEBHOOK_BASE_URL}/api/v1/skills/site-updates/identify-site"
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "save_site_progress_update",
                    "description": "Save a complete site progress update with all collected information",
                    "strict": True,
                    "parameters": {
                        "type": "object",
                        "required": ["site_id"],
                        "properties": {
                            "site_id": {
                                "type": "string",
                                "description": "UUID of the site being updated"
                            },
                            "main_focus": {
                                "type": "string",
                                "description": "Main focus of work at the site today"
                            },
                            "is_wet_weather_closure": {
                                "type": "boolean",
                                "description": "True if site was closed due to bad weather"
                            },
                            "materials_delivered": {
                                "type": "string",
                                "description": "Information about materials and deliveries"
                            },
                            "work_progress": {
                                "type": "string",
                                "description": "Work completed and progress made"
                            },
                            "issues": {
                                "type": "string",
                                "description": "Problems or issues that came up"
                            },
                            "delays": {
                                "type": "string",
                                "description": "Delays affecting timeline"
                            },
                            "staffing": {
                                "type": "string",
                                "description": "Staffing and resource information"
                            },
                            "site_visitors": {
                                "type": "string",
                                "description": "Site visitors, approvals, and interactions"
                            },
                            "site_conditions": {
                                "type": "string",
                                "description": "Site conditions, safety observations, access issues"
                            },
                            "follow_up_actions": {
                                "type": "string",
                                "description": "Follow-up actions and tomorrow's plans"
                            },
                            "raw_transcript": {
                                "type": "string",
                                "description": "Full conversation transcript for reference"
                            }
                        }
                    }
                },
                "server": {
                    "url": "{WEBHOOK_BASE_URL}/api/v1/skills/site-updates/save-update"
                }
            }
        ]

    def get_vapi_assistant_config(self) -> Optional[Dict]:
        """
        Return VAPI assistant configuration for site progress updates

        This will be defined in app/assistants/site_progress.py
        """
        return None  # Assistant defined separately

    def register_routes(self, app, prefix: str = ""):
        """Register FastAPI routes for this skill"""
        from app.skills.site_updates.endpoints import router
        app.include_router(router, prefix=prefix, tags=["site-updates"])
        self.logger.info(f"Registered Site Updates routes with prefix: {prefix}")

    def validate_user_access(self, user_id: str, tenant_id: str) -> bool:
        """
        Validate if user has access to this skill

        Checked via user_skills table in the database
        """
        # This will be checked by the authentication system
        return True

    def get_required_permissions(self) -> List[str]:
        """Define permissions needed for this skill"""
        return ["site_updates.create", "site_updates.view"]
