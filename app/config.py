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


    # VAPI Configuration
    VAPI_API_KEY: Optional[str] = None
    VAPI_PHONE_NUMBER_ID: Optional[str] = None

    # Webhook URLs - Environment-specific
    # Development: Use Cloudflare Tunnel or ngrok URL
    # Production: Use Railway deployment URL
    DEV_WEBHOOK_BASE_URL: Optional[str] = None  # e.g., https://vapi-local.trycloudflare.com
    PROD_WEBHOOK_BASE_URL: str = "https://journ3y-vapi-skills-service.up.railway.app"

    # Legacy support (deprecated, use environment-specific URLs above)
    WEBHOOK_BASE_URL: Optional[str] = None

    # App Settings
    ENVIRONMENT: str = "development"  # "development" or "production"
    log_level: str = "INFO"

    @property
    def webhook_base_url(self) -> str:
        """
        Returns appropriate webhook URL based on environment.
        Priority:
        1. Legacy WEBHOOK_BASE_URL (for backwards compatibility)
        2. DEV_WEBHOOK_BASE_URL if ENVIRONMENT=development
        3. PROD_WEBHOOK_BASE_URL if ENVIRONMENT=production
        4. Fallback to production URL
        """
        # Legacy support
        if self.WEBHOOK_BASE_URL:
            return self.WEBHOOK_BASE_URL

        # Environment-specific
        if self.ENVIRONMENT == "development" and self.DEV_WEBHOOK_BASE_URL:
            return self.DEV_WEBHOOK_BASE_URL

        return self.PROD_WEBHOOK_BASE_URL

    class Config:
        env_file = ".env"

settings = Settings()