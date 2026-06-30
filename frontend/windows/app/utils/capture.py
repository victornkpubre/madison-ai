"""
application/utils/capture.py
════════════════════
Multi-platform LIVE chat capture — callable edition. Supports TikTok, Kick,
Whatnot, and Twitch (see PLATFORMS below) — pass platform="kick" etc. to any
public function; defaults to "tiktok" everywhere for backward compatibility.

Same engine as the websocket version, but exposed as plain functions you call
on demand instead of a service that broadcasts. Two ways to use it:

    capture_image_b64()      -> a PNG (base64) of the chat band, for the BACKEND
                                to run the VLM on (no API key needed on client).
    capture_messages()       -> structured rows, by running the VLM HERE on the
                                client (needs ANTHROPIC_API_KEY on this machine).
    capture_usernames()      -> just the unique sender names (your audience).

Locating logic (window track -> input-bar template -> chat band ROI -> settle
gate) is unchanged per platform. Each platform needs its OWN landmark image
next to this file (landmark.png for TikTok, landmark_kick.png, etc.) — template
matching is pixel-pattern correlation, not generalized UI detection, so one
template can't cover platforms with visually distinct chat input bars. A
platform's logo template, when present, is a SOFT signal scored for diagnostics
only — it no longer gates capture (None = no logo to score). The settle gate is
relaxed: a busy chat that never stops scrolling falls back to its latest located
frame rather than capturing nothing. Each slice logs a one-line diagnostic
(window found? input-bar/logo confidence? settled?) so a "0 messages" result
explains which gate broke.

Install:
    pip install mss opencv-python numpy rapidfuzz pygetwindow anthropic
    set ANTHROPIC_API_KEY=sk-ant-...     # only needed for capture_messages()
"""

import base64
import json
import logging
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

logger = logging.getLogger(__name__)

try:
    from anthropic import Anthropic
    _vlm_client = Anthropic(api_key=config.anthropic_api_key) if config.anthropic_api_key else None
    _vlm_import_error = None if _vlm_client else RuntimeError("ANTHROPIC_API_KEY not set in .env")
except Exception as _e:
    _vlm_client = None
    _vlm_import_error = _e


# ── Configuration ────────────────────────────────────────────────────────────
# Each platform's chat input bar looks visually distinct, so each gets its own
# landmark template — cv2.matchTemplate is pixel-pattern correlation, not a
# generalized UI detector, so one template can't cover multiple platforms.
# logo_path is a SOFT signal: when present, its match confidence is recorded
# for diagnostics but it no longer GATES capture (a low logo match used to
# block TikTok entirely). None = no logo template to score at all.
PLATFORMS = {
    "tiktok": {
        "display_name": "TikTok",
        "window_title_substr": "TikTok",
        "inputbar_path": "landmark.png",
        "logo_path": "logo.png",
        "chat_band_height": 500,
    },
    "kick": {
        "display_name": "Kick",
        "window_title_substr": "Kick",
        "inputbar_path": "landmark_kick.png",
        "logo_path": None,
        "chat_band_height": 500,
    },
    "whatnot": {
        "display_name": "Whatnot",
        "window_title_substr": "Whatnot",
        "inputbar_path": "landmark_whatnot.png",
        "logo_path": None,
        "chat_band_height": 500,
    },
    "twitch": {
        "display_name": "Twitch",
        "window_title_substr": "Twitch",
        "inputbar_path": "landmark_twitch.png",
        "logo_path": None,
        "chat_band_height": 500,
    },
}
DEFAULT_PLATFORM = "tiktok"


