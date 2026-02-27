"""
Timesheet Skill

Provides tools for logging work hours at construction sites.
This skill only defines tools - it does not create assistants.
"""

from typing import Dict, Optional
from fastapi import FastAPI
import httpx
import logging

from app.skills.base_skill import BaseSkill
from app.config import settings

logger = logging.getLogger(__name__)


class TimesheetSkill(BaseSkill):
    """
    Timesheet Skill - Log work hours at construction sites

    This skill provides tools only:
    - identify_site: Match user's site description to available sites
    - save_timesheet_entry: Store timesheet entry for one site
    - confirm_and_save_all: Confirm and save all timesheet entries from the call

    Note: This skill does not create assistants. Use an assistant definition
    to orchestrate these tools.
    """

    def __init__(self):
        super().__init__(
            skill_key="timesheet",
            name="Timesheet",
            description="Log work hours at construction sites"
        )
        self.vapi_api_key = settings.VAPI_API_KEY
        self.vapi_base_url = "https://api.vapi.ai"
        self.webhook_base_url = settings.webhook_base_url

        if not self.vapi_api_key:
            raise ValueError("VAPI_API_KEY not configured")

    async def create_tools(self) -> Dict[str, str]:
        """
        Create VAPI tools for timesheet skill

        Returns:
            Dict with tool names mapped to VAPI tool IDs
        """
        logger.info("Creating VAPI tools for Timesheet skill...")

        tools_config = {
            "identify_site_for_timesheet": {
                "type": "function",
                "function": {
                    "name": "identify_site_for_timesheet",
                    "description": "Match the user's site description to their available sites for timesheet logging",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "site_description": {
                                "type": "string",
                                "description": "The user's description of the site (name, address, or partial match)"
                            },
                            "vapi_call_id": {
                                "type": "string",
                                "description": "The VAPI call identifier"
                            }
                        },
                        "required": ["site_description", "vapi_call_id"]
                    }
                },
                "server": {
                    "url": f"{self.webhook_base_url}/api/v1/skills/timesheet/identify-site"
                }
            },
            "save_timesheet_entry": {
                "type": "function",
                "function": {
                    "name": "save_timesheet_entry",
                    "description": "Save a single timesheet entry for one site",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "site_id": {
                                "type": "string",
                                "description": "The UUID of the site"
                            },
                            "start_time": {
                                "type": "string",
                                "description": "Start time in 24-hour format HH:MM (e.g., '09:00')"
                            },
                            "end_time": {
                                "type": "string",
                                "description": "End time in 24-hour format HH:MM (e.g., '17:30')"
                            },
                            "work_description": {
                                "type": "string",
                                "description": "Brief description of what work was done"
                            },
                            "plans_for_tomorrow": {
                                "type": "string",
                                "description": "What they plan to do at this site tomorrow (if anything)"
                            },
                            "vapi_call_id": {
                                "type": "string",
                                "description": "The VAPI call identifier"
                            }
                        },
                        "required": ["site_id", "start_time", "end_time", "work_description", "vapi_call_id"]
                    }
                },
                "server": {
                    "url": f"{self.webhook_base_url}/api/v1/skills/timesheet/save-entry"
                }
            },
            "get_signon_data": {
                "type": "function",
                "function": {
                    "name": "get_signon_data",
                    "description": "Get today's QR sign-on data for the caller. Call this immediately after greeting to check if the user signed on at any sites today. Returns site names and arrival times.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "vapi_call_id": {
                                "type": "string",
                                "description": "The VAPI call identifier"
                            }
                        },
                        "required": ["vapi_call_id"]
                    }
                },
                "server": {
                    "url": f"{self.webhook_base_url}/api/v1/skills/timesheet/get-signon-data"
                }
            },
            "confirm_and_save_all": {
                "type": "function",
                "function": {
                    "name": "confirm_and_save_all",
                    "description": "Confirm all timesheet entries and finalize the submission",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "vapi_call_id": {
                                "type": "string",
                                "description": "The VAPI call identifier"
                            },
                            "user_confirmed": {
                                "type": "boolean",
                                "description": "Whether the user confirmed all entries are correct"
                            }
                        },
                        "required": ["vapi_call_id", "user_confirmed"]
                    }
                },
                "server": {
                    "url": f"{self.webhook_base_url}/api/v1/skills/timesheet/confirm-all"
                }
            },
            "get_recent_timesheets": {
                "type": "function",
                "function": {
                    "name": "get_recent_timesheets",
                    "description": "Get the user's recent timesheet entries for the last N days. Use this when the user asks what they've already logged.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "days_back": {
                                "type": "integer",
                                "description": "Number of days to look back (default 14)"
                            },
                            "vapi_call_id": {
                                "type": "string",
                                "description": "The VAPI call identifier"
                            }
                        },
                        "required": ["vapi_call_id"]
                    }
                },
                "server": {
                    "url": f"{self.webhook_base_url}/api/v1/skills/timesheet/get-recent-timesheets"
                }
            },
            "check_date_for_conflicts": {
                "type": "function",
                "function": {
                    "name": "check_date_for_conflicts",
                    "description": "Check if the user already has timesheet entries for a specific date. Use this before logging time for historical dates to avoid duplicates.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "work_date": {
                                "type": "string",
                                "description": "The date to check in YYYY-MM-DD format"
                            },
                            "vapi_call_id": {
                                "type": "string",
                                "description": "The VAPI call identifier"
                            }
                        },
                        "required": ["work_date", "vapi_call_id"]
                    }
                },
                "server": {
                    "url": f"{self.webhook_base_url}/api/v1/skills/timesheet/check-date-conflicts"
                }
            },
            "update_timesheet_entry": {
                "type": "function",
                "function": {
                    "name": "update_timesheet_entry",
                    "description": "Update an existing timesheet entry. Use this when the user wants to modify a previously logged entry.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "timesheet_id": {
                                "type": "string",
                                "description": "The UUID of the timesheet entry to update"
                            },
                            "start_time": {
                                "type": "string",
                                "description": "New start time in 24-hour format HH:MM"
                            },
                            "end_time": {
                                "type": "string",
                                "description": "New end time in 24-hour format HH:MM"
                            },
                            "work_description": {
                                "type": "string",
                                "description": "New description of work done"
                            },
                            "plans_for_tomorrow": {
                                "type": "string",
                                "description": "Updated plans for tomorrow"
                            }
                        },
                        "required": ["timesheet_id"]
                    }
                },
                "server": {
                    "url": f"{self.webhook_base_url}/api/v1/skills/timesheet/update-entry"
                }
            }
        }

        tool_ids = {}
        headers = {
            "Authorization": f"Bearer {self.vapi_api_key}",
            "Content-Type": "application/json"
        }

        # Check for existing tools first
        existing_tools = await self._get_existing_tools(headers)

        async with httpx.AsyncClient() as client:
            for tool_name, tool_config in tools_config.items():
                # Skip if tool already exists
                if tool_name in existing_tools:
                    tool_ids[tool_name] = existing_tools[tool_name]
                    logger.info(f"Using existing tool: {tool_name} ({tool_ids[tool_name]})")
                    continue

                # Create new tool
                response = await client.post(
                    f"{self.vapi_base_url}/tool",
                    headers=headers,
                    json=tool_config
                )

                if response.status_code == 201:
                    tool = response.json()
                    tool_ids[tool_name] = tool['id']
                    logger.info(f"Created tool: {tool_name} ({tool_ids[tool_name]})")
                else:
                    logger.error(f"Failed to create tool {tool_name}: {response.status_code} - {response.text}")
                    raise Exception(f"Tool creation failed for {tool_name}: {response.text}")

        return tool_ids

    async def _get_existing_tools(self, headers: Dict) -> Dict[str, str]:
        """Get existing tools to avoid duplicates"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.vapi_base_url}/tool",
                headers=headers
            )

            if response.status_code == 200:
                tools = response.json()
                tool_map = {}
                for tool in tools:
                    if tool.get('function', {}).get('name'):
                        tool_map[tool['function']['name']] = tool['id']
                return tool_map
            else:
                logger.warning(f"Failed to get existing tools: {response.status_code}")
                return {}

    async def create_assistant(self, tool_ids: Dict[str, str]) -> str:
        """
        Timesheet skill does not create assistants.
        It only provides tools that assistants can use.

        Raises:
            NotImplementedError: This skill doesn't create assistants
        """
        raise NotImplementedError(
            "TimesheetSkill does not create assistants. "
            "It provides tools for assistants to use. "
            "Use an assistant definition (e.g., TimesheetAssistant) instead."
        )

    def register_routes(self, app: FastAPI, prefix: str = ""):
        """
        Register timesheet endpoints with FastAPI

        Args:
            app: FastAPI application instance
            prefix: Optional URL prefix (e.g., "/api/v1")
        """
        from app.skills.timesheet.endpoints import router

        app.include_router(router, prefix=prefix)
        logger.info(f"Registered Timesheet routes with prefix: {prefix}")
