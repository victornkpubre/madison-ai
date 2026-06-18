"""
application/utils/sse_worker.py
────────────────────────
QThread that consumes a Server-Sent Events stream and emits one signal per
text chunk so the Qt main thread can render it safely.

In addition to the streaming formats below, it understands the StreamEye
backend's typed events:
    data: {"type": "token",     "content": "..."}   -> chunk
    data: {"type": "interrupt", "value":   {...}}    -> interrupt   (NEW)
    data: {"type": "done"}                            -> end of stream

Other supported formats:
  1. LangGraph astream_events  data: {"event":"on_chat_model_stream","data":{"chunk":{"content":"..."}}}
  2. Simple content key        data: {"content": "..."}
  3. Token key                 data: {"token": "..."}
  4. OpenAI-compatible delta   data: {"choices":[{"delta":{"content":"..."}}]}
  5. Plain-text chunk          data: <raw text>
Stream ends on:  data: [DONE]  OR  data: {"type":"done"}  OR  connection close.
"""
import json
import requests
from PyQt5.QtCore import QThread, pyqtSignal


class SSEWorker(QThread):
    chunk     = pyqtSignal(str)    # one text fragment — append to the bubble
    done      = pyqtSignal()       # stream finished cleanly
    error     = pyqtSignal(str)    # error message
    interrupt = pyqtSignal(dict)   # NEW: backend paused for human approval

    def __init__(self,
                 url:     str,
                 message: str,
                 history: list | None = None,
                 extra_payload: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self.url           = url
        self.message       = message
        self.history       = history or []
        self.extra_payload = extra_payload or {}
        self._abort        = False

    # ── Thread entry point ─────────────────────────────────────────────────────

    def run(self):
        payload = {
            "message": self.message,
            "history": self.history,
            **self.extra_payload,         # carries thread_id / chat_id / action / text
        }
        try:
            with requests.post(
                self.url,
                json=payload,
                headers={"Accept": "text/event-stream"},
                stream=True,
                timeout=60,
            ) as resp:
                resp.raise_for_status()
                for raw in resp.iter_lines():
                    if self._abort:
                        break
                    line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                    if not line:
                        continue                    # blank line (SSE keepalive)
                    if not line.startswith("data:"):
                        continue                    # skip comment / event lines
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break

                    # ── typed StreamEye events first ──────────────────────────
                    evt = None
                    try:
                        evt = json.loads(data_str)
                    except json.JSONDecodeError:
                        evt = None
                    if isinstance(evt, dict):
                        if evt.get("type") == "interrupt":
                            self.interrupt.emit(evt.get("value", {}))
                            continue
                        if evt.get("type") == "done":
                            break

                    # ── fall back to the generic chunk parser ────────────────
                    text = self._parse(data_str)
                    if text:
                        self.chunk.emit(text)

        except requests.exceptions.ConnectionError:
            self.error.emit("Cannot reach the agent — is your FastAPI server running?")
        except requests.exceptions.Timeout:
            self.error.emit("Request timed out.")
        except requests.exceptions.HTTPError as exc:
            self.error.emit(f"HTTP {exc.response.status_code}: {exc.response.text[:120]}")
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.done.emit()

    # ── Payload parsing ────────────────────────────────────────────────────────

    def _parse(self, data_str: str) -> str:
        """Return the text fragment from one SSE data line, or '' to skip."""
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return data_str                         # raw text chunk

        event = data.get("event", "")
        if event == "on_chat_model_stream":
            return data.get("data", {}).get("chunk", {}).get("content", "")
        if event:
            return ""                               # other named LangGraph events
        if "content" in data:                       # our token events land here
            return data["content"]
        if "token" in data:
            return data["token"]
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("delta", {}).get("content", "")
        return ""

    # ── Control ────────────────────────────────────────────────────────────────

    def abort(self):
        self._abort = True
