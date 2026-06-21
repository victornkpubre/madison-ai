"""
assistant_schema.py
══════════════════════
Pydantic request models for the conversational and messaging endpoints
exposed by interface/api/assistant.py: chat/resume (the shared
supervisor-graph entry points), message templates, and SMTP connection.

Not part of the originally specified schema folder contents, but added
because these request bodies need a home and main.py previously defined
them inline.
"""
from pydantic import BaseModel


class ChatRequest(BaseModel):
    thread_id: str
    message:   str
    chat_id:   str = ""   # set when the message comes from a Telegram viewer


class ResumeRequest(BaseModel):
    thread_id: str
    action:    str | None  = None
    text:      str         = ""
    value:     dict | None = None


class TemplateRequest(BaseModel):
    name:    str
    channel: str = "email"
    subject: str | None = None
    body:    str


class SmtpConnectRequest(BaseModel):
    email:        str
    password:     str            # app password, not real password
    display_name: str | None = None
    smtp_host:    str | None = None   # auto-detected from domain if omitted
    smtp_port:    int = 587
    imap_host:    str | None = None   # auto-detected from domain if omitted
    imap_port:    int = 993
