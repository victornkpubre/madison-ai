"""
email_client.py
═══════════════
SMTP + IMAP email integration for StreamEye.
No OAuth. No Google Cloud. No Azure app registrations.
Just an email address and an app password.

Connect once
────────────
  save_smtp_account(email, password, display_name)
  verify_smtp_credentials(email, password, smtp_host, smtp_port) → {"ok": True/False}

Send
────
  await send_smtp(account_email, to_email, subject, body) → {"ok": True/False}

Receive
───────
  await poll_imap_inbox(account_email, after_datetime) → list[dict]

Provider presets (auto-detected from email domain)
────────────────────────────────────────────────────
  @gmail.com   → smtp.gmail.com:587  /  imap.gmail.com:993
  @outlook.com → smtp.office365.com:587  /  outlook.office365.com:993
  @hotmail.com → smtp.office365.com:587  /  outlook.office365.com:993
  @yahoo.com   → smtp.mail.yahoo.com:587  /  imap.mail.yahoo.com:993
  anything else → smtp.<domain>:587  /  imap.<domain>:993

App password guides
────────────────────
  Gmail:   myaccount.google.com → Security → App passwords
  Outlook: account.microsoft.com → Security → Advanced security → App passwords
"""
from __future__ import annotations

import asyncio
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr, parsedate_to_datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import func

from backend.config import settings
from backend.domain.repository.email_repository_interface import IEmailRepository
from backend.infrastructure.database.db import get_sync_session
from backend.infrastructure.database.notification_model import EmailAccountModel

# ── in-memory store (fallback when DATABASE_URL is not set) ───────────────────
_smtp_store: dict[str, dict] = {}


# ── provider presets ──────────────────────────────────────────────────────────

SMTP_PRESETS: dict[str, dict] = {
    "gmail.com":     {"smtp_host": "smtp.gmail.com",       "smtp_port": 587,
                      "imap_host": "imap.gmail.com",        "imap_port": 993},
    "outlook.com":   {"smtp_host": "smtp.office365.com",   "smtp_port": 587,
                      "imap_host": "outlook.office365.com", "imap_port": 993},
    "hotmail.com":   {"smtp_host": "smtp.office365.com",   "smtp_port": 587,
                      "imap_host": "outlook.office365.com", "imap_port": 993},
    "live.com":      {"smtp_host": "smtp.office365.com",   "smtp_port": 587,
                      "imap_host": "outlook.office365.com", "imap_port": 993},
    "yahoo.com":     {"smtp_host": "smtp.mail.yahoo.com",  "smtp_port": 587,
                      "imap_host": "imap.mail.yahoo.com",   "imap_port": 993},
    "yahoo.co.uk":   {"smtp_host": "smtp.mail.yahoo.com",  "smtp_port": 587,
                      "imap_host": "imap.mail.yahoo.com",   "imap_port": 993},
    "icloud.com":    {"smtp_host": "smtp.mail.me.com",     "smtp_port": 587,
                      "imap_host": "imap.mail.me.com",      "imap_port": 993},
    "protonmail.com":{"smtp_host": "127.0.0.1",            "smtp_port": 1025,
                      "imap_host": "127.0.0.1",             "imap_port": 1143},
}


def get_smtp_preset(email: str) -> dict:
    """
    Return SMTP/IMAP host and port for an email address.
    Falls back to smtp.<domain>:587 / imap.<domain>:993 for unknown domains.
    """
    domain = email.lower().split("@")[-1] if "@" in email else ""
    return SMTP_PRESETS.get(domain, {
        "smtp_host": f"smtp.{domain}",
        "smtp_port": 587,
        "imap_host": f"imap.{domain}",
        "imap_port": 993,
    })


# ── credential management ─────────────────────────────────────────────────────

