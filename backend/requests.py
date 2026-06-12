from pydantic import BaseModel

# ── request bodies ────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    thread_id: str
    chat_id: str
    message: str


class AssistRequest(BaseModel):
    thread_id: str
    message: str


class ResumeRequest(BaseModel):
    thread_id: str
    action: str | None = None
    text: str = ""
    value: dict | None = None


# ── SSE helper ────────────────