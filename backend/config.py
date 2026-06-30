
import os
from dotenv import load_dotenv

load_dotenv()      # reads the .env in the current working dir (or a parent)


class Settings:
    def __init__(self):
        self.openai_api_key     = os.getenv("OPENAI_API_KEY", "")
        self.openai_model       = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.anthropic_api_key  = os.getenv("ANTHROPIC_API_KEY", "")
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.database_url       = os.getenv("DATABASE_URL") or None

        # Default sending account, loaded from the environment so the app
        # password lives only in .env and is never typed into the chat. When
        # both are set, composition.py registers this account as a connected
        # sender at startup, so email sends work with no in-chat connect step.
        # The app password is stored without spaces (Gmail shows it spaced).
        self.email_address      = os.getenv("EMAIL_ADDRESS", "").strip()
        self.email_app_password = os.getenv("EMAIL_APP_PASSWORD", "").replace(" ", "").strip()
        self.email_display_name = os.getenv("EMAIL_DISPLAY_NAME", "").strip()


settings = Settings()
