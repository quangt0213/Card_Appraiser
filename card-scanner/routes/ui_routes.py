"""Touchscreen UI + debug monitor.

- /display : the kiosk home screen that the Freenove touchscreen shows.
- /         : a simple result page.
- /debug    : a browser-friendly monitor (same theme as /display) that also shows
               the most recent image the ESP32-CAM actually sent, plus all the
               recognition details. Open it from any computer at
               http://<pi-ip>:5000/debug to aim/focus the camera and debug scans.
- /debug/state   : JSON of the current display state + newest image metadata.
- /debug/latest.jpg: the newest non-empty received frame.
"""
from __future__ import annotations

import glob
import os
import time

from flask import Blueprint, abort, jsonify, render_template, send_file


def _newest_scan(scans_dir) -> str | None:
    """Newest non-empty JPEG in the scans dir (skips 0-byte/failed captures)."""
    files = sorted(glob.glob(os.path.join(str(scans_dir), "*.jpg")),
                   key=os.path.getmtime, reverse=True)
    for f in files:
        try:
            if os.path.getsize(f) > 0:
                return f
        except OSError:
            continue
    return None


def build_ui_blueprint(ctx) -> Blueprint:
    bp = Blueprint("ui", __name__)

    @bp.get("/display")
    def display():
        state = ctx.display.read()
        return render_template("display.html", state=state)

    @bp.get("/")
    def index():
        state = ctx.display.read()
        return render_template("result.html", state=state)

    # ---- debug monitor (for a computer browser) ----
    @bp.get("/debug")
    def debug():
        return render_template("debug.html")

    @bp.get("/debug/state")
    def debug_state():
        info = dict(ctx.display.read())
        f = _newest_scan(ctx.config.scans_dir)
        if f:
            info["image_file"] = os.path.basename(f)
            info["image_bytes"] = os.path.getsize(f)
            info["image_age_s"] = int(time.time() - os.path.getmtime(f))
        else:
            info["image_file"] = None
        return jsonify(info)

    @bp.get("/debug/latest.jpg")
    def debug_latest():
        f = _newest_scan(ctx.config.scans_dir)
        if not f:
            abort(404)
        resp = send_file(f, mimetype="image/jpeg")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    return bp
