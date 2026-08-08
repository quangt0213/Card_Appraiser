"""Touchscreen UI: /display renders the latest scan state for the Freenove monitor."""
from __future__ import annotations

from flask import Blueprint, render_template


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

    return bp
