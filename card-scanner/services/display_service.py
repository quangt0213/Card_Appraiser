"""Writes the latest scan state to a JSON file that the /display touchscreen page reads."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class DisplayService:
    def __init__(self, state_file: Path):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    def update(self, result: Dict[str, Any]) -> None:
        payload = dict(result)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        # atomic write so /display never reads a half-written file
        tmp = tempfile.NamedTemporaryFile("w", delete=False, dir=str(self.state_file.parent),
                                          encoding="utf-8")
        try:
            json.dump(payload, tmp, ensure_ascii=False)
            tmp.flush()
            tmp.close()
            Path(tmp.name).replace(self.state_file)
        finally:
            if Path(tmp.name).exists():
                try:
                    Path(tmp.name).unlink()
                except OSError:
                    pass

    def read(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {"matched": False, "message": "No scans yet."}
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"matched": False, "message": "No scans yet."}
