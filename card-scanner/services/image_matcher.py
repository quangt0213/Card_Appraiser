"""OpenCV-first matching, structured as the cascade you approved:

  1. pHash (perceptual hash) against an in-memory index  -> cheap, O(N), first pass
  2. ORB feature match                                   -> tie-break on a small shortlist

pHash uses Hamming distance with a threshold (NOT exact match) because a lit/foil
scan drifts from clean art. ORB only re-ranks the top-K pHash candidates, so we
never run the expensive matcher across the whole database.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np


@dataclass
class LocalCard:
    """An entry in the in-memory index (mirrors a row in `cards`)."""
    card_id: int
    phash: int                       # 64-bit perceptual hash as int
    descriptors: Optional["np.ndarray"] = None  # ORB descriptors, lazily loaded


@dataclass
class MatchResult:
    card_id: Optional[int]
    score: float                     # 0..1 confidence
    method: str                      # "phash", "orb", or "none"
    phash_distance: Optional[int] = None


def compute_phash_int(image: "np.ndarray") -> int:
    """64-bit perceptual hash of a BGR/gray image, computed natively with OpenCV's
    DCT (no external imagehash dependency). Classic pHash: DCT of a 32x32 gray
    image, keep the top-left 8x8 low frequencies, threshold each against their
    median (excluding the DC term)."""
    import cv2
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(small)
    low = dct[:8, :8].flatten()
    med = float(np.median(low[1:]))     # ignore the DC coefficient at index 0
    bits = low > med
    value = 0
    for b in bits:
        value = (value << 1) | int(bool(b))
    return value


def compute_orb_descriptors(image: "np.ndarray", nfeatures: int = 500) -> Optional["np.ndarray"]:
    import cv2
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    orb = cv2.ORB_create(nfeatures=nfeatures)
    _, desc = orb.detectAndCompute(gray, None)
    return desc


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _orb_similarity(d1: "np.ndarray", d2: "np.ndarray") -> float:
    """Fraction of 'good' BF-Hamming matches, 0..1."""
    import cv2
    if d1 is None or d2 is None or len(d1) == 0 or len(d2) == 0:
        return 0.0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    try:
        knn = bf.knnMatch(d1, d2, k=2)
    except cv2.error:
        return 0.0
    good = 0
    total = 0
    for pair in knn:
        if len(pair) < 2:
            continue
        m, n = pair
        total += 1
        if m.distance < 0.75 * n.distance:   # Lowe's ratio test
            good += 1
    if total == 0:
        return 0.0
    return good / float(min(len(d1), len(d2)))


class ImageMatcher:
    def __init__(self, phash_max_distance: int = 10, orb_shortlist: int = 5,
                 descriptor_loader=None):
        self.phash_max_distance = phash_max_distance
        self.orb_shortlist = orb_shortlist
        # callable(card_id) -> descriptors ndarray | None  (usually DescriptorStore.load)
        self.descriptor_loader = descriptor_loader

    def match(self, scan: "np.ndarray", index: Sequence[LocalCard]) -> MatchResult:
        if not index:
            return MatchResult(card_id=None, score=0.0, method="none")

        scan_phash = compute_phash_int(scan)

        # --- pass 1: pHash Hamming distance across the whole (in-memory) index ---
        scored = sorted(
            ((c, _hamming(scan_phash, c.phash)) for c in index),
            key=lambda t: t[1],
        )
        best_card, best_dist = scored[0]
        # map distance (0 best .. 64 worst) to a 0..1 score
        phash_score = max(0.0, 1.0 - best_dist / 64.0)

        # If the top pHash hit is comfortably close, accept it.
        if best_dist <= self.phash_max_distance:
            return MatchResult(card_id=best_card.card_id, score=phash_score,
                               method="phash", phash_distance=best_dist)

        # --- pass 2: ORB tie-break over the pHash shortlist ---
        scan_desc = compute_orb_descriptors(scan)
        best_orb = 0.0
        best_orb_id: Optional[int] = None
        for cand, dist in scored[: self.orb_shortlist]:
            desc = cand.descriptors
            if desc is None and self.descriptor_loader is not None:
                desc = self.descriptor_loader(cand.card_id)
            sim = _orb_similarity(scan_desc, desc)
            if sim > best_orb:
                best_orb, best_orb_id = sim, cand.card_id

        if best_orb_id is not None and best_orb > 0.0:
            # Blend a little pHash proximity into the ORB score so both signals count.
            blended = 0.7 * best_orb + 0.3 * phash_score
            return MatchResult(card_id=best_orb_id, score=round(blended, 4),
                               method="orb", phash_distance=best_dist)

        return MatchResult(card_id=best_card.card_id, score=round(phash_score, 4),
                           method="phash", phash_distance=best_dist)
