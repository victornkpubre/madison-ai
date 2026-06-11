
import os
from dotenv import load_dotenv

load_dotenv()      # reads the .env in the current working dir (or a parent)


class Settings:
    def __init__(self):
        self.openai_api_key     = os.getenv("OPENAI_API_KEY", "")
        self.openai_model       = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.database_url       = os.getenv("DATABASE_URL") or None


settings = Settings()
