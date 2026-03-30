"""
Configuration management for TradeReply
"""

import os
from pathlib import Path


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


class Config:
    """Application configuration"""

    # Database
    DATABASE_PATH = os.getenv("TRADEREPLY_DB_PATH", "tradereply.db")

    # Twilio
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "+61468155994")

    # Google Business API (Phase 2)
    GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "")
    GOOGLE_BUSINESS_ACCOUNT_ID = os.getenv("GOOGLE_BUSINESS_ACCOUNT_ID", "")

    # AI/Gemini
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    MODEL_NAME = os.getenv("TRADEREPLY_MODEL", "gemini-2.0-flash")

    # FastAPI
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 8000))

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "tradereply.log")

    # Feature flags
    DRY_RUN_SMS = os.getenv("DRY_RUN_SMS", "true").lower() == "true"
    DRY_RUN_AI = os.getenv("DRY_RUN_AI", "false").lower() == "true"

    @classmethod
    def environment_name(cls) -> str:
        return os.getenv("ENVIRONMENT", "development")

    @classmethod
    def validate(cls):
        """Validate required configuration.

        Returns:
            list[str]: validation warnings/errors in non-production modes.

        Raises:
            ConfigError: in production when required settings are missing/invalid.
        """
        env = cls.environment_name()
        issues = []

        if not cls.TWILIO_FROM_NUMBER:
            issues.append("TWILIO_FROM_NUMBER not set")

        if not cls.DATABASE_PATH:
            issues.append("TRADEREPLY_DB_PATH not set")

        if env == "production":
            # Phase 1: Core requirements (Twilio + Gemini only)
            required_phase1 = {
                "TWILIO_ACCOUNT_SID": cls.TWILIO_ACCOUNT_SID,
                "TWILIO_AUTH_TOKEN": cls.TWILIO_AUTH_TOKEN,
                "TWILIO_FROM_NUMBER": cls.TWILIO_FROM_NUMBER,
                "GEMINI_API_KEY": cls.GEMINI_API_KEY,
            }
            missing = [key for key, value in required_phase1.items() if not value]
            if missing:
                issues.append(
                    "Missing required production environment variables: "
                    + ", ".join(missing)
                )

            if cls.DRY_RUN_SMS:
                issues.append("DRY_RUN_SMS must be false in production")
            if cls.DRY_RUN_AI:
                issues.append("DRY_RUN_AI must be false in production")
            if cls.DEBUG:
                issues.append("DEBUG must be false in production")

            # Phase 2: Google Business Profile (optional for now)
            # Only validate if both are set (indicates Phase 2 is enabled)
            if cls.GOOGLE_CREDENTIALS_PATH and cls.GOOGLE_BUSINESS_ACCOUNT_ID:
                if not Path(cls.GOOGLE_CREDENTIALS_PATH).exists():
                    issues.append(
                        f"GOOGLE_CREDENTIALS_PATH does not exist: {cls.GOOGLE_CREDENTIALS_PATH}"
                    )

            if issues:
                raise ConfigError(" | ".join(issues))

        else:
            if cls.DRY_RUN_SMS:
                print("⚠️  SMS is in DRY_RUN mode (logs only, no actual SMS sent)")
            if not cls.TWILIO_ACCOUNT_SID or not cls.TWILIO_AUTH_TOKEN:
                issues.append("Twilio credentials missing (acceptable for local dry-run only)")
            if not cls.GEMINI_API_KEY and not cls.DRY_RUN_AI:
                issues.append("GEMINI_API_KEY missing while DRY_RUN_AI=false")

        return issues


class DevelopmentConfig(Config):
    """Development configuration"""

    DEBUG = True
    DRY_RUN_SMS = True
    DRY_RUN_AI = False  # Use real AI for testing


class TestingConfig(Config):
    """Testing configuration"""

    DATABASE_PATH = ":memory:"
    DEBUG = True
    DRY_RUN_SMS = True
    DRY_RUN_AI = True


class ProductionConfig(Config):
    """Production configuration"""

    DEBUG = False
    DRY_RUN_SMS = False
    DRY_RUN_AI = False


def get_config(env: str = None) -> Config:
    """Get configuration based on environment"""
    if env is None:
        # Default to production for Railway/PaaS if ENVIRONMENT not explicitly set
        # This makes it harder to accidentally run dev config in prod
        if os.getenv("RAILWAY_ENVIRONMENT_ID") or os.getenv("RENDER_SERVICE_ID"):
            env = "production"
        else:
            env = os.getenv("ENVIRONMENT", "development")

    if env == "production":
        return ProductionConfig()
    elif env == "testing":
        return TestingConfig()
    else:
        return DevelopmentConfig()
