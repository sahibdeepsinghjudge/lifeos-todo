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

    # AI Provider selection: 'gemini' or 'groq'
    AI_PROVIDER: str = "groq"

    # Gemini (via OpenAI SDK)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_LIGHT_MODEL: str = "gemini-2.5-flash-lite"

    # Groq (via OpenAI SDK)
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "qwen/qwen3.6-27b"
    GROQ_LIGHT_MODEL: str = "llama-3.1-8b-instant"

    # Google Sign-In: comma-separated OAuth client IDs allowed as `aud` in
    # Google ID tokens (web + android + ios client ids). Empty disables the
    # audience check (dev only).
    GOOGLE_CLIENT_IDS: str = ""

    # App metadata served to clients via GET /meta
    APP_VERSION: str = "0.3.0B"
    APP_BUILD_NUMBER: int = 3
    # Oldest mobile build allowed to talk to this backend (for force-update UX)
    MIN_SUPPORTED_BUILD: int = 1

    # Billing
    # Master switch for paid subscriptions. While False the app is in
    # free-access mode: every signed-in user is entitled, no paywall is
    # shown, and the purchase endpoints refuse to run. Nothing is written to
    # user rows in this mode, so flipping it back to True restores each
    # user's real state (an unused free trial stays unused).
    BILLING_ENABLED: bool = False
    TRIAL_DAYS: int = 3
    PRICE_MONTHLY_INR: int = 149
    PRICE_YEARLY_INR: int = 1499

    # Razorpay (web subscriptions). Plan ids are created in the Razorpay
    # dashboard (Subscriptions → Plans) and pasted here.
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    RAZORPAY_PLAN_MONTHLY: str = ""
    RAZORPAY_PLAN_YEARLY: str = ""

    # Google Play Billing (Android in-app subscriptions). The app launches the
    # Play purchase flow; we verify the resulting purchase token server-side
    # against the Play Developer API before granting entitlement.
    #   - PACKAGE_NAME: the Android applicationId (com.sahibdeepjwd.phagan).
    #   - SERVICE_ACCOUNT_JSON: the full JSON key of a service account granted
    #     "View financial data / Manage orders" access in Play Console, linked
    #     via Google Cloud. Pasted as a single-line JSON string (or a path —
    #     see google_play_service._load_credentials).
    #   - PRODUCT_MONTHLY / PRODUCT_YEARLY: the subscription product IDs created
    #     in Play Console (Monetize → Subscriptions), mapped back to our plans.
    #   - RTDN_VERIFICATION_TOKEN: an optional shared secret we require on the
    #     Pub/Sub push URL (?token=...) so only Google can post notifications.
    GOOGLE_PLAY_PACKAGE_NAME: str = "com.sahibdeepjwd.phagan"
    GOOGLE_PLAY_SERVICE_ACCOUNT_JSON: str = ""
    GOOGLE_PLAY_PRODUCT_MONTHLY: str = "ottoai_pro_monthly"
    GOOGLE_PLAY_PRODUCT_YEARLY: str = "ottoai_pro_yearly"
    GOOGLE_PLAY_RTDN_VERIFICATION_TOKEN: str = ""

    # Resend (transactional email)
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "OttoAI <ottoai@happpening.com>"
    # Days before expiry to send the renewal-reminder email.
    EXPIRY_REMINDER_DAYS: int = 3

    # Public URLs used in emails / redirects.
    WEBSITE_URL: str = "https://ottoai.happpening.com"

    # Admin dashboard: comma-separated emails allowed into /admin, plus a
    # basic-auth password for the dashboard itself.
    ADMIN_EMAILS: str = ""
    ADMIN_DASHBOARD_PASSWORD: str = ""

    # Dev mode
    DEV_MODE: bool = True

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
