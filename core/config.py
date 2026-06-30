"""Application settings loaded from .env file."""

from datetime import timezone, timedelta
from pydantic_settings import BaseSettings

# Indian Standard Time (UTC+05:30)
IST = timezone(timedelta(hours=5, minutes=30))
TIMEZONE = IST



class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "sqlite:///./lifeos.db"

    # JWT
    SECRET_KEY: str = "change-me-to-a-random-secret-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # Groq (via OpenAI SDK)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GROQ_LIGHT_MODEL: str = "llama-3.1-8b-instant"

    # Dev mode
    DEV_MODE: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
