# app/vapi_tools_setup.py
import httpx
import os
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class VAPIToolsManager:
    def __init__(self):
        self.api_key = os.getenv('VAPI_API_KEY')
        self.base_url = "https://api.vapi.ai"
        self.webhook_base_url = os.getenv('WEBHOOK_BASE_URL')
        
        if not self.api_key:
            raise ValueError("VAPI_API_KEY environment variable is required")
        if not self.webhook_base_url:
            raise ValueError("WEBHOOK_BASE_URL environment variable is required")
    
    async def create_authenticate_caller_tool(self) -> str:
        """Create the authenticate_caller tool and return its ID"""
        
        tool_data = {
            "type": "function",
            "function": {
                "name": "authenticate_caller",
                "description": "Authenticate the caller using their phone number and call ID to verify they are authorized to use voice notes",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "caller_phone": {
                            "type": "string",
                            "description": "The caller's phone number"
                        },
                        #"vapi_call_id": {
                        #    "type": "string",
                        #    "description": "The VAPI call identifier"
                        #}
                    },
                    "required": ["caller_phone"]
                }
            },
            "server": {
                "url": f"{self.webhook_base_url}/api/v1/vapi/authenticate-by-phone"
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/tool",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=tool_data
            )
            
            if response.status_code == 201:
                tool = response.json()
                logger.info(f"Created authenticate_caller tool: {tool['id']}")
                return tool['id']
            else:
                logger.error(f"Failed to create authenticate_caller tool: {response.status_code} - {response.text}")
                raise Exception(f"Tool creation failed: {response.text}")
    
    async def create_identify_context_tool(self) -> str:
        """Create the identify_context tool and return its ID"""
        
        tool_data = {
            "type": "function", 
            "function": {
                "name": "identify_context",
                "description": "Identify whether the voice note is general or site-specific based on user input",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_input": {
                            "type": "string",
                            "description": "The user's description of what their note is about"
                        },
                        "vapi_call_id": {
                            "type": "string",
                            "description": "The VAPI call identifier"
                        }
                    },
                    "required": ["user_input", "vapi_call_id"]
                }
            },
            "server": {
                "url": f"{self.webhook_base_url}/api/v1/skills/voice-notes/identify-context"
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/tool",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=tool_data
            )
            
            if response.status_code == 201:
                tool = response.json()
                logger.info(f"Created identify_context tool: {tool['id']}")
                return tool['id']
            else:
                logger.error(f"Failed to create identify_context tool: {response.status_code} - {response.text}")
                raise Exception(f"Tool creation failed: {response.text}")
    
    async def create_save_note_tool(self) -> str:
        """Create the save_note tool and return its ID"""
        
        tool_data = {
            "type": "function",
            "function": {
                "name": "save_note",
                "description": "Save the voice note with all collected information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note_text": {
                            "type": "string",
                            "description": "The transcribed voice note content"
                        },
                        "note_type": {
                            "type": "string",
                            "enum": ["general", "site_specific"],
                            "description": "Whether this is a general note or site-specific note"
                        },
                        "site_id": {
                            "type": "string",
                            "description": "Site ID if this is a site-specific note (null for general notes)"
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["low", "medium", "high", "urgent"],
                            "description": "Priority level of the note"
                        },
                        "vapi_call_id": {
                            "type": "string",
                            "description": "The VAPI call identifier"
                        }
                    },
                    "required": ["note_text", "note_type", "vapi_call_id"]
                }
            },
            "server": {
                "url": f"{self.webhook_base_url}/api/v1/skills/voice-notes/save-note"
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/tool",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=tool_data
            )
            
            if response.status_code == 201:
                tool = response.json()
                logger.info(f"Created save_note tool: {tool['id']}")
                return tool['id']
            else:
                logger.error(f"Failed to create save_note tool: {response.status_code} - {response.text}")
                raise Exception(f"Tool creation failed: {response.text}")
    
    async def get_existing_tools(self) -> Dict[str, str]:
        """Get existing tools by name to avoid duplicates"""
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/tool",
                headers={
                    "Authorization": f"Bearer {self.api_key}"
                }
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
    
    async def setup_all_tools(self) -> Dict[str, str]:
        """Set up all required tools and return their IDs"""
        
        # Check for existing tools first
        existing_tools = await self.get_existing_tools()
        tool_ids = {}
        
        # Create or get authenticate_caller tool
        if 'authenticate_caller' in existing_tools:
            tool_ids['authenticate_caller'] = existing_tools['authenticate_caller']
            logger.info(f"Using existing authenticate_caller tool: {tool_ids['authenticate_caller']}")
        else:
            tool_ids['authenticate_caller'] = await self.create_authenticate_caller_tool()
        
        # Create or get identify_context tool  
        if 'identify_context' in existing_tools:
            tool_ids['identify_context'] = existing_tools['identify_context']
            logger.info(f"Using existing identify_context tool: {tool_ids['identify_context']}")
        else:
            tool_ids['identify_context'] = await self.create_identify_context_tool()
        
        # Create or get save_note tool
        if 'save_note' in existing_tools:
            tool_ids['save_note'] = existing_tools['save_note']
            logger.info(f"Using existing save_note tool: {tool_ids['save_note']}")
        else:
            tool_ids['save_note'] = await self.create_save_note_tool()
        
        logger.info(f"All tools ready: {tool_ids}")
        return tool_ids

    async def delete_tool(self, tool_id: str) -> bool:
        """Delete a tool by ID (useful for cleanup)"""
        
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.base_url}/tool/{tool_id}",
                headers={
                    "Authorization": f"Bearer {self.api_key}"
                }
            )
            
            success = response.status_code == 200
            if success:
                logger.info(f"Deleted tool: {tool_id}")
            else:
                logger.error(f"Failed to delete tool {tool_id}: {response.status_code}")
            
            return success