def _platform_cfg(platform):
    key = (platform or DEFAULT_PLATFORM).strip().lower()
    cfg = PLATFORMS.get(key)
    if cfg is None:
        raise ValueError(f"Unknown platform {platform!r}. Known: {', '.join(PLATFORMS)}")
    return cfg


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
def get_window_bbox(title_substr):
    """Bounding box of the best ON-SCREEN window whose title contains
    `title_substr`. Minimized windows can't be screen-grabbed — Windows parks
    them at ~(-32000, -32000) — so they're skipped; otherwise the first match
    might be a minimized stream and capture would read garbage. When several
    windows match, the largest visible one wins, so a tiny tray/helper window
    doesn't beat the actual stream."""
    if not HAVE_PYGETWINDOW:
        return None
    try:
        candidates = []
        for w in gw.getAllWindows():
            if title_substr.lower() not in (w.title or "").lower():
                continue
            if not w.visible or getattr(w, "isMinimized", False):
                continue
            if w.width <= 0 or w.height <= 0:
                continue
            if w.left <= -10000 or w.top <= -10000:   # parked off-screen / minimized
                continue
            candidates.append(w)
    except Exception:
        return None
    if not candidates:
        return None
    w = max(candidates, key=lambda c: c.width * c.height)
    return {"top": max(w.top, 0), "left": max(w.left, 0),
            "width": w.width, "height": w.height}


def _grab(bbox, sct):
    return np.array(sct.grab(bbox))[:, :, :3]


# ── Template matching / ROI ──────────────────────────────────────────────────
# Resolve landmark/logo paths relative to THIS file's directory, not the
# process's current working directory — a bare relative filename like
# "landmark.png" only loads if the app happens to be launched with CWD set
# to this exact folder, which nothing in this codebase guarantees.
_ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))


def _asset_path(filename):
    return filename if os.path.isabs(filename) else os.path.join(_ASSETS_DIR, filename)


def _load_template(path):
    return cv2.imread(_asset_path(path))


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


def _find_chat_roi(window_img, inputbar_tpl, chat_band_height):
    loc, conf, shape = _match_template(window_img, inputbar_tpl)
    if loc is None or conf < MATCH_CONFIDENCE:
        return None, conf
    _, tw = shape
    x, y = loc
    cy = max(y - chat_band_height, 0)
    return (x, cy, tw, y - cy), conf


# Outcomes that mean "got no usable frame" — logged at WARNING so they reach
# stderr even when the app configures no logging handlers (the root logger's
# lastResort handler only emits WARNING and above). Successful outcomes log at
# INFO, which stays quiet unless the app opts into verbose logging.
_FAILED_OUTCOMES = {"no-chat-located", "timeout"}


def _log_capture_diag(title_substr, diag, outcome):
    """Emit one line explaining how a slice ended, so a failed capture says
    WHICH gate broke (window / input-bar match / logo / settle) instead of a
    bare "0 messages". LOGO_CONFIDENCE is logged as a reference threshold even
    though the logo no longer gates capture."""
    level = logging.WARNING if outcome in _FAILED_OUTCOMES else logging.INFO
    logger.log(
        level,
        "capture[%s] outcome=%s window_found=%s inputbar_conf=%.2f (need %.2f) "
        "logo_conf=%.2f (ref %.2f) settled=%s frames=%d",
        title_substr, outcome, diag["window_found"],
        diag["best_inputbar_conf"], MATCH_CONFIDENCE,
        diag["best_logo_conf"], LOGO_CONFIDENCE,
        diag["settled"], diag["frames"],
    )


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
    "You read text from a screenshot of a livestream chat panel and return it as "
    "structured data. You never invent content and you never split one person's "
    "message across multiple entries or merge two people's messages into one."
)


def _vlm_prompt(platform_label="TikTok"):
    return (
        f"This image is the chat column of a {platform_label} LIVE stream. Extract "
        "every chat row you can read, top to bottom, as a JSON array. Each element "
        'has exactly these keys: "user" (display name copied exactly, or null for a '
        'system notice), "message" (the message text only, wrapped lines kept as ONE '
        'message), and "type" (one of "chat","gift","join","system"). Usernames '
        "render in a distinct color from the white message body. Output ONLY the "
        "JSON array, [] if empty."
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


def _extract_from_b64(png_b64, platform_label="TikTok"):
    """Run the VLM on a base64 PNG. Needs ANTHROPIC_API_KEY on this machine."""
    if _vlm_client is None:
        raise RuntimeError(f"Anthropic client unavailable: {_vlm_import_error}")
    resp = _vlm_client.messages.create(
        model=VLM_MODEL, max_tokens=1024, system=_VLM_SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/png", "data": png_b64}},
            {"type": "text", "text": _vlm_prompt(platform_label)},
        ]}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return _vlm_parse(text)


