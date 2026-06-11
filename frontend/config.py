
import os
from dotenv import load_dotenv

load_dotenv()      # reads the .env in the folder you launch the app from (or a parent)


class Config:
    def __init__(self):
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.vlm_model         = os.getenv("VLM_MODEL", "claude-haiku-4-5-20251001")


config = Config()
