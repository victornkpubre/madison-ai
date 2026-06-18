"""
application/utils/capture.py
════════════════════
TikTok LIVE chat capture — callable edition.

Same engine as the websocket version, but exposed as plain functions you call
on demand instead of a service that broadcasts. Two ways to use it:

    capture_image_b64()      -> a PNG (base64) of the chat band, for the BACKEND
                                to run the VLM on (no API key needed on client).
    capture_messages()       -> structured rows, by running the VLM HERE on the
                                client (needs ANTHROPIC_API_KEY on this machine).
    capture_usernames()      -> just the unique sender names (your audience).

Locating logic (window track -> input-bar template -> chat band ROI -> settle
gate) is unchanged. Put landmark.png (and optionally logo.png) next to the application.

Install:
    pip install mss opencv-python numpy rapidfuzz pygetwindow anthropic
    set ANTHROPIC_API_KEY=sk-ant-...     # only needed for capture_messages()
"""

import base64
import json
import os
import time
from collections import deque

import cv2
import numpy as np
import mss

try:
    import pygetwindow as gw
    HAVE_PYGETWINDOW = True
except Exception:
    HAVE_PYGETWINDOW = False

from rapidfuzz import fuzz

from app.core.config import config

try:
    from anthropic import Anthropic
    _vlm_client = Anthropic(api_key=config.anthropic_api_key) if config.anthropic_api_key else None
    _vlm_import_error = None if _vlm_client else RuntimeError("ANTHROPIC_API_KEY not set in .env")
except Exception as _e:
    _vlm_client = None
    _vlm_import_error = _e


# ── Configuration ────────────────────────────────────────────────────────────
WINDOW_TITLE_SUBSTR = "TikTok"
INPUTBAR_PATH = "landmark.png"           # required: locates the chat band
LOGO_PATH = "logo.png"                   # optional: presence confirmation

CHAT_BAND_HEIGHT = 500
MATCH_CONFIDENCE = 0.70
LOGO_CONFIDENCE = 0.55
TEMPLATE_SCALES = (0.8, 0.9, 1.0, 1.1, 1.2)

CAPTURE_SLEEP = 0.04
SETTLE_HASH_THRESHOLD = 6

DEDUP_WINDOW = 60
DEDUP_SIMILARITY = 88

VLM_MODEL = config.vlm_model
VLM_MAX_LONG_EDGE = 1100


# ── Window + capture ─────────────────────────────────────────────────────────
def get_window_bbox(title_substr=WINDOW_TITLE_SUBSTR):
    if not HAVE_PYGETWINDOW:
        return None
    try:
        wins = [w for w in gw.getAllWindows()
                if title_substr.lower() in (w.title or "").lower()
                and w.visible and w.width > 0 and w.height > 0]
    except Exception:
        return None
    if not wins:
        return None
    w = wins[0]
    return {"top": max(w.top, 0), "left": max(w.left, 0),
            "width": w.width, "height": w.height}


def _grab(bbox, sct):
    return np.array(sct.grab(bbox))[:, :, :3]


# ── Template matching / ROI ──────────────────────────────────────────────────
def _load_template(path):
    return cv2.imread(path)


def _match_template(window_img, template, scales=TEMPLATE_SCALES):
    if template is None or window_img is None:
        return None, 0.0, (0, 0)
    best_conf, best_loc, best_shape = 0.0, None, (0, 0)
    wh, ww = window_img.shape[:2]
    for s in scales:
        t = cv2.resize(template, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        th, tw = t.shape[:2]
        if th >= wh or tw >= ww:
            continue
        res = cv2.matchTemplate(window_img, t, cv2.TM_CCOEFF_NORMED)
        _, conf, _, loc = cv2.minMaxLoc(res)
        if conf > best_conf:
            best_conf, best_loc, best_shape = conf, loc, (th, tw)
    return best_loc, best_conf, best_shape


def _find_chat_roi(window_img, inputbar_tpl):
    loc, conf, shape = _match_template(window_img, inputbar_tpl)
    if loc is None or conf < MATCH_CONFIDENCE:
        return None, conf
    _, tw = shape
    x, y = loc
    cy = max(y - CHAT_BAND_HEIGHT, 0)
    return (x, cy, tw, y - cy), conf


def _logo_present(window_img, logo_tpl):
    if logo_tpl is None:
        return True
    _, conf, _ = _match_template(window_img, logo_tpl)
    return conf >= LOGO_CONFIDENCE


def _clamp_roi(roi_xywh, window_img):
    x, y, w, h = roi_xywh
    H, W = window_img.shape[:2]
    x, y = max(0, x), max(0, y)
    w, h = min(w, W - x), min(h, H - y)
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


# ── Settle gate ──────────────────────────────────────────────────────────────
def _dhash(image, hash_size=16):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (hash_size + 1, hash_size))
    return (resized[:, 1:] > resized[:, :-1]).flatten()


