"""EasyOCR wrapper.

Design choices that keep EasyOCR usable on a Raspberry Pi 4:
  * the Reader model is loaded ONCE (lazily) and reused -- never per scan;
  * we OCR only the small title/number crops from the warped card, not the whole
    image, which is the biggest speed win;
  * import of easyocr is lazy so the rest of the app (and the test suite) doesn't
    need torch installed.
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np

from utils.logger import get_logger

log = get_logger("ocr")


class OcrService:
    def __init__(self, langs: Optional[List[str]] = None, gpu: bool = False, enabled: bool = True):
        self.langs = langs or ["en"]
        self.gpu = gpu
        self.enabled = enabled
        self._reader = None  # lazily initialized easyocr.Reader

    def _reader_instance(self):
        if self._reader is None:
            import easyocr  # heavy import, done once
            log.info("Loading EasyOCR model (langs=%s, gpu=%s)...", self.langs, self.gpu)
            self._reader = easyocr.Reader(self.langs, gpu=self.gpu)
        return self._reader

    def warmup(self) -> None:
        """Optionally pre-load the model at startup so the first scan isn't slow."""
        if self.enabled:
            try:
                self._reader_instance()
            except Exception as exc:  # pragma: no cover - depends on torch install
                log.warning("OCR warmup failed: %s", exc)

    def read(self, image: "np.ndarray") -> str:
        """Return concatenated text from an image region, or '' if OCR is off/failed."""
        if not self.enabled or image is None or image.size == 0:
            return ""
        try:
            reader = self._reader_instance()
            results = reader.readtext(image, detail=0, paragraph=True)
            return "\n".join(results)
        except Exception as exc:  # pragma: no cover
            log.warning("OCR read failed: %s", exc)
            return ""
