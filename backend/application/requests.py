from pydantic import BaseModel

class ChatRequest(BaseModel):
    thread_id: str
    message:   str
    chat_id:   str = ""


class ResumeRequest(BaseModel):
    thread_id: str
    action:    str | None  = None
    text:      str = ""
    value:     dict | None = None

class KnowledgeEntry(BaseModel):
    topic:   str
    content: str


class BulkKnowledgeRequest(BaseModel):
    entries: list[KnowledgeEntry]

class SignalIngestRequest(BaseModel):
    messages:   list[str]
    source:     str = "telegram"
    session_id: str = ""