def _hamming(a, b):
    if a is None or b is None:
        return 10 ** 9
    return int(np.count_nonzero(a != b))


class _SettleGate:
    def __init__(self, threshold=SETTLE_HASH_THRESHOLD):
        self.threshold = threshold
        self.prev = None
        self.was_changing = False

    def ready(self, roi_img):
        h = _dhash(roi_img)
        changed = _hamming(h, self.prev) > self.threshold
        self.prev = h
        if changed:
            self.was_changing = True
            return False
        if self.was_changing:
            self.was_changing = False
            return True
        return False


# ── VLM extraction ───────────────────────────────────────────────────────────
_VLM_SYSTEM = (
    "You read text from a screenshot of a TikTok LIVE chat panel and return it as "
    "structured data. You never invent content and you never split one person's "
    "message across multiple entries or merge two people's messages into one."
)
_VLM_PROMPT = (
    "This image is the chat column of a TikTok LIVE stream. Extract every chat row "
    "you can read, top to bottom, as a JSON array. Each element has exactly these "
    'keys: "user" (display name copied exactly, or null for a system notice), '
    '"message" (the message text only, wrapped lines kept as ONE message), and '
    '"type" (one of "chat","gift","join","system"). Usernames render in a distinct '
    "color from the white message body. Output ONLY the JSON array, [] if empty."
)


def _encode_png_b64(bgr):
    h, w = bgr.shape[:2]
    long_edge = max(h, w)
    if long_edge > VLM_MAX_LONG_EDGE:
        scale = VLM_MAX_LONG_EDGE / long_edge
        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", bgr)
    if not ok:
        raise RuntimeError("failed to PNG-encode the crop")
    return base64.b64encode(buf).decode("ascii")


def _vlm_parse(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return []
    out = []
    for d in data:
        if not isinstance(d, dict):
            continue
        user = d.get("user")
        msg = (d.get("message") or "").strip()
        if not msg and not user:
            continue
        out.append({"user": (str(user).strip() or None) if user else None,
                    "text": msg, "type": d.get("type", "chat")})
    return out


def _extract_from_b64(png_b64):
    """Run the VLM on a base64 PNG. Needs ANTHROPIC_API_KEY on this machine."""
    if _vlm_client is None:
        raise RuntimeError(f"Anthropic client unavailable: {_vlm_import_error}")
    resp = _vlm_client.messages.create(
        model=VLM_MODEL, max_tokens=1024, system=_VLM_SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/png", "data": png_b64}},
            {"type": "text", "text": _VLM_PROMPT},
        ]}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return _vlm_parse(text)


# ── Internal: grab one settled chat-band crop ────────────────────────────────
def _grab_settled_roi(sct, inputbar_tpl, logo_tpl, gate, timeout):
    """Block until a settled chat frame is found, or timeout. Returns BGR or None."""
    deadline = time.time() + timeout
    cached_roi = None
    while time.time() < deadline:
        bbox = get_window_bbox() or sct.monitors[1]
        window_img = _grab(bbox, sct)
        roi_xywh, conf = _find_chat_roi(window_img, inputbar_tpl)
        if roi_xywh is None or not _logo_present(window_img, logo_tpl):
            time.sleep(CAPTURE_SLEEP)
            continue
        clamped = _clamp_roi(roi_xywh, window_img)
        if clamped is None:
            time.sleep(CAPTURE_SLEEP)
            continue
        x, y, w, h = clamped
        roi_img = window_img[y:y + h, x:x + w]
        if gate.ready(roi_img):
            return roi_img
        time.sleep(CAPTURE_SLEEP)
    return None


