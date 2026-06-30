"""
diagnose_capture.py
═══════════════════
Standalone, no-VLM diagnostic for the LIVE chat capture pipeline. Run it with
your stream OPEN and visible on the primary monitor to find out WHICH gate is
failing when capture returns "0 messages":

    1. window     — is a window whose title contains the platform name found?
    2. input-bar  — does landmark.png match the chat input bar at >= 0.70?
    3. logo       — (soft, TikTok only) does logo.png match? not a blocker.
    4. settle/ROI — can a chat-band ROI be carved out at all?

It reuses the REAL functions from app.utils.capture, so what it reports is what
the app actually sees — no API key needed (it never calls the VLM).

Run from the frontend/windows folder (the one with main.py):

    python diagnose_capture.py            # TikTok (default)
    python diagnose_capture.py kick       # or kick / whatnot / twitch

Debug images are written next to this script:
    diag_window.png   — exactly what was grabbed (the window, or full monitor)
    diag_roi.png      — the chat-band crop the pipeline would feed the VLM
"""
import os
import sys

import cv2
import mss

from app.utils import capture as cap

# Window titles can carry emoji/non-cp1252 chars; the Windows console is often
# cp1252 and would crash on print. Force a tolerant UTF-8 stdout.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

try:
    import pygetwindow as gw
except Exception:
    gw = None

_OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def _list_all_window_titles():
    """Every non-empty visible window title — helps spot the case where the
    stream IS open but its title doesn't contain the platform name (e.g. a
    browser tab), which makes get_window_bbox fall back to the whole monitor."""
    if gw is None:
        print("  (pygetwindow unavailable — cannot list windows)")
        return
    titles = []
    for w in gw.getAllWindows():
        t = (w.title or "").strip()
        if t and getattr(w, "visible", True) and w.width > 0 and w.height > 0:
            titles.append(f"{t!r}  ({w.width}x{w.height} @ {w.left},{w.top})")
    if not titles:
        print("  (no visible windows reported)")
    for t in titles:
        print(f"    - {t}")


