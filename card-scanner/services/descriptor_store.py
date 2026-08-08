"""Persists per-card ORB descriptors as .npz files (Tier 2 storage).

pHash is a tiny scalar kept in SQLite; ORB descriptors are larger arrays kept on
disk and referenced by path. Both are rebuildable from a cached card image.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np


class DescriptorStore:
    def __init__(self, descriptors_dir: Path):
        self.dir = Path(descriptors_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, card_id: int) -> Path:
        return self.dir / f"card_{card_id}.npz"

    def save(self, card_id: int, descriptors: "np.ndarray") -> str:
        p = self.path_for(card_id)
        np.savez_compressed(p, desc=descriptors)
        return str(p)

    def load(self, card_id: int) -> Optional["np.ndarray"]:
        p = self.path_for(card_id)
        if not p.exists():
            return None
        try:
            with np.load(p) as data:
                return data["desc"]
        except Exception:
            return None

    def exists(self, card_id: int) -> bool:
        return self.path_for(card_id).exists()