def save_smtp_account(email: str,
                      password: str,
                      display_name: str | None = None,
                      smtp_host: str | None    = None,
                      smtp_port: int           = 587,
                      imap_host: str | None    = None,
                      imap_port: int           = 993) -> None:
    """
    Store credentials for an email account.
    smtp_host and imap_host are auto-detected from the domain if not provided.
    """
    preset  = get_smtp_preset(email)
    record  = {
        "display_name": display_name or email.split("@")[0].capitalize(),
        "password":     password,
        "smtp_host":    smtp_host or preset["smtp_host"],
        "smtp_port":    smtp_port or preset["smtp_port"],
        "imap_host":    imap_host or preset["imap_host"],
        "imap_port":    imap_port or preset["imap_port"],
    }
    if settings.database_url:
        with get_sync_session() as s:
            s.execute(
                pg_insert(EmailAccountModel)
                .values(email=email.lower(), provider="smtp",
                        display_name=record["display_name"], access_token=record["password"],
                        smtp_host=record["smtp_host"], smtp_port=record["smtp_port"],
                        imap_host=record["imap_host"], imap_port=record["imap_port"],
                        updated_at=func.now())
                .on_conflict_do_update(
                    index_elements=["email"],
                    set_=dict(display_name=record["display_name"], access_token=record["password"],
                              smtp_host=record["smtp_host"], smtp_port=record["smtp_port"],
                              imap_host=record["imap_host"], imap_port=record["imap_port"],
                              updated_at=func.now()),
                )
            )
            s.commit()
    else:
        _smtp_store[email.lower()] = record


def get_smtp_account(email: str) -> dict | None:
    """Return stored credentials for an account, or None if not connected."""
    email = email.lower().strip()
    if settings.database_url:
        with get_sync_session() as s:
            row = s.execute(
                select(EmailAccountModel)
                .where(EmailAccountModel.email    == email,
                       EmailAccountModel.provider == "smtp")
            ).scalar_one_or_none()
        if not row:
            return None
        return {"email": row.email, "display_name": row.display_name,
                "password": row.access_token,
                "smtp_host": row.smtp_host, "smtp_port": row.smtp_port,
                "imap_host": row.imap_host, "imap_port": row.imap_port}
    data = _smtp_store.get(email)
    return {"email": email, **data} if data else None


def list_email_accounts() -> list[dict]:
    """Return all connected accounts without exposing credentials."""
    if settings.database_url:
        with get_sync_session() as s:
            rows = s.execute(
                select(EmailAccountModel.email, EmailAccountModel.provider,
                       EmailAccountModel.display_name)
                .order_by(EmailAccountModel.created_at)
            ).all()
        return [{"email": r.email, "provider": r.provider,
                 "display_name": r.display_name} for r in rows]
    return [
        {"email": email, "provider": "smtp",
         "display_name": d.get("display_name")}
        for email, d in _smtp_store.items()
    ]


# ── SMTP verification ─────────────────────────────────────────────────────────

