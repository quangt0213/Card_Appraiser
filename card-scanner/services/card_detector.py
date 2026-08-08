"""Find the card in an ESP32-CAM photo, perspective-correct it, and crop the
regions we OCR (title bar + bottom collector-number strip).

This runs BEFORE matching/OCR and is the single biggest accuracy win: it removes
background, tilt, and framing so everything downstream sees a clean, upright card.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

# Canonical warped card size (portrait). Roughly the 63x88mm card aspect ratio.
CANON_W = 480
CANON_H = 670
CARD_ASPECT = 63.0 / 88.0  # width / height ~= 0.716


@dataclass
class DetectedCard:
    warped: "np.ndarray"          # upright, canonical-size BGR card
    title_crop: "np.ndarray"      # top strip (name)
    number_crop: "np.ndarray"     # bottom strip (collector number / set)
    found_quad: bool              # True if a real card contour was found & warped


def _order_quad(pts: "np.ndarray") -> "np.ndarray":
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]      # top-left
    rect[2] = pts[np.argmax(s)]      # bottom-right
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]      # top-right
    rect[3] = pts[np.argmax(d)]      # bottom-left
    return rect


def _find_card_quad(gray: "np.ndarray"):
    import cv2
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    img_area = gray.shape[0] * gray.shape[1]
    for cnt in sorted(contours, key=cv2.contourArea, reverse=True)[:6]:
        area = cv2.contourArea(cnt)
        if area < 0.10 * img_area:      # ignore tiny contours
            continue
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype("float32")
    return None


def detect(img: "np.ndarray") -> DetectedCard:
    """Detect + warp. Falls back to a plain resize if no 4-point card is found,
    so the pipeline still runs on a tightly-cropped photo."""
    import cv2
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    quad = _find_card_quad(gray)

    if quad is not None:
        rect = _order_quad(quad)
        dst = np.array([[0, 0], [CANON_W - 1, 0],
                        [CANON_W - 1, CANON_H - 1], [0, CANON_H - 1]], dtype="float32")
        M = cv2.getPerspectiveTransform(rect, dst)
        warped = cv2.warpPerspective(img, M, (CANON_W, CANON_H))
        found = True
    else:
        warped = cv2.resize(img, (CANON_W, CANON_H), interpolation=cv2.INTER_AREA)
        found = False

    title_crop = warped[0:int(CANON_H * 0.16), :]
    number_crop = warped[int(CANON_H * 0.86):, :]
    return DetectedCard(warped=warped, title_crop=title_crop,
                        number_crop=number_crop, found_quad=found)