# ── Internal: grab one settled chat-band crop ────────────────────────────────
def _grab_settled_roi(sct, inputbar_tpl, logo_tpl, gate, timeout,
                      window_title_substr, chat_band_height,
                      allow_unsettled=True):
    """Block until a settled chat frame is found, or timeout. Returns BGR or None.

    Relaxed settle gate: a busy LIVE chat can scroll every frame and never
    "settle" within `timeout`, which used to yield nothing at all. When
    `allow_unsettled` is set we instead fall back to the most recent frame
    whose chat ROI we could locate, so a constantly-moving chat still produces
    data. The logo template is now a SOFT signal — its confidence is recorded
    for diagnostics but does not gate capture (it previously blocked TikTok
    whenever the logo match dipped below LOGO_CONFIDENCE)."""
    deadline = time.time() + timeout
    last_roi = None
    diag = {"window_found": False, "best_inputbar_conf": 0.0,
            "best_logo_conf": 0.0, "settled": False, "frames": 0}
    while time.time() < deadline:
        win_bbox = get_window_bbox(window_title_substr)
        diag["window_found"] = diag["window_found"] or win_bbox is not None
        window_img = _grab(win_bbox or sct.monitors[1], sct)
        diag["frames"] += 1

        roi_xywh, conf = _find_chat_roi(window_img, inputbar_tpl, chat_band_height)
        diag["best_inputbar_conf"] = max(diag["best_inputbar_conf"], conf)
        if logo_tpl is not None:
            _, logo_conf, _ = _match_template(window_img, logo_tpl)
            diag["best_logo_conf"] = max(diag["best_logo_conf"], logo_conf)

        if roi_xywh is None:
            time.sleep(CAPTURE_SLEEP)
            continue
        clamped = _clamp_roi(roi_xywh, window_img)
        if clamped is None:
            time.sleep(CAPTURE_SLEEP)
            continue
        x, y, w, h = clamped
        roi_img = window_img[y:y + h, x:x + w]
        last_roi = roi_img            # remember for the unsettled fallback
        if gate.ready(roi_img):
            diag["settled"] = True
            _log_capture_diag(window_title_substr, diag, "settled")
            return roi_img
        time.sleep(CAPTURE_SLEEP)

    # Timed out without a settled frame.
    if allow_unsettled and last_roi is not None:
        _log_capture_diag(window_title_substr, diag, "unsettled-fallback")
        return last_roi
    _log_capture_diag(window_title_substr, diag,
                      "no-chat-located" if last_roi is None else "timeout")
    return None


# ═══════════════════════════════════════════════════════════════════════════ #
# PUBLIC API — call these
# ═══════════════════════════════════════════════════════════════════════════ #
def capture_image_b64(timeout=8.0, platform=DEFAULT_PLATFORM):
    """Grab one settled chat-band screenshot and return it as base64 PNG.
    No API key needed here — send this to the backend for VLM processing.
    Returns the base64 string, or None if the chat couldn't be located in time."""
    cfg = _platform_cfg(platform)
    inputbar_tpl = _load_template(cfg["inputbar_path"])
    logo_tpl = _load_template(cfg["logo_path"]) if cfg["logo_path"] else None
    gate = _SettleGate()
    with mss.mss() as sct:
        roi = _grab_settled_roi(sct, inputbar_tpl, logo_tpl, gate, timeout,
                                cfg["window_title_substr"], cfg["chat_band_height"])
    return None if roi is None else _encode_png_b64(roi)


