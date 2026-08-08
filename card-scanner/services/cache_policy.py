"""Retention / eviction rules for the storage tiers. Pure helpers so they're testable."""
from __future__ import annotations

import time
from pathlib import Path
from typing import List, Tuple


def dir_size_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())


def expired_files(path: Path, ttl_seconds: float) -> List[Path]:
    now = time.time()
    out = []
    for f in Path(path).rglob("*"):
        if f.is_file() and f.name != ".gitkeep" and (now - f.stat().st_mtime) > ttl_seconds:
            out.append(f)
    return out


def lru_eviction_plan(path: Path, max_bytes: int) -> List[Path]:
    """Return files to delete (oldest-accessed first) to get under max_bytes."""
    files: List[Tuple[float, int, Path]] = []
    for f in Path(path).rglob("*"):
        if f.is_file() and f.name != ".gitkeep":
            st = f.stat()
            files.append((st.st_atime, st.st_size, f))
    total = sum(sz for _, sz, _ in files)
    if total <= max_bytes:
        return []
    files.sort(key=lambda t: t[0])  # oldest access first
    to_delete: List[Path] = []
    for _, sz, f in files:
        if total <= max_bytes:
            break
        to_delete.append(f)
        total -= sz
    return to_delete
