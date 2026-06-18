"""
application/core/config.py  (frontend)
══════════════════════════════
Loads the frontend .env once and exposes the values as a Config object.
The VLM runs on the client, so the Anthropic key lives here.

.env (in the streameye/ project root) should contain:
    ANTHROPIC_API_KEY=sk-ant-...
    VLM_MODEL=claude-haiku-4-5-20251001     # optional
"""
import os
from dotenv import load_dotenv

load_dotenv()      # reads the .env in the folder you launch the application from (or a parent)


class Config:
    def __init__(self):
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.vlm_model         = os.getenv("VLM_MODEL", "claude-haiku-4-5-20251001")


config = Config()