# ═══════════════════════════════════════════════════════════════════════════ #
# PUBLIC API — call these
# ═══════════════════════════════════════════════════════════════════════════ #
def capture_image_b64(timeout=8.0):
    """Grab one settled chat-band screenshot and return it as base64 PNG.
    No API key needed here — send this to the backend for VLM processing.
    Returns the base64 string, or None if the chat couldn't be located in time."""
    inputbar_tpl = _load_template(INPUTBAR_PATH)
    logo_tpl = _load_template(LOGO_PATH)
    gate = _SettleGate()
    with mss.mss() as sct:
        roi = _grab_settled_roi(sct, inputbar_tpl, logo_tpl, gate, timeout)
    return None if roi is None else _encode_png_b64(roi)


def capture_messages(duration=5.0, timeout=8.0):
    """Capture for `duration` seconds, running the VLM HERE on each settled frame,
    and return a deduped list of {user, text, type}. Needs ANTHROPIC_API_KEY."""
    inputbar_tpl = _load_template(INPUTBAR_PATH)
    logo_tpl = _load_template(LOGO_PATH)
    gate = _SettleGate()
    recent = deque(maxlen=DEDUP_WINDOW)
    results = []

    def is_new(key):
        for prev in recent:
            if fuzz.ratio(key, prev) >= DEDUP_SIMILARITY:
                return False
        recent.append(key)
        return True

    deadline = time.time() + duration
    with mss.mss() as sct:
        while time.time() < deadline:
            roi = _grab_settled_roi(sct, inputbar_tpl, logo_tpl, gate,
                                    timeout=max(0.5, deadline - time.time()))
            if roi is None:
                break
            try:
                for m in _extract_from_b64(_encode_png_b64(roi)):
                    if is_new(f"{m['user']}|{m['text']}"):
                        results.append({**m, "ts": time.time()})
            except Exception:
                break
    return results


def capture_usernames(duration=5.0):
    """Convenience: return just the unique sender names from chat rows."""
    seen, names = set(), []
    for m in capture_messages(duration=duration):
        u = m.get("user")
        if m.get("type") == "chat" and u and u not in seen:
            seen.add(u)
            names.append(u)
    return names


# ═══════════════════════════════════════════════════════════════════════════ #
# SLICE CAPTURE — incremental, description-focused
# ═══════════════════════════════════════════════════════════════════════════ #
# Dedup that PERSISTS across slices within one capture session, so a message
# seen in slice 1 isn't re-sent in slice 2. Reset it when a new session starts.
_session_recent = deque(maxlen=DEDUP_WINDOW)


def reset_capture_session():
    """Clear cross-slice dedup memory (call at the start of a new capture goal)."""
    _session_recent.clear()


def _extract_focused(png_b64, description=""):
    """VLM extraction, optionally focused by a description of what to look for."""
    if _vlm_client is None:
        raise RuntimeError(f"Anthropic client unavailable: {_vlm_import_error}")
    prompt = _VLM_PROMPT
    if description:
        prompt += ("\nThe creator is especially looking for: " + description +
                   ". Still extract every readable row faithfully; never invent rows.")
    resp = _vlm_client.messages.create(
        model=VLM_MODEL, max_tokens=1024, system=_VLM_SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/png", "data": png_b64}},
            {"type": "text", "text": prompt},
        ]}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return _vlm_parse(text)


def capture_slice(description="", slice_index=0, duration=1.5, timeout=6.0):
    """Capture ONE slice of the chat — a short settled window — focused by
    `description`. Returns {"messages": [...], "found": bool}.

    slice_index == 0 resets cross-slice dedup, so each new capture goal starts
    fresh. Subsequent slices (1, 2, ...) only return messages not already seen.
    `found` is False if the TikTok chat couldn't be located — the caller should
    stop the loop in that case.
    """
    if slice_index == 0:
        reset_capture_session()

    inputbar_tpl = _load_template(INPUTBAR_PATH)
    logo_tpl = _load_template(LOGO_PATH)
    gate = _SettleGate()
    rows = []

    def is_new(key):
        for prev in _session_recent:
            if fuzz.ratio(key, prev) >= DEDUP_SIMILARITY:
                return False
        _session_recent.append(key)
        return True

    deadline = time.time() + duration
    found = False
    with mss.mss() as sct:
        while time.time() < deadline:
            roi = _grab_settled_roi(sct, inputbar_tpl, logo_tpl, gate,
                                    timeout=max(0.5, deadline - time.time()))
            if roi is None:
                break
            found = True
            for m in _extract_focused(_encode_png_b64(roi), description):
                if is_new(f"{m['user']}|{m['text']}"):
                    rows.append({**m, "ts": time.time()})
    return {"messages": rows, "found": found}