async def verify_smtp_credentials(email: str,
                                   password: str,
                                   smtp_host: str,
                                   smtp_port: int) -> dict:
    """
    Test SMTP credentials before saving them.
    Runs the blocking smtplib call in a thread pool so it never blocks
    the async event loop.
    Returns {"ok": True} or {"ok": False, "error": "<reason>"}.
    """
    def _test():
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.login(email, password)
            return {"ok": True}
        except smtplib.SMTPAuthenticationError:
            return {"ok": False,
                    "error": "Authentication failed. Check the app password is correct."}
        except smtplib.SMTPConnectError:
            return {"ok": False,
                    "error": f"Could not connect to {smtp_host}:{smtp_port}."}
        except OSError as e:
            return {"ok": False,
                    "error": f"Network error: {e}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return await asyncio.get_event_loop().run_in_executor(None, _test)


# ── SMTP send ─────────────────────────────────────────────────────────────────

async def send_smtp(account_email: str,
                    to_email: str,
                    subject: str,
                    body: str,
                    to_name: str    = "",
                    reply_to: str   | None = None,
                    html_body: str  | None = None) -> dict:
    """
    Send an email using stored SMTP credentials.

    Supports plain text and optional HTML alternative (multipart/alternative).
    Runs the blocking smtplib calls in a thread pool.
    """
    account = get_smtp_account(account_email)
    if not account:
        return {
            "ok":    False,
            "error": f"No account connected for {account_email}. "
                     f"Connect it first via POST /email/connect."
        }

    def _send():
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = (f"{account['display_name']} <{account_email}>"
                          if account.get("display_name") else account_email)
        msg["To"]      = f"{to_name} <{to_email}>" if to_name else to_email
        if reply_to:
            msg["Reply-To"] = reply_to

        # Plain text always attached first (lowest priority in multipart/alternative)
        msg.attach(MIMEText(body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            with smtplib.SMTP(account["smtp_host"],
                              account["smtp_port"],
                              timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(account_email, account["password"])
                server.send_message(msg)
            return {"ok": True}
        except smtplib.SMTPAuthenticationError:
            return {"ok": False,
                    "error": "Authentication failed — app password may have been revoked."}
        except smtplib.SMTPRecipientsRefused:
            return {"ok": False,
                    "error": f"Recipient refused: {to_email}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return await asyncio.get_event_loop().run_in_executor(None, _send)


# ── IMAP receive (IMAPClient) ─────────────────────────────────────────────────

async def poll_imap_inbox(account_email: str,
                           after_datetime: datetime | None = None,
                           folder: str = "INBOX",
                           limit: int  = 50) -> list[dict]:
    """
    Fetch new messages using IMAPClient.

    IMAPClient advantages over stdlib imaplib:
      - Clean Pythonic API (no raw byte parsing)
      - Built-in SSL context management
      - SEARCH criteria as Python objects
      - Automatic UID handling

    after_datetime — only return messages received after this timestamp.
                     Pass the last successful poll time to avoid duplicates.
    folder         — IMAP folder name (default INBOX).
    limit          — maximum number of messages to return.

    Returns list of:
      {uid, message_id, from_email, from_name, subject, body, received_at}
    """
    account = get_smtp_account(account_email)
    if not account:
        return []

    def _fetch() -> list[dict]:
        from imapclient import IMAPClient
        from imapclient.exceptions import IMAPClientError

        results = []
        try:
            with IMAPClient(account["imap_host"],
                            port=account["imap_port"],
                            ssl=True) as client:
                client.login(account_email, account["password"])
                client.select_folder(folder, readonly=True)

                # Build search criteria
                # IMAPClient accepts criteria as a list of strings or
                # imapclient.search module objects.
                if after_datetime:
                    # SINCE is date-granular; we filter by exact time in Python
                    date_str  = after_datetime.strftime("%d-%b-%Y")
                    uids      = client.search(["SINCE", date_str])
                else:
                    uids = client.search(["ALL"])

                if not uids:
                    return []

                # Fetch the most recent `limit` UIDs
                uids = uids[-limit:]

                # Fetch headers + body in a single round trip
                messages = client.fetch(uids, ["ENVELOPE", "RFC822"])

                for uid, data in messages.items():
                    raw = data.get(b"RFC822", b"")
                    if not raw:
                        continue

                    import email as email_parser
                    msg = email_parser.message_from_bytes(raw)

                    # Parse received timestamp
                    date_header = msg.get("Date", "")
                    try:
                        received = parsedate_to_datetime(date_header)
                        if received.tzinfo is None:
                            received = received.replace(tzinfo=timezone.utc)
                    except Exception:
                        received = datetime.now(timezone.utc)

                    # Skip messages older than after_datetime (SINCE is date-only)
                    if after_datetime and received <= after_datetime:
                        continue

                    # Extract plain-text body (prefer text/plain over text/html)
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                charset = part.get_content_charset() or "utf-8"
                                body    = part.get_payload(
                                    decode=True).decode(charset, errors="replace")
                                break
                        # Fall back to HTML stripped of tags if no plain text
                        if not body:
                            for part in msg.walk():
                                if part.get_content_type() == "text/html":
                                    charset   = part.get_content_charset() or "utf-8"
                                    html      = part.get_payload(
                                        decode=True).decode(charset, errors="replace")
                                    import re
                                    body = re.sub(r"<[^>]+>", " ", html).strip()
                                    break
                    else:
                        charset = msg.get_content_charset() or "utf-8"
                        body    = msg.get_payload(
                            decode=True).decode(charset, errors="replace")

                    # Parse from address
                    from_header              = msg.get("From", "")
                    from_name, from_addr     = parseaddr(from_header)

                    results.append({
                        "uid":        uid,
                        "message_id": msg.get("Message-ID", ""),
                        "from_email": from_addr.lower(),
                        "from_name":  from_name,
                        "subject":    msg.get("Subject", ""),
                        "body":       body.strip(),
                        "received_at": received,
                    })

        except IMAPClientError as e:
            # Log but don't raise — polling failures are non-fatal
            print(f"[imap] {account_email}: {e}")
        except Exception as e:
            print(f"[imap] unexpected error for {account_email}: {e}")

        return results

    return await asyncio.get_event_loop().run_in_executor(None, _fetch)


# ── inbox search (IMAPClient) ─────────────────────────────────────────────────

async def search_imap_inbox(account_email: str,
                             subject_contains: str | None = None,
                             from_address: str | None     = None,
                             since: datetime | None       = None,
                             folder: str                  = "INBOX",
                             limit: int                   = 20) -> list[dict]:
    """
    Search the inbox by subject, sender, or date using IMAP SEARCH.

    Useful for finding replies to specific outbound messages without
    fetching the entire inbox.
    """
    account = get_smtp_account(account_email)
    if not account:
        return []

    def _search() -> list[dict]:
        from imapclient import IMAPClient
        from imapclient.exceptions import IMAPClientError

        criteria: list = []
        if since:
            criteria += ["SINCE", since.strftime("%d-%b-%Y")]
        if from_address:
            criteria += ["FROM", from_address]
        if subject_contains:
            criteria += ["SUBJECT", subject_contains]
        if not criteria:
            criteria = ["ALL"]

        results = []
        try:
            with IMAPClient(account["imap_host"],
                            port=account["imap_port"],
                            ssl=True) as client:
                client.login(account_email, account["password"])
                client.select_folder(folder, readonly=True)

                uids = client.search(criteria)
                if not uids:
                    return []

                uids     = uids[-limit:]
                messages = client.fetch(uids, ["RFC822"])

                for uid, data in messages.items():
                    raw = data.get(b"RFC822", b"")
                    if not raw:
                        continue

                    import email as email_parser
                    msg        = email_parser.message_from_bytes(raw)
                    from_hdr   = msg.get("From", "")
                    fname, fadr = parseaddr(from_hdr)

                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                charset = part.get_content_charset() or "utf-8"
                                body    = part.get_payload(
                                    decode=True).decode(charset, errors="replace")
                                break
                    else:
                        charset = msg.get_content_charset() or "utf-8"
                        body    = msg.get_payload(
                            decode=True).decode(charset, errors="replace")

                    results.append({
                        "uid":        uid,
                        "message_id": msg.get("Message-ID", ""),
                        "from_email": fadr.lower(),
                        "from_name":  fname,
                        "subject":    msg.get("Subject", ""),
                        "body":       body.strip(),
                    })

        except IMAPClientError as e:
            print(f"[imap search] {account_email}: {e}")

        return results

    return await asyncio.get_event_loop().run_in_executor(None, _search)


# ── IEmailRepository adapter ────────────────────────────────────────────────
# Thin wrapper so NotificationService depends on the interface, not this
# module directly. The flat functions above stay public and untouched —
# interface/api/assistant.py's POST /email/poll endpoint still calls
# poll_imap_inbox directly, which is out of scope for this interface.

class EmailRepository(IEmailRepository):

    def get_smtp_preset(self, email: str) -> dict:
        return get_smtp_preset(email)

    async def verify_smtp_credentials(self, email: str, password: str,
                                      smtp_host: str, smtp_port: int) -> dict:
        return await verify_smtp_credentials(email, password, smtp_host, smtp_port)

    def save_smtp_account(self, email: str, password: str,
                          display_name: str | None = None,
                          smtp_host: str | None = None, smtp_port: int = 587,
                          imap_host: str | None = None, imap_port: int = 993) -> None:
        save_smtp_account(email, password, display_name,
                          smtp_host, smtp_port, imap_host, imap_port)

    def get_smtp_account(self, email: str) -> dict | None:
        return get_smtp_account(email)

    def list_email_accounts(self) -> list[dict]:
        return list_email_accounts()

    async def send_smtp(self, account_email: str, to_email: str, subject: str, body: str,
                        to_name: str = "", reply_to: str | None = None,
                        html_body: str | None = None) -> dict:
        return await send_smtp(account_email, to_email, subject, body,
                               to_name, reply_to, html_body)


email_repository = EmailRepository()
