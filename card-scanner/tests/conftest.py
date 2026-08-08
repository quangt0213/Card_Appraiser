"""Shared test fixtures. Everything runs offline: mock providers, a stub OCR, and
a fake detector so we never depend on network, EasyOCR/torch, or real photos."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.card_detector import DetectedCard  # noqa: E402


def make_jpeg(seed: int, w: int = 140, h: int = 200) -> bytes:
    """Deterministic, distinct JPEG bytes per seed."""
    import cv2
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def fake_detect(img):
    """Skip real card detection in tests: treat the whole image as the warped card."""
    return DetectedCard(warped=img, title_crop=img, number_crop=img, found_quad=True)


class StubOcr:
    """Returns fixed OCR text regardless of the image region."""
    enabled = True

    def __init__(self, text: str = "Pikachu\n58/102"):
        self.text = text

    def read(self, image) -> str:  # noqa: ARG002
        return self.text


@pytest.fixture
def schema_path() -> Path:
    return ROOT / "database" / "schema.sql"
