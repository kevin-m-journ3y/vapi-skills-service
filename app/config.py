from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Database
    supabase_url: str
    supabase_service_key: str
    
    # AI Services
    claude_api_key: Optional[str] = None

    
    # VAPI
    AVPI_API_KEY: Optional[str] = None
    
    # App Settings
    environment: str = "development"
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"

settings = Settings()