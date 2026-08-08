"""Small OpenCV/numpy helpers. cv2 is imported lazily so modules that only need
hashing or IO don't force the OpenCV import at collection time."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import numpy as np


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def decode_jpeg(data: bytes) -> Optional["np.ndarray"]:
    """Decode raw image bytes to a BGR ndarray, or None if not a valid image."""
    import cv2
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


def to_gray(img: "np.ndarray") -> "np.ndarray":
    import cv2
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def resize_max(img: "np.ndarray", max_side: int = 1000) -> "np.ndarray":
    import cv2
    h, w = img.shape[:2]
    scale = max_side / float(max(h, w))
    if scale >= 1.0:
        return img
    return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def is_valid_jpeg(data: bytes) -> bool:
    # JPEG SOI marker; cheap sanity check before decoding.
    return len(data) > 3 and data[0:2] == b"\xff\xd8"
