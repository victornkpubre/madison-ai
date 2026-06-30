"""
application/utils/capture_request_worker.py
───────────────────────────────────
Captures one slice off the GUI thread when the backend asks, then resumes
the paused graph. Always emits a payload so the graph never hangs.

Three interrupt payload shapes from the backend, distinguished by "mode":

  Lead-field capture (mode="records"):
    {"action": "record_screen", "mode": "records", "platform": "kick",
     "fields": ["tiktok_username","telegram","age","location"],
     "target": 20, "have": 8, "slice": 2, "tool_call_id": "..."}

  Raw stream-message capture (mode="messages"), for stream reports:
    {"action": "record_screen", "mode": "messages", "platform": "kick",
     "target": 50, "have": 12, "slice": 3, "tool_call_id": "..."}
    platform is one of "tiktok" (default if absent), "kick", "whatnot", "twitch".

  Single-shot post/video screenshot (mode="post_screenshot"), for analysing
  ANOTHER creator's post rather than the creator's own live chat:
    {"action": "record_screen", "mode": "post_screenshot", "platform": "tiktok",
     "tool_call_id": "..."}
    No slice/target math here — one frame, no loop. platform can be any
    string (not just the four with capture-config entries), since no
    landmark/template is needed for a full-window grab.

  The continuous inspiration hunt reuses mode="post_screenshot" but adds
  "continuous": True and a "slice_delay" (seconds) — the worker waits that
  long before grabbing so the creator has time to scroll to a fresh post.
  The first shot of a hunt carries slice_delay=0 (they're already on a post);
  later shots carry a positive delay. cancel() makes that wait return early
  (used when the creator hits Stop mid-delay) so the graph resumes promptly.
"""
import time

from PyQt5.QtCore import QThread, pyqtSignal

from app.utils import capture


class CaptureRequestWorker(QThread):
    finished_payload = pyqtSignal(dict)

    def __init__(self, request: dict, parent=None):
        super().__init__(parent)
        self.request = request or {}
        self._cancelled = False

    def run(self):
        req = self.request
        mode = req.get("mode", "records")
        slice_index = req.get("slice", 0)

        # Continuous hunt: wait slice_delay so the grab lands on a freshly
        # scrolled post, not the one we just captured. Poll in small steps so
        # a Stop (cancel()) during the wait returns at once instead of stalling
        # the whole delay. The first shot carries slice_delay=0 — no wait.
        delay = float(req.get("slice_delay", 0) or 0)
        waited = 0.0
        while waited < delay and not self._cancelled:
            step = min(0.1, delay - waited)
            time.sleep(step)
            waited += step
        if self._cancelled:
            # Don't capture — let the GUI thread resume the graph with stop.
            self.finished_payload.emit(
                {"image_b64": None, "records": [], "messages": [],
                 "found": False, "cancelled": True, "slice": slice_index})
            return

        try:
            if mode == "post_screenshot":
                # Single-shot — no slice/target accounting, unlike the two
                # modes below which loop across re-entries.
                platform = req.get("platform", "tiktok")
                result = capture.capture_post_screenshot(platform=platform)
            elif mode == "messages":
                # No per-slice target math needed here — capture_slice just
                # grabs whatever's on screen for this slice's duration, with
                # cross-slice dedup. The backend's stream_capture_node is the
                # one deciding when enough messages have accumulated overall.
                platform = req.get("platform", "tiktok")
                result = capture.capture_slice(slice_index=slice_index, platform=platform)
            else:
                fields = req.get("fields", ["tiktok_username"])
                target = int(req.get("target", 0) or 0)
                have = int(req.get("have", 0) or 0)
                remaining = max(target - have, 1)   # only need the shortfall this slice
                platform = req.get("platform", "tiktok")
                result = capture.capture_records(
                    fields=fields, target=remaining, slice_index=slice_index, platform=platform)
        except Exception as exc:
            result = {"records": [], "messages": [], "image_b64": None, "found": False, "error": str(exc)}
        result["slice"] = slice_index
        self.finished_payload.emit(result)

    def cancel(self):
        """Ask a pending slice_delay wait to return early (creator hit Stop).
        Only affects the pre-capture wait; a capture already underway can't be
        interrupted and will still emit its result."""
        self._cancelled = True

    def stop(self, wait_ms: int = 5000):
        """Block until the capture finishes, so the QThread is never destroyed
        while still running. The capture itself can't be interrupted, so this
        waits it out (then terminates as a last resort)."""
        if self.isRunning():
            if not self.wait(wait_ms):
                self.terminate()
                self.wait()
