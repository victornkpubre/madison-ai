"""
application/utils/db_api_worker.py
──────────────────────────────────
QThread that performs a single GET against the backend and emits the parsed
JSON on the Qt main thread. Used by the Database page to fetch the read-only
table views from the backend (/database/views and /database/views/{key})
without blocking the UI while the request is in flight.
"""
import requests
from PyQt5.QtCore import QThread, pyqtSignal


class DbApiWorker(QThread):
    loaded = pyqtSignal(object)   # parsed JSON body
    failed = pyqtSignal(str)      # human-readable error message

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            resp = requests.get(self.url, timeout=10)
            resp.raise_for_status()
            self.loaded.emit(resp.json())
        except requests.exceptions.ConnectionError:
            self.failed.emit("Cannot reach the backend — is the server running?")
        except requests.exceptions.Timeout:
            self.failed.emit("Request timed out.")
        except requests.exceptions.HTTPError as exc:
            self.failed.emit(f"HTTP {exc.response.status_code}")
        except Exception as exc:
            self.failed.emit(str(exc))

    def stop(self, wait_ms: int = 3000):
        """Block until the thread finishes so Qt never destroys a running
        QThread on shutdown."""
        if self.isRunning():
            if not self.wait(wait_ms):
                self.terminate()
                self.wait()
