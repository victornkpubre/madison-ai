"""
application/ui/pages/chat_page.py  (v4 — assistant + slice/record capture + ask)
─────────────────────────────────────────────────────────────────────────
Talks to the creator-assistant backend (/chat, /resume):

  send a request → assistant may ask for fields/count (ask_user interrupt)
                 → assistant captures records in slices (record_screen interrupt)
                 → assistant summarises the collected records

Also keeps the viewer-reply approval bar (record-screen-unrelated interrupts).

config/settings.json:
  { "agent_url": "http://localhost:8000/chat",
    "resume_url": "http://localhost:8000/resume" }
"""
import uuid
from urllib.parse import urlsplit

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QTextEdit, QLineEdit,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import (
    QTextCursor, QTextCharFormat, QTextBlockFormat, QColor, QFont,
)

from app.core.database import CaptureDatabase
from app.core.settings import load_settings
from app.utils.db_api_worker import DbApiWorker


# ── Colour tokens (match dark.qss palette) ───────────────────────────────────
_C_USER_BG   = QColor("#313244")
_C_USER_FG   = QColor("#CDD6F4")
_C_AGENT_BG  = QColor("#252535")
_C_AGENT_FG  = QColor("#CDD6F4")
_C_LABEL_FG  = QColor("#7986CB")
_C_SYS_FG    = QColor("#6C7086")
_C_ERR_FG    = QColor("#F38BA8")
# Streamed-token fonts. Use pixel sizes so they match the HTML message
# bubbles (which use font-size:12px / 10px) exactly — a point size here
# (e.g. 12pt ≈ 16px) made streamed replies render larger than the bubbles,
# so the chat font looked non-uniform.
_FONT        = QFont("Segoe UI"); _FONT.setPixelSize(12)
_FONT_SMALL  = QFont("Segoe UI"); _FONT_SMALL.setPixelSize(10)


