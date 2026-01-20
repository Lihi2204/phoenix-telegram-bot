"""Configuration management for Phoenix Telegram Bot."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self):
        # Telegram Bot
        self.telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

        # Gemini API
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        # Paths
        self.data_dir: Path = Path(os.getenv("DATA_DIR", "data"))
        self.database_path: Path = self.data_dir / "bot.db"

        # Timeouts
        self.otp_timeout_seconds: int = int(os.getenv("OTP_TIMEOUT", "300"))  # 5 minutes
        self.scraper_timeout_seconds: int = int(os.getenv("SCRAPER_TIMEOUT", "600"))  # 10 minutes

        # Playwright
        self.headless: bool = os.getenv("HEADLESS", "true").lower() == "true"

    def validate(self) -> list[str]:
        """Validate required settings. Returns list of missing fields."""
        missing = []
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        return missing


# Global settings instance
settings = Settings()