def main():
    platform = (sys.argv[1] if len(sys.argv) > 1 else cap.DEFAULT_PLATFORM).strip().lower()
    try:
        pcfg = cap._platform_cfg(platform)
    except ValueError as e:
        print(e)
        return 2

    title_substr = pcfg["window_title_substr"]
    print(f"=== capture diagnostic: platform={platform} (window title ~ {title_substr!r}) ===\n")

    print("[1] Visible windows on screen:")
    _list_all_window_titles()

    # --- template assets ---
    inputbar_tpl = cap._load_template(pcfg["inputbar_path"])
    logo_tpl = cap._load_template(pcfg["logo_path"]) if pcfg["logo_path"] else None
    print(f"\n[2] Templates (from {cap._ASSETS_DIR}):")
    print(f"    input-bar {pcfg['inputbar_path']}: "
          f"{'loaded ' + str(inputbar_tpl.shape) if inputbar_tpl is not None else 'MISSING / unreadable'}")
    if pcfg["logo_path"]:
        print(f"    logo      {pcfg['logo_path']}: "
              f"{'loaded ' + str(logo_tpl.shape) if logo_tpl is not None else 'MISSING / unreadable'}")
    else:
        print("    logo: (none for this platform)")
    if inputbar_tpl is None:
        print("\n>>> input-bar template missing — capture cannot work. Stop here.")
        return 1

    # --- grab the window (or full monitor fallback) ---
    win_bbox = cap.get_window_bbox(title_substr)
    print(f"\n[3] Window match for {title_substr!r}: "
          f"{'FOUND ' + str(win_bbox) if win_bbox else 'NOT found -> grabbing whole primary monitor'}")

    with mss.mss() as sct:
        bbox = win_bbox or sct.monitors[1]
        window_img = cap._grab(bbox, sct)
    print(f"    grabbed image: {window_img.shape[1]}x{window_img.shape[0]}")
    cv2.imwrite(os.path.join(_OUT_DIR, "diag_window.png"), window_img)
    print("    saved diag_window.png")

    # --- input-bar match, per scale ---
    print(f"\n[4] Input-bar template match (need >= {cap.MATCH_CONFIDENCE:.2f}):")
    best = 0.0
    for s in cap.TEMPLATE_SCALES:
        t = cv2.resize(inputbar_tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        th, tw = t.shape[:2]
        if th >= window_img.shape[0] or tw >= window_img.shape[1]:
            print(f"    scale {s:>4}: template larger than grab — skipped")
            continue
        res = cv2.matchTemplate(window_img, t, cv2.TM_CCOEFF_NORMED)
        _, conf, _, _ = cv2.minMaxLoc(res)
        best = max(best, conf)
        print(f"    scale {s:>4}: conf={conf:.3f}{'   <-- PASS' if conf >= cap.MATCH_CONFIDENCE else ''}")
    print(f"    best input-bar conf = {best:.3f} -> {'PASS' if best >= cap.MATCH_CONFIDENCE else 'FAIL'}")

    # Annotate WHERE the best match landed (even if below threshold) so we can
    # see whether landmark.png is finding the real input bar or junk elsewhere.
    loc, _bconf, (bth, btw) = cap._match_template(window_img, inputbar_tpl)
    annotated = window_img.copy()
    if loc is not None:
        bx, by = loc
        cv2.rectangle(annotated, (bx, by), (bx + btw, by + bth), (0, 0, 255), 3)
        band_top = max(by - pcfg["chat_band_height"], 0)
        cv2.rectangle(annotated, (bx, band_top), (bx + btw, by), (0, 255, 0), 3)
        print(f"    best match at x={bx}, y={by} (red=input-bar, green=chat band it would read)")
    cv2.imwrite(os.path.join(_OUT_DIR, "diag_match.png"), annotated)
    print("    saved diag_match.png")

    # --- logo match (soft) ---
    if logo_tpl is not None:
        _, logo_conf, _ = cap._match_template(window_img, logo_tpl)
        print(f"\n[5] Logo match (soft, ref {cap.LOGO_CONFIDENCE:.2f}): conf={logo_conf:.3f} "
              f"-> {'above ref' if logo_conf >= cap.LOGO_CONFIDENCE else 'below ref (no longer blocks capture)'}")

    # --- ROI carve-out ---
    roi_xywh, conf = cap._find_chat_roi(window_img, inputbar_tpl, pcfg["chat_band_height"])
    roi_crop = None
    print(f"\n[6] Chat-band ROI: ", end="")
    if roi_xywh is None:
        print(f"could NOT locate (best conf {conf:.3f} < {cap.MATCH_CONFIDENCE:.2f}).")
        print("    -> This is why capture returns 0. The chat input bar wasn't found,")
        print("       so there's no anchor to crop the chat band above it.")
    else:
        clamped = cap._clamp_roi(roi_xywh, window_img)
        if clamped is None:
            print("located but clamped to empty (off-screen). ")
        else:
            x, y, w, h = clamped
            roi_crop = window_img[y:y + h, x:x + w]
            cv2.imwrite(os.path.join(_OUT_DIR, "diag_roi.png"), roi_crop)
            print(f"located at {clamped}, conf={conf:.3f}. Saved diag_roi.png")
            print("    -> Open diag_roi.png: it should show the chat messages. If it shows")
            print("       the wrong region, landmark.png needs to be re-grabbed for your screen.")

    # --- VLM extraction: the step the real capture does but this script skipped ---
    # This is what actually turns the ROI into messages. If detection passes but
    # capture still returns 0, the failure is almost always HERE.
    print("\n[7] VLM extraction (the step the app runs on each frame):")
    if cap._vlm_client is None:
        print(f"    VLM client UNAVAILABLE -> {cap._vlm_import_error}")
        print("    -> THIS is why capture returns 0. The ROI is found fine, but the")
        print("       client can't run the VLM (usually ANTHROPIC_API_KEY missing from")
        print("       frontend/windows/.env). capture_slice raises, the worker swallows")
        print("       it as found=False, and the agent reports 'no chat found'.")
    elif roi_crop is None:
        print("    skipped — no ROI to extract from (see [6]).")
    else:
        print(f"    model={cap.VLM_MODEL} — calling the VLM on diag_roi.png ...")
        try:
            rows = cap._extract_focused(cap._encode_png_b64(roi_crop), "", pcfg["display_name"])
            print(f"    VLM returned {len(rows)} row(s).")
            for r in rows[:8]:
                print(f"      - [{r.get('type')}] {r.get('user')}: {r.get('text')}")
            if not rows:
                print("    -> VLM ran but read no rows. Check diag_roi.png actually shows chat text.")
        except Exception as e:
            print(f"    VLM CALL FAILED -> {type(e).__name__}: {e}")
            print("    -> THIS is why capture returns 0 (bad model id, auth, or network).")
            print("       The app hits the same error and swallows it as found=False.")

    print("\n=== done. Look at diag_window.png / diag_match.png / diag_roi.png. ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
