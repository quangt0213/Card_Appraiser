"""Turn remote provider candidates + the OCR signal into a single ranked result
with a meaningful confidence score.

confidence = weighted blend of:
    number_exact   (1.0 if the collector number matches, else 0)   weight 0.5
    name_fuzz      (RapidFuzz WRatio of OCR title vs candidate)    weight 0.3
    image_score    (pHash/ORB of candidate art vs the scan, 0..1)  weight 0.2

The number is the strongest, most discriminative signal, but it can be misread --
so a number hit still has to be corroborated by name/image before it wins outright.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from providers.base import CandidateCard
from services import normalizer

W_NUMBER = 0.5
W_NAME = 0.3
W_IMAGE = 0.2


@dataclass
class RankedCandidate:
    card: CandidateCard
    confidence: float
    number_exact: bool
    name_fuzz: float
    image_score: float


def score_candidate(card: CandidateCard, ocr_title: str, ocr_number: str,
                    image_score: float = 0.0) -> RankedCandidate:
    number_exact = normalizer.number_match(ocr_number, card.collector_number)
    name_fuzz = normalizer.name_score(ocr_title, card.card_name)
    confidence = (W_NUMBER * (1.0 if number_exact else 0.0)
                  + W_NAME * name_fuzz
                  + W_IMAGE * image_score)
    return RankedCandidate(card=card, confidence=round(confidence, 4),
                           number_exact=number_exact, name_fuzz=round(name_fuzz, 4),
                           image_score=round(image_score, 4))


def rank(candidates: List[CandidateCard], ocr_title: str, ocr_number: str,
         image_scores: Optional[dict] = None) -> List[RankedCandidate]:
    image_scores = image_scores or {}
    ranked = [
        score_candidate(c, ocr_title, ocr_number, image_scores.get(c.api_id, 0.0))
        for c in candidates
    ]
    ranked.sort(key=lambda r: r.confidence, reverse=True)
    return ranked


def best(candidates: List[CandidateCard], ocr_title: str, ocr_number: str,
         image_scores: Optional[dict] = None) -> Optional[RankedCandidate]:
    ranked = rank(candidates, ocr_title, ocr_number, image_scores)
    return ranked[0] if ranked else None
