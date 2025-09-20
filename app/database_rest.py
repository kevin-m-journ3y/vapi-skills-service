import httpx
import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime

class SupabaseClient:
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_SERVICE_KEY")
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json"
        }

    async def authenticate_internal_user(self, phone_number: str) -> Optional[Dict]:
        """Phase 1: Basic internal user authentication"""
        async with httpx.AsyncClient() as client:
            # Simple query for Phase 1 - using existing users table
            response = await client.get(
                f"{self.url}/rest/v1/users",
                headers=self.headers,
                params={
                    "phone_number": f"eq.{phone_number}",
                    "is_active": "eq.true"
                }
            )
            
            if response.status_code == 200 and response.json():
                user = response.json()[0]
                
                # Get company info (assuming users table has company_id)
                company_response = await client.get(
                    f"{self.url}/rest/v1/companies",
                    headers=self.headers,
                    params={"id": f"eq.{user['company_id']}"}
                )
                
                if company_response.status_code == 200 and company_response.json():
                    company = company_response.json()[0]
                    
                    return {
                        "session_type": "internal_user",
                        "user_data": {
                            **user,
                            "tenants": company  # Match expected structure
                        }
                    }
            
            return None

    async def log_authentication(self, phone_number: str, success: bool, details: Dict = None):
        """Log authentication attempts for debugging"""
        try:
            async with httpx.AsyncClient() as client:
                log_data = {
                    "phone_number": phone_number,
                    "success": success,
                    "details": details or {},
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                # Log to console for Phase 1
                print(f"AUTH LOG: {json.dumps(log_data, indent=2)}")
                
        except Exception as e:
            print(f"Failed to log authentication: {e}")