def capture_messages(duration=5.0, timeout=8.0, platform=DEFAULT_PLATFORM):
    """Capture for `duration` seconds, running the VLM HERE on each settled frame,
    and return a deduped list of {user, text, type}. Needs ANTHROPIC_API_KEY."""
    cfg = _platform_cfg(platform)
    inputbar_tpl = _load_template(cfg["inputbar_path"])
    logo_tpl = _load_template(cfg["logo_path"]) if cfg["logo_path"] else None
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
                                    timeout=max(0.5, deadline - time.time()),
                                    window_title_substr=cfg["window_title_substr"],
                                    chat_band_height=cfg["chat_band_height"])
            if roi is None:
                break
            try:
                for m in _extract_from_b64(_encode_png_b64(roi), cfg["display_name"]):
                    if is_new(f"{m['user']}|{m['text']}"):
                        results.append({**m, "ts": time.time()})
            except Exception:
                break
    return results


def capture_usernames(duration=5.0, platform=DEFAULT_PLATFORM):
    """Convenience: return just the unique sender names from chat rows."""
    seen, names = set(), []
    for m in capture_messages(duration=duration, platform=platform):
        u = m.get("user")
        if m.get("type") == "chat" and u and u not in seen:
            seen.add(u)
            names.append(u)
    return names


# ═══════════════════════════════════════════════════════════════════════════ #
# POST SCREENSHOT — single-shot, full window, no chat-band cropping
# ═══════════════════════════════════════════════════════════════════════════ #
# Deliberately bypasses everything above built for the live-chat overlay:
# no landmark/logo template, no _find_chat_roi crop, no _SettleGate. Those
# all exist to isolate one small, constantly-scrolling region inside a much
# bigger window. A post/video page (caption, hashtags, engagement counts,
# comments) is the opposite case — there's no sub-region to isolate, the
# WHOLE window is the useful content, and it's one static frame, not a feed
# that needs a "wait until it stops moving" gate.
def capture_post_screenshot(platform=DEFAULT_PLATFORM):
    """Grab ONE full-window screenshot for vision analysis of another
    creator's post/video page. Returns {"image_b64": str|None, "found": bool}
    — found=False means the window couldn't be located (falls back to the
    primary monitor, but flags that the platform's window specifically
    wasn't seen, so the caller can tell the creator rather than silently
    analysing whatever happened to be on screen).

    platform: looked up in PLATFORMS for its display_name (used as the
    window-title substring) when known; any other string is title-cased and
    used directly, so this works for platforms with no capture-config entry
    at all (e.g. "instagram") since no template/landmark is needed here.
    """
    try:
        window_title_substr = _platform_cfg(platform)["display_name"]
    except ValueError:
        window_title_substr = (platform or DEFAULT_PLATFORM).strip().title()

    with mss.mss() as sct:
        bbox = get_window_bbox(window_title_substr)
        img = _grab(bbox or sct.monitors[1], sct)

    found = bbox is not None
    logger.log(logging.INFO if found else logging.WARNING,
               "capture_post_screenshot[%s] window_found=%s", window_title_substr, found)
    return {"image_b64": _encode_png_b64(img), "found": found}


# ═══════════════════════════════════════════════════════════════════════════ #
# SLICE CAPTURE — incremental, description-focused
# ═══════════════════════════════════════════════════════════════════════════ #
# Dedup that PERSISTS across slices within one capture session, so a message
# seen in slice 1 isn't re-sent in slice 2. Reset it when a new session starts.
_session_recent = deque(maxlen=DEDUP_WINDOW)


def reset_capture_session():
    """Clear cross-slice dedup memory (call at the start of a new capture goal)."""
    _session_recent.clear()


def _extract_focused(png_b64, description="", platform_label="TikTok"):
    """VLM extraction, optionally focused by a description of what to look for."""
    if _vlm_client is None:
        raise RuntimeError(f"Anthropic client unavailable: {_vlm_import_error}")
    prompt = _vlm_prompt(platform_label)
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


