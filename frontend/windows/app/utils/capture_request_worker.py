"""
application/utils/capture_request_worker.py
───────────────────────────────────
Captures one slice of viewer RECORDS off the GUI thread when the backend asks,
then resumes the paused graph. Always emits a payload so the graph never hangs.

Interrupt payload from the backend:
    {"action": "record_screen", "mode": "records",
     "fields": ["tiktok_username","telegram","age","location"],
     "target": 20, "have": 8, "slice": 2, "tool_call_id": "..."}
"""
from PyQt5.QtCore import QThread, pyqtSignal

from app.utils import capture


class CaptureRequestWorker(QThread):
    finished_payload = pyqtSignal(dict)

    def __init__(self, request: dict, parent=None):
        super().__init__(parent)
        self.request = request or {}

    def run(self):
        req = self.request
        fields = req.get("fields", ["tiktok_username"])
        target = int(req.get("target", 0) or 0)
        have = int(req.get("have", 0) or 0)
        slice_index = req.get("slice", 0)
        remaining = max(target - have, 1)        # only need the shortfall this slice
        try:
            result = capture.capture_records(
                fields=fields, target=remaining, slice_index=slice_index)
        except Exception as exc:
            result = {"records": [], "found": False, "error": str(exc)}
        result["slice"] = slice_index
        self.finished_payload.emit(result)

    def stop(self, wait_ms: int = 5000):
        """Block until the capture finishes, so the QThread is never destroyed
        while still running. The capture itself can't be interrupted, so this
        waits it out (then terminates as a last resort)."""
        if self.isRunning():
            if not self.wait(wait_ms):
                self.terminate()
                self.wait()
