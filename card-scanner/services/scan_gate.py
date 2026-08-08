"""A tiny thread-safe gate that holds a matched result until the user resumes.

Product flow: the ESP32-CAM auto-scans continuously. When a scan matches, the Pi
"holds" — it keeps showing that result and ignores further frames — until the user
taps "Scan next card" on the touchscreen (POST /resume), which re-arms scanning.

The scan route and the resume route run on different threads (worker vs request),
so access is guarded by a lock.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional


class ScanGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._held: Optional[Dict[str, Any]] = None

    def holding(self) -> bool:
        with self._lock:
            return self._held is not None

    def hold(self, result: Dict[str, Any]) -> None:
        with self._lock:
            self._held = dict(result)

    def resume(self) -> None:
        with self._lock:
            self._held = None

    def held_summary(self) -> Dict[str, Any]:
        """Minimal payload echoed back to the ESP32 while paused."""
        with self._lock:
            r = self._held or {}
            return {
                "card_name": r.get("card_name", ""),
                "price": r.get("price"),
                "held": True,
            }
