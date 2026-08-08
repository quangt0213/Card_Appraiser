"""SD-card-friendly file handling: hash-dedupe uploads, save into the right tier,
copy confirmed remote art into the reusable image cache."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from utils.image_utils import sha256_bytes
from utils.logger import get_logger

log = get_logger("storage")


class StorageManager:
    def __init__(self, scans_dir: Path, card_images_dir: Path, candidate_temp_dir: Path):
        self.scans_dir = Path(scans_dir)
        self.card_images_dir = Path(card_images_dir)
        self.candidate_temp_dir = Path(candidate_temp_dir)
        for d in (self.scans_dir, self.card_images_dir, self.candidate_temp_dir):
            d.mkdir(parents=True, exist_ok=True)

    def save_scan(self, data: bytes) -> Tuple[Path, str, bool]:
        """Save an uploaded JPEG, deduplicated by content hash.
        Returns (path, sha256, was_new)."""
        digest = sha256_bytes(data)
        existing = next(self.scans_dir.glob(f"*_{digest[:16]}.jpg"), None)
        if existing is not None:
            return existing, digest, False
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        path = self.scans_dir / f"scan_{ts}_{digest[:16]}.jpg"
        path.write_bytes(data)
        return path, digest, True

    def promote_card_image(self, temp_path: Path, card_id: int) -> Optional[Path]:
        """Copy a confirmed candidate image into the long-lived image cache."""
        src = Path(temp_path)
        if not src.exists():
            return None
        dst = self.card_images_dir / f"card_{card_id}{src.suffix or '.jpg'}"
        shutil.copy2(src, dst)
        return dst
