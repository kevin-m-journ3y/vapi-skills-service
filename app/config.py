from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Database
    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str
    
    # AI Services
    claude_api_key: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None 
    GOOGLE_SERVICE_ACCOUNT_JSON: Optional[str] = None  # Used in main.py

    
    # VAPI
    VAPI_API_KEY: Optional[str] = None
    WEBHOOK_BASE_URL: Optional[str] = "https://journ3y-vapi-skills-service.up.railway.app"
    
    # App Settings
    environment: str = "development"
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"

settings = Settings()