def capture_slice(description="", slice_index=0, duration=1.5, timeout=5.0,
                  platform=DEFAULT_PLATFORM):
    """Capture ONE slice of the chat — a short settled window — focused by
    `description`. Returns {"messages": [...], "found": bool}.

    `timeout` is how long to WAIT for the chat window to appear on screen (a
    LIVE can take a few seconds to load); `duration` is how long to keep
    collecting frames once it's found. These are separate budgets — a slow
    window no longer eats the collection time.

    slice_index == 0 resets cross-slice dedup, so each new capture goal starts
    fresh. Subsequent slices (1, 2, ...) only return messages not already seen.
    `found` is False if the chat couldn't be located within `timeout` — the
    caller should stop the loop in that case (which also covers a platform with
    chat disabled, popped out, or otherwise not on screen — not just TikTok).
    platform: one of PLATFORMS — "tiktok" (default), "kick", "whatnot", "twitch".
    """
    if slice_index == 0:
        reset_capture_session()

    cfg = _platform_cfg(platform)
    inputbar_tpl = _load_template(cfg["inputbar_path"])
    logo_tpl = _load_template(cfg["logo_path"]) if cfg["logo_path"] else None
    gate = _SettleGate()
    rows = []

    def is_new(key):
        for prev in _session_recent:
            if fuzz.ratio(key, prev) >= DEDUP_SIMILARITY:
                return False
        _session_recent.append(key)
        return True

    found = False
    deadline = None        # set once the window is found, to bound collection
    with mss.mss() as sct:
        while True:
            # Wait up to `timeout` for the window the first time; afterwards,
            # only collect until `duration` from first sighting has elapsed.
            budget = timeout if not found else (deadline - time.time())
            if found and budget <= 0:
                break
            roi = _grab_settled_roi(sct, inputbar_tpl, logo_tpl, gate,
                                    timeout=max(0.5, budget),
                                    window_title_substr=cfg["window_title_substr"],
                                    chat_band_height=cfg["chat_band_height"])
            if roi is None:
                break
            if not found:
                found = True
                deadline = time.time() + duration
            for m in _extract_focused(_encode_png_b64(roi), description, cfg["display_name"]):
                if is_new(f"{m['user']}|{m['text']}"):
                    rows.append({**m, "ts": time.time()})
    return {"messages": rows, "found": found}


# ═══════════════════════════════════════════════════════════════════════════ #
# FIELD CAPTURE — extract specific fields (username, telegram, age, location…)
# ═══════════════════════════════════════════════════════════════════════════ #
def _field_prompt(fields, platform_label="TikTok"):
    """Build a VLM prompt that extracts a named set of fields per viewer."""
    keys = ", ".join(fields)
    lines = "\n".join(f'  "{f}" - the viewer\'s {f} if visible in their message, else null'
                      for f in fields)
    return (
        f"This image is the chat column of a {platform_label} LIVE stream. For each "
        "chat row, extract a JSON object with EXACTLY these keys:\n"
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


def _extract_fields(png_b64, fields, platform_label="TikTok"):
    if _vlm_client is None:
        raise RuntimeError(f"Anthropic client unavailable: {_vlm_import_error}")
    resp = _vlm_client.messages.create(
        model=VLM_MODEL, max_tokens=1500, system=_VLM_SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/png", "data": png_b64}},
            {"type": "text", "text": _field_prompt(fields, platform_label)},
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
                    duration=2.0, timeout=8.0, platform=DEFAULT_PLATFORM):
    """Capture viewer records with the named `fields` until `target` records are
    collected (or this slice's time runs out). Returns:
        {"records": [...], "found": bool, "complete_count": int}

    fields        : e.g. ["tiktok_username", "telegram", "age", "location"]
    target        : how many records the creator asked for
    require_all   : if True, only count a record once ALL fields are filled
    slice_index 0 : resets cross-slice dedup so a new capture goal starts fresh
    platform      : one of PLATFORMS — defaults to "tiktok"
    """
    if slice_index == 0:
        reset_capture_session()

    cfg = _platform_cfg(platform)
    inputbar_tpl = _load_template(cfg["inputbar_path"])
    logo_tpl = _load_template(cfg["logo_path"]) if cfg["logo_path"] else None
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
                                    timeout=max(0.5, deadline - time.time()),
                                    window_title_substr=cfg["window_title_substr"],
                                    chat_band_height=cfg["chat_band_height"])
            if roi is None:
                break
            found = True
            for rec in _extract_fields(_encode_png_b64(roi), fields, cfg["display_name"]):
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