class ChatPage(QWidget):
    go_back       = pyqtSignal()
    request_close = pyqtSignal()
    message_sent  = pyqtSignal(str)
    data_saved    = pyqtSignal(int)

    def __init__(self, db: CaptureDatabase, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatPage")
        self.db      = db
        self._worker = None
        # Strong refs to every live QThread. self._worker / self._cap_worker are
        # only control-flow handles and get cleared from inside the workers' own
        # done/payload signals — which fire BEFORE run() returns. Dropping the
        # last Python ref there lets the GC destroy a still-running QThread
        # ("QThread: Destroyed while thread is still running" -> crash). This set
        # holds each worker alive until Qt's finished signal, which fires only
        # after run() has fully returned.
        self._threads = set()

        # ── conversation / capture state ──
        self._thread_id       = None
        self._chat_id         = ""
        self._pending         = None      # reply-approval payload
        self._edit_mode       = False
        self._resume_action   = None
        self._cap_worker      = None      # CaptureRequestWorker | None
        self._awaiting_answer = False     # next Send answers an ask_creator question
        self._stream_open     = False     # lazy stream bubble open?

        # ── continuous inspiration-hunt state ──
        # _hunt_active: the graph is currently driving a continuous hunt (set on
        # each continuous record_screen interrupt). _hunt_stop_requested: the
        # creator pressed Stop — honoured at the next safe point (when a capture
        # finishes, or when the next hunt interrupt arrives) by resuming the
        # paused graph with {"stop": True} so the backend ends the hunt cleanly
        # and presents what it has, instead of a hard abort that drops the loop.
        self._hunt_active         = False
        self._hunt_stop_requested = False

        self._build()
        self._add_onboarding_message()

    def _add_onboarding_message(self):
        self.add_agent_message(
            "Hi, I'm your Marketing Agent 👋\n\n"
            "I'm here to grow your presence. Here's what I can do:\n"
            "\n"
            "Content & ideas\n"
            "• Build content plans and ideas from your profile, content history, and audience analysis\n"
            "• Read another creator's stream or post for relevance and ideas — paste in what you see, "
            "or just point your screen at it\n"
            "\n"
            "Live capture (your own stream — TikTok, Kick, Whatnot, or Twitch)\n"
            "• Collect viewer contacts (username, Telegram, age, location)\n"
            "• Turn a session into a topic/sentiment report and surface knowledge gaps\n"
            "\n"
            "Leads & outreach\n"
            "• Add a lead manually — a referral, a DM — and I'll draft a personalized follow-up\n"
            "• Send via email or Telegram, broadcast to a list, or save reusable templates\n"
            "• You always approve a message before it sends\n"
            "\n"
            "Knowledge base\n"
            "• Save answers to common viewer questions so I can use them in replies and content"
        )
        # The CTA below depends on whether the creator profile is actually
        # empty, so it's appended as a follow-up bubble once we know — rather
        # than always showing the new-creator pitch to someone who already
        # set up their profile weeks ago.
        self._fetch_profile_for_greeting()

    def _base_url(self) -> str:
        """Derive the backend root (scheme://host:port) from agent_url."""
        agent_url = load_settings().get("agent_url", "")
        parts = urlsplit(agent_url)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
        return ""

    def _fetch_profile_for_greeting(self):
        base = self._base_url()
        if not base:
            self._add_new_creator_cta()   # no backend configured — default to the safe, generic CTA
            return
        worker = DbApiWorker(f"{base}/creator/profile")
        worker.loaded.connect(self._on_profile_status_loaded)
        worker.failed.connect(self._on_profile_status_failed)
        self._track(worker)
        worker.start()

    def _on_profile_status_loaded(self, profile: dict):
        name = (profile or {}).get("name")
        if name:
            self.add_agent_message(
                f"Welcome back, {name}! Want me to check your knowledge "
                f"gaps, draft a follow-up, or work on something else?"
            )
        else:
            self._add_new_creator_cta()

    def _on_profile_status_failed(self, _msg: str):
        # Can't tell whether the profile is set — default to the same CTA a
        # brand-new creator would see (matches check_onboarding_status()'s
        # own fallback: assume nothing is set up yet rather than guess wrong).
        self._add_new_creator_cta()

    def _add_new_creator_cta(self):
        self.add_agent_message(
            "Tell me a bit about yourself and your content to get started — "
            "or just say hi, and I'll figure out the best next step for your "
            "growth, whether that's setting you up or putting data you "
            "already have to work."
        )

    # ── Layout ─────────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._make_header())
        root.addWidget(self._hline())
        root.addWidget(self._make_chat_area(), stretch=1)
        self._approval = self._make_approval_bar()
        root.addWidget(self._approval)
        root.addWidget(self._hline())
        root.addWidget(self._make_input_row())

    def _make_header(self) -> QWidget:
        w = QWidget(); w.setObjectName("PanelHeader"); w.setFixedHeight(46)
        lay = QHBoxLayout(w); lay.setContentsMargins(8, 0, 10, 0); lay.setSpacing(6)
        back = QPushButton("←"); back.setObjectName("BackBtn")
        back.setFixedSize(28, 28); back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self._on_back)
        dot = QLabel("●"); dot.setObjectName("DotOn"); dot.setFixedWidth(14)
        title = QLabel("Marketing Agent"); title.setObjectName("PanelTitle")
        export = QPushButton("Export DB"); export.setObjectName("ExportBtn")
        export.setFixedHeight(24); export.setCursor(Qt.PointingHandCursor)
        export.clicked.connect(self._export_db)
        close = QPushButton("✕"); close.setObjectName("CloseBtn")
        close.setFixedSize(22, 22); close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.request_close)
        for widget in (back, dot, title):
            lay.addWidget(widget)
        lay.addStretch()
        lay.addWidget(export); lay.addSpacing(4); lay.addWidget(close)
        return w

    def _hline(self) -> QFrame:
        d = QFrame(); d.setFrameShape(QFrame.HLine); d.setObjectName("Divider")
        return d

    def _make_chat_area(self) -> QTextEdit:
        self._chat = QTextEdit()
        self._chat.setObjectName("ChatHistory")
        self._chat.setReadOnly(True)
        self._chat.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        return self._chat

    def _make_approval_bar(self) -> QWidget:
        w = QWidget(); w.setObjectName("ApprovalBar"); w.setFixedHeight(40)
        lay = QHBoxLayout(w); lay.setContentsMargins(8, 4, 8, 4); lay.setSpacing(6)
        self._approval_label = QLabel("Approve this reply?")
        self._approval_label.setObjectName("PanelTitle")
        approve = QPushButton("Approve"); approve.setObjectName("SendBtn")
        approve.setCursor(Qt.PointingHandCursor)
        approve.clicked.connect(lambda: self._decide("approve"))
        edit = QPushButton("Edit"); edit.setObjectName("SecondaryBtn")
        edit.setCursor(Qt.PointingHandCursor)
        edit.clicked.connect(self._start_edit)
        reject = QPushButton("Reject"); reject.setObjectName("SecondaryBtn")
        reject.setCursor(Qt.PointingHandCursor)
        reject.clicked.connect(lambda: self._decide("reject"))
        lay.addWidget(self._approval_label); lay.addStretch()
        lay.addWidget(approve); lay.addWidget(edit); lay.addWidget(reject)
        w.hide()
        return w

    def _make_input_row(self) -> QWidget:
        w = QWidget(); w.setObjectName("InputRow"); w.setFixedHeight(48)
        lay = QHBoxLayout(w); lay.setContentsMargins(8, 6, 8, 8); lay.setSpacing(6)
        self._input = QLineEdit()
        self._input.setObjectName("ChatInput")
        self._input.setPlaceholderText("e.g. capture 20 tiktok usernames and telegram numbers…")
        self._input.returnPressed.connect(self._on_send)
        self._stop_btn = QPushButton("■")
        self._stop_btn.setObjectName("SecondaryBtn")
        self._stop_btn.setFixedWidth(30); self._stop_btn.setFixedHeight(32)
        self._stop_btn.setCursor(Qt.PointingHandCursor)
        self._stop_btn.setToolTip("Stop")
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        self._stop_btn.hide()
        self._send_btn = QPushButton("Send")
        self._send_btn.setObjectName("SendBtn")
        self._send_btn.setFixedWidth(54); self._send_btn.setCursor(Qt.PointingHandCursor)
        self._send_btn.clicked.connect(self._on_send)
        lay.addWidget(self._input)
        lay.addWidget(self._stop_btn)
        lay.addWidget(self._send_btn)
        return w

    # ── Message rendering ──────────────────────────────────────────────────────
    # Friendly labels for the top-level graph nodes, used when rendering
    # 'route' trace events (see _on_flow_event below).
    _NODE_LABELS = {
        "supervisor":   "Supervisor",
        "assist_agent": "Marketing Agent",
        "idea_agent":   "Idea Generator",
        "reply_agent":  "Viewer Reply Agent",
    }

    def _on_flow_event(self, evt: dict):
        """Render the graph-trace events the backend already streams (route,
        tool_call) as small inline status lines — previously these were
        decoded by SSEWorker but had no signal to travel on, so the
        supervisor -> sub-agent handoffs and tool activity were invisible.
        node_enter / node_exit / llm_start / fastapi are still available on
        the same `event` signal for a future debug panel; not rendered here
        to avoid cluttering the chat with internal node bookkeeping."""
        etype = evt.get("type")
        if etype == "route":
            frm = self._NODE_LABELS.get(evt.get("from_node", ""), evt.get("from_node", "?"))
            to  = self._NODE_LABELS.get(evt.get("to_node", ""), evt.get("to_node", "?"))
            self._add_system(f"↳ {frm} → {to}")
        elif etype == "tool_call":
            self._add_system(f"🔧 {evt.get('name', 'tool')}")

    def _add_system(self, text: str):
        self._chat.append(
            f'<p style="text-align:center;color:#6C7086;font-size:11px;'
            f'margin:2px 0">{text}</p>'
        )

    def add_user_message(self, text: str):
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._chat.append(
            f'<p style="text-align:right;margin:6px 0">'
            f'<span style="background:#313244;color:#CDD6F4;padding:5px 10px;'
            f'border-radius:8px 8px 2px 8px;font-size:12px">{escaped}</span></p>'
        )
        self._scroll_end()

    def add_agent_message(self, text: str):
        escaped = (text.replace("&", "&amp;").replace("<", "&lt;")
                       .replace(">", "&gt;").replace("\n", "<br>"))
        self._chat.append(
            f'<p style="margin:6px 0">'
            f'<span style="color:#7986CB;font-size:10px">● </span>'
            f'<span style="background:#252535;color:#CDD6F4;padding:5px 10px;'
            f'border-radius:8px 8px 8px 2px;font-size:12px;'
            f'display:inline-block;line-height:1.5">{escaped}</span></p>'
        )
        self._scroll_end()

    # ── SSE streaming render (lazy bubble) ───────────────────────────────────────
    def _begin_stream(self):
        cursor = self._chat.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertBlock()
        label_fmt = QTextCharFormat()
        label_fmt.setForeground(_C_LABEL_FG); label_fmt.setFont(_FONT_SMALL)
        cursor.insertText("● Agent", label_fmt)
        block_fmt = QTextBlockFormat()
        block_fmt.setBackground(_C_AGENT_BG)
        block_fmt.setTopMargin(2); block_fmt.setBottomMargin(6)
        block_fmt.setLeftMargin(8); block_fmt.setRightMargin(8)
        cursor.insertBlock(block_fmt)
        self._stream_fmt = QTextCharFormat()
        self._stream_fmt.setForeground(_C_AGENT_FG); self._stream_fmt.setFont(_FONT)
        self._stream_fmt.setBackground(_C_AGENT_BG)
        self._chat.setTextCursor(cursor)
        self._chat.ensureCursorVisible()

    def _ensure_stream(self):
        """Open the agent bubble only when the first real token arrives, so the
        tool-only rounds (capture/ask) don't leave empty bubbles."""
        if not self._stream_open:
            self._begin_stream()
            self._stream_open = True

    def _on_chunk(self, text: str):
        # The hunt loop emits no tokens; the first agent text after a hunt is its
        # results summary, so the capture loop is over — Stop now aborts normally.
        self._hunt_active = False
        self._ensure_stream()
        cursor = self._chat.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text, self._stream_fmt)
        self._chat.setTextCursor(cursor)
        self._chat.ensureCursorVisible()

    def _on_stream_done(self):
        self._set_input_busy(False)
        self._worker = None

    def _on_stream_error(self, msg: str):
        cursor = self._chat.textCursor()
        cursor.movePosition(QTextCursor.End)
        err_fmt = QTextCharFormat()
        err_fmt.setForeground(_C_ERR_FG); err_fmt.setFont(_FONT_SMALL)
        cursor.insertBlock(); cursor.insertText(f"⚠ {msg}", err_fmt)
        self._chat.setTextCursor(cursor)
        self._set_input_busy(False)
        self._worker = None

    # ── Interrupt handling: capture / ask / approve ──────────────────────────────
    def _on_interrupt(self, value: dict):
        action = value.get("action")

        if action == "record_screen":
            mode = value.get("mode", "records")
            continuous = bool(value.get("continuous"))

            if continuous:
                self._hunt_active = True
                # Creator already asked to stop while the backend was between
                # shots — the graph is now paused at this interrupt, so answer
                # it with stop instead of grabbing another screenshot.
                if self._hunt_stop_requested:
                    self._finish_hunt_stop()
                    return
                found, target = value.get("relevant_found", 0), value.get("target", "?")
                self._add_system(f"● Scanning posts ({found}/{target} relevant)…")
            elif mode == "post_screenshot":
                self._add_system("● Capturing screenshot…")
            else:
                label = "chat messages" if mode == "messages" else "records"
                self._add_system(
                    f"● Capturing {label} ({value.get('have', 0)}/{value.get('target', '?')})…")
            from app.utils.capture_request_worker import CaptureRequestWorker
            self._cap_worker = CaptureRequestWorker(value)
            self._cap_worker.finished_payload.connect(self._on_capture_done)
            self._track(self._cap_worker)
            self._cap_worker.start()
            return

        if action == "ask_user":
            self.add_agent_message(value.get("question", "…"))
            self._awaiting_answer = True
            self._set_input_busy(False)
            self._input.setFocus()
            return

        # else: viewer-reply approval
        self._pending = value
        self._approval_label.setText("Approve this reply?")
        self._approval.show()

    def _on_capture_done(self, payload: dict):
        self._cap_worker = None
        # Creator pressed Stop while this slice was capturing (or during its
        # pre-capture wait) — discard the frame and end the hunt cleanly.
        if self._hunt_stop_requested or payload.get("cancelled"):
            self._finish_hunt_stop()
            return
        if "messages" in payload:
            recs, label = payload.get("messages", []), "message"
        else:
            recs, label = payload.get("records", []), "record"
        if recs:
            self._add_system(f"  +{len(recs)} {label}(s)")
        self._resume_value(payload)

    # ── Resume helpers ───────────────────────────────────────────────────────────
    def _resume_value(self, value: dict):
        """Resume a paused graph with a generic value (capture result or answer)."""
        resume_url = self._resume_url()
        self._set_input_busy(True)
        self._stream_open = False
        from app.utils.sse_worker import SSEWorker
        self._worker = SSEWorker(
            url=resume_url, message="",
            extra_payload={"thread_id": self._thread_id, "value": value})
        self._worker.chunk.connect(self._on_chunk)
        self._worker.interrupt.connect(self._on_interrupt)
        self._worker.done.connect(self._on_stream_done)
        self._worker.error.connect(self._on_stream_error)
        self._worker.flow_event.connect(self._on_flow_event)
        self._track(self._worker)
        self._worker.start()

    def _resume_url(self) -> str:
        settings   = load_settings()
        agent_url  = settings.get("agent_url", "")
        resume_url = settings.get("resume_url", "")
        if not resume_url and agent_url.endswith("/assist"):
            resume_url = agent_url[:-len("/assist")] + "/assist/resume"
        if not resume_url and agent_url.endswith("/chat"):
            resume_url = agent_url[:-len("/chat")] + "/resume"
        return resume_url

    # ── Reply-approval bar actions ───────────────────────────────────────────────
    def _decide(self, action: str):
        resume_url = self._resume_url()
        self._approval.hide(); self._pending = None
        self._resume_action = action
        self._set_input_busy(True); self._stream_open = False
        from app.utils.sse_worker import SSEWorker
        self._worker = SSEWorker(
            url=resume_url, message="",
            extra_payload={"thread_id": self._thread_id, "action": action, "text": ""})
        self._worker.done.connect(self._on_resume_done)
        self._worker.error.connect(self._on_stream_error)
        self._worker.flow_event.connect(self._on_flow_event)
        self._track(self._worker)
        self._worker.start()

    def _start_edit(self):
        self._approval.hide()
        self._input.setText((self._pending or {}).get("proposed_reply", ""))
        self._edit_mode = True
        self._input.setFocus()

    def _on_resume_done(self):
        self._set_input_busy(False); self._worker = None
        if self._resume_action == "approve":
            self._add_system("✓ Approved — delivered to the viewer.")
        elif self._resume_action == "edit":
            self._add_system("✓ Edited — delivered to the viewer.")
        else:
            self._add_system("✗ Rejected — nothing sent.")
        self._resume_action = None

    # ── Send ─────────────────────────────────────────────────────────────────────
    def _on_send(self):
        text = self._input.text().strip()
        if not text or self._worker:
            return
        self._input.clear()

        # Answering an ask_creator question?
        if self._awaiting_answer:
            self._awaiting_answer = False
            self.add_user_message(text)
            self._resume_value({"answer": text})
            return

        # Editing a proposed reply?
        if self._edit_mode:
            self._edit_mode = False
            self.add_agent_message(text)
            resume_url = self._resume_url()
            self._set_input_busy(True); self._stream_open = False
            from app.utils.sse_worker import SSEWorker
            self._worker = SSEWorker(
                url=resume_url, message="",
                extra_payload={"thread_id": self._thread_id, "action": "edit", "text": text})
            self._resume_action = "edit"
            self._worker.done.connect(self._on_resume_done)
            self._worker.error.connect(self._on_stream_error)
            self._worker.flow_event.connect(self._on_flow_event)
            self._worker.finished.connect(self._worker.deleteLater)
            self._worker.start()
            return

        # Normal new turn -> the assistant agent.
        self._hunt_active = False
        self._hunt_stop_requested = False
        self.add_user_message(text)
        self.message_sent.emit(text)
        self._set_input_busy(True); self._stream_open = False

        settings  = load_settings()
        agent_url = settings.get("agent_url", "")
        self._chat_id = settings.get("viewer_chat_id", "")
        if not agent_url:
            self._begin_stream(); self._stream_open = True
            self._on_chunk('No agent_url in config/settings.json.\n'
                           'Add: "agent_url": "http://localhost:8000/chat"')
            self._on_stream_done()
            return

        from app.utils.sse_worker import SSEWorker
        # One thread per conversation: the checkpointer keys all memory by
        # thread_id. Regenerating it each turn wiped the agent's history,
        # making it re-run the welcome and re-ask for the profile every message.
        if not self._thread_id:
            self._thread_id = str(uuid.uuid4())
        self._worker = SSEWorker(
            url=agent_url, message=text,
            extra_payload={"thread_id": self._thread_id, "chat_id": self._chat_id})
        self._worker.chunk.connect(self._on_chunk)
        self._worker.interrupt.connect(self._on_interrupt)
        self._worker.done.connect(self._on_stream_done)
        self._worker.error.connect(self._on_stream_error)
        self._worker.flow_event.connect(self._on_flow_event)
        self._track(self._worker)
        self._worker.start()

    def _on_stop_clicked(self):
        """Stop button. During a continuous inspiration hunt, stop it gracefully
        (let the backend finish and present what it collected). Any other busy
        state — a normal turn, a records/stream capture — gets the hard abort."""
        if self._hunt_active:
            self._request_hunt_stop()
        else:
            self._abort_stream()

    def _request_hunt_stop(self):
        """Creator asked to end the hunt. If a slice is capturing right now, the
        graph is paused at the hunt interrupt — cancel the grab and the
        capture-done handler resumes with stop. If nothing is capturing, the
        backend is mid-analysis and will emit one more interrupt; the flag makes
        _on_interrupt answer that one with stop instead of another screenshot."""
        if self._hunt_stop_requested:
            return
        self._hunt_stop_requested = True
        self._add_system("● Stopping the hunt — wrapping up what we found…")
        if self._cap_worker is not None:
            self._cap_worker.cancel()   # ends any slice_delay wait early

    def _finish_hunt_stop(self):
        """Resume the paused hunt with stop=True so the backend ends it cleanly
        and presents the collected results."""
        self._cap_worker = None
        self._hunt_stop_requested = False
        self._hunt_active = False
        self._resume_value({"stop": True})

    def _abort_stream(self):
        if self._worker:
            self._worker.abort()          # closes the read; finished->deleteLater cleans up
            self._add_system("Stopped.")
            self._worker = None
        if self._cap_worker:
            self._cap_worker = None
        self._hunt_active = False
        self._hunt_stop_requested = False
        self._set_input_busy(False)       # abort suppresses the done signal, so reset here

    def _track(self, worker):
        """Keep a strong ref to a worker until Qt's finished signal (fires after
        run() returns), then drop it and schedule deletion. Call before start()."""
        self._threads.add(worker)
        worker.finished.connect(lambda w=worker: self._threads.discard(w))
        worker.finished.connect(worker.deleteLater)

    def cleanup(self):
        """Stop every running worker thread and block until each finishes, so Qt
        never destroys a QThread that is still running (the
        'QThread: Destroyed while thread is still running' warning / crash on
        exit). Safe to call multiple times."""
        self._worker = None
        self._cap_worker = None
        for worker in list(self._threads):
            try:
                worker.stop()
            except Exception:
                pass
        self._threads.clear()

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _set_input_busy(self, busy: bool):
        self._input.setEnabled(not busy)
        self._send_btn.setVisible(not busy)
        self._stop_btn.setVisible(busy)
        if not busy:
            self._input.setFocus()

    def _scroll_end(self):
        self._chat.moveCursor(QTextCursor.End)

    def _on_back(self):
        if self._worker:
            self._worker.abort()
        self.go_back.emit()

    def save_capture(self, rows: list[dict]):
        n = self.db.save_batch(rows)
        self.data_saved.emit(self.db.count())
        self._add_system(f"✓ Saved {n} entr{'y' if n == 1 else 'ies'} to database.")

    def _export_db(self):
        try:
            path = self.db.export_excel()
            self._add_system(f"Exported → {path}")
        except Exception as exc:
            self._add_system(f"Export failed: {exc}")