# ═══════════════════════════════════════════════════════════════════════════ #
# FIELD CAPTURE — extract specific fields (username, telegram, age, location…)
# ═══════════════════════════════════════════════════════════════════════════ #
def _field_prompt(fields):
    """Build a VLM prompt that extracts a named set of fields per viewer."""
    keys = ", ".join(fields)
    lines = "\n".join(f'  "{f}" - the viewer\'s {f} if visible in their message, else null'
                      for f in fields)
    return (
        "This image is the chat column of a TikTok LIVE stream. For each chat row, "
        "extract a JSON object with EXACTLY these keys:\n"
        f"{lines}\n"
        '  "tiktok_username" - the sender\'s display name as shown\n'
        "Rules:\n"
        "- Read values only from what the viewer actually typed or what is shown; "
        "never invent a value. Use null for any field not present in that row.\n"
        "- A telegram number/handle, age, or location is usually inside the message "
        "text (e.g. 'my telegram is @joe, 24, Lagos').\n"
        f"- Only these fields matter: {keys} (plus tiktok_username).\n"
        "- Skip system/gift/join notices.\n"
        "Output ONLY a JSON array of these objects. Return [] if none readable."
    )


def _extract_fields(png_b64, fields):
    if _vlm_client is None:
        raise RuntimeError(f"Anthropic client unavailable: {_vlm_import_error}")
    resp = _vlm_client.messages.create(
        model=VLM_MODEL, max_tokens=1500, system=_VLM_SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/png", "data": png_b64}},
            {"type": "text", "text": _field_prompt(fields)},
        ]}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return []
    return [d for d in data if isinstance(d, dict)]


def _record_complete(rec, required):
    """True if every required field has a non-empty value."""
    return all((rec.get(f) not in (None, "", "null")) for f in required)


def capture_records(fields, target, require_all=True, slice_index=0,
                    duration=2.0, timeout=8.0):
    """Capture viewer records with the named `fields` until `target` records are
    collected (or this slice's time runs out). Returns:
        {"records": [...], "found": bool, "complete_count": int}

    fields        : e.g. ["tiktok_username", "telegram", "age", "location"]
    target        : how many records the creator asked for
    require_all   : if True, only count a record once ALL fields are filled
    slice_index 0 : resets cross-slice dedup so a new capture goal starts fresh
    """
    if slice_index == 0:
        reset_capture_session()

    inputbar_tpl = _load_template(INPUTBAR_PATH)
    logo_tpl = _load_template(LOGO_PATH)
    gate = _SettleGate()
    records = []
    required = fields if require_all else [fields[0]] if fields else []

    def is_new(key):
        for prev in _session_recent:
            if fuzz.ratio(key, prev) >= DEDUP_SIMILARITY:
                return False
        _session_recent.append(key)
        return True

    deadline = time.time() + duration
    found = False
    with mss.mss() as sct:
        while time.time() < deadline and len(records) < target:
            roi = _grab_settled_roi(sct, inputbar_tpl, logo_tpl, gate,
                                    timeout=max(0.5, deadline - time.time()))
            if roi is None:
                break
            found = True
            for rec in _extract_fields(_encode_png_b64(roi), fields):
                key = rec.get("tiktok_username") or json.dumps(rec, sort_keys=True)
                if not is_new(str(key)):
                    continue
                if require_all and not _record_complete(rec, required):
                    continue          # skip partial records when all fields required
                records.append(rec)
                if len(records) >= target:
                    break

    complete = sum(1 for r in records if _record_complete(r, fields))
    return {"records": records[:target], "found": found, "complete_count": complete}
