"""The orchestrator. Ties the whole scan together:

    save -> detect/warp -> LOCAL match (pHash + ORB tie-break)
         -> [if weak] OCR title+number -> RapidFuzz normalize
         -> identity providers -> rank -> price (recent sales) -> persist

All collaborators are injected, so tests can wire mock providers / a stub OCR and
run the full pipeline offline. app.py wires the real implementations.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from providers.base import CandidateCard, PriceProvider
from services import candidate_ranker, normalizer
from services.card_detector import detect as default_detect
from services.image_matcher import (ImageMatcher, LocalCard, MatchResult,
                                     compute_orb_descriptors, compute_phash_int)
from services.pricing_service import PricingService
from utils.image_utils import decode_jpeg
from utils.logger import get_logger

log = get_logger("pipeline")


@dataclass
class PipelineDeps:
    repository: object
    storage: object
    matcher: ImageMatcher
    ocr: object
    identity_providers: List[object]
    pricing: PricingService
    descriptor_store: object
    display: Optional[object] = None
    detect: Callable = default_detect
    local_threshold: float = 0.72
    remote_threshold: float = 0.60
    ocr_enabled: bool = True


class ScanPipeline:
    def __init__(self, deps: PipelineDeps):
        self.d = deps
        self.index: List[LocalCard] = []
        self.refresh_index()

    # ---- in-memory index (Issue #7: avoid per-scan DB scans) ----
    def refresh_index(self) -> None:
        rows = self.d.repository.load_index()
        self.index = [LocalCard(card_id=cid, phash=ph) for cid, ph, _ in rows if ph is not None]
        log.info("loaded local index: %d cards", len(self.index))

    def _add_to_index(self, card_id: int, phash: int) -> None:
        self.index.append(LocalCard(card_id=card_id, phash=phash))

    # ---- main entry ----
    def process(self, image_bytes: bytes) -> dict:
        t0 = time.time()
        path, digest, is_new = self.d.storage.save_scan(image_bytes)

        img = decode_jpeg(image_bytes)
        if img is None:
            return self._finalize(self._no_match(reason="undecodable image"), str(path), "")

        det = self.d.detect(img)
        warped = det.warped

        # --- LOCAL match first (OpenCV-first, cheap signal) ---
        local: MatchResult = self.d.matcher.match(warped, self.index)
        if local.card_id is not None and local.score >= self.d.local_threshold:
            card = self.d.repository.get_card(local.card_id)
            if card:
                quote = self.d.pricing.get_price(_card_to_candidate(card), card_db_id=local.card_id)
                result = {
                    "matched": True, "card_name": card["card_name"], "game": card["game"],
                    "set_name": card["set_name"], "collector_number": card["collector_number"],
                    "price": quote.value, "currency": quote.currency,
                    "price_basis": quote.basis, "price_as_of": quote.as_of,
                    "recent_sales": quote.sales,
                    "confidence": round(local.score, 4), "source": "local_db",
                    "match_method": local.method, "ocr_text": "", "db_id": local.card_id,
                }
                return self._finalize(result, str(path), "")

        # --- OCR fallback ---
        if not (self.d.ocr_enabled and getattr(self.d.ocr, "enabled", True)):
            return self._finalize(self._no_match(reason="no local match; OCR disabled"), str(path), "")

        raw_title = self.d.ocr.read(det.title_crop)
        raw_number = self.d.ocr.read(det.number_crop)
        raw_all = f"{raw_title}\n{raw_number}".strip()
        title = normalizer.extract_title(raw_title) or normalizer.extract_title(raw_all)
        number = normalizer.extract_collector_number(raw_number) or normalizer.extract_collector_number(raw_all)

        # --- identity providers ---
        candidates: List[CandidateCard] = []
        for prov in self.d.identity_providers:
            try:
                candidates.extend(prov.search(title, number=number, limit=20))
            except Exception as exc:  # noqa: BLE001
                log.warning("provider %s failed: %s", getattr(prov, "name", prov), exc)
        candidates = normalizer.dedupe_candidates(candidates)

        if not candidates:
            return self._finalize(self._no_match(reason="no candidates", ocr_text=raw_all), str(path), raw_all)

        ranked = candidate_ranker.best(candidates, title, number)
        if ranked is None or ranked.confidence < self.d.remote_threshold:
            res = self._no_match(reason="low confidence", ocr_text=raw_all)
            res["confidence"] = round(ranked.confidence, 4) if ranked else 0.0
            if ranked:
                res["best_guess"] = ranked.card.card_name
            return self._finalize(res, str(path), raw_all)

        # --- accept remote match: persist so future scans hit locally ---
        card = ranked.card
        scan_phash = compute_phash_int(warped)
        card_id = self.d.repository.upsert_card(card, phash=scan_phash)
        try:
            desc = compute_orb_descriptors(warped)
            if desc is not None:
                dpath = self.d.descriptor_store.save(card_id, desc)
                self.d.repository.set_descriptor_path(card_id, dpath)
        except Exception as exc:  # noqa: BLE001
            log.warning("descriptor save failed: %s", exc)
        self._add_to_index(card_id, scan_phash)

        quote = self.d.pricing.get_price(card, card_db_id=card_id)
        result = {
            "matched": True, "card_name": card.card_name, "game": card.game,
            "set_name": card.set_name, "collector_number": card.collector_number,
            "price": quote.value, "currency": quote.currency,
            "price_basis": quote.basis, "price_as_of": quote.as_of,
            "recent_sales": quote.sales,
            "confidence": ranked.confidence, "source": "remote_api",
            "match_method": "ocr+provider", "ocr_text": raw_all, "db_id": card_id,
            "name_fuzz": ranked.name_fuzz, "number_exact": ranked.number_exact,
        }
        elapsed = round((time.time() - t0) * 1000)
        log.info("scan matched %s (%.2f, %s) in %dms", card.card_name, ranked.confidence, result["source"], elapsed)
        return self._finalize(result, str(path), raw_all)

    # ---- helpers ----
    def _no_match(self, *, reason: str = "", ocr_text: str = "") -> dict:
        return {
            "matched": False, "card_name": "", "game": "", "set_name": "",
            "collector_number": "", "price": None, "currency": "USD",
            "confidence": 0.0, "source": "none", "match_method": "none",
            "ocr_text": ocr_text, "db_id": None, "reason": reason,
        }

    def _finalize(self, result: dict, image_path: str, ocr_text: str) -> dict:
        result.setdefault("image_path", image_path)
        result["image_path"] = image_path
        # write scan history
        try:
            self.d.repository.add_scan(
                matched=bool(result.get("matched")), card_id=result.get("db_id"),
                card_name=result.get("card_name", ""), game=result.get("game", ""),
                confidence=float(result.get("confidence", 0) or 0), source=result.get("source", "none"),
                price=result.get("price"), ocr_text=result.get("ocr_text", ocr_text),
                image_path=image_path,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("scan_history write failed: %s", exc)
        # update touchscreen display
        if self.d.display is not None:
            try:
                self.d.display.update(result)
            except Exception as exc:  # noqa: BLE001
                log.warning("display update failed: %s", exc)
        return result


def _card_to_candidate(card: dict) -> CandidateCard:
    return CandidateCard(
        game=card.get("game", ""), card_name=card.get("card_name", ""),
        set_name=card.get("set_name", ""), collector_number=card.get("collector_number", ""),
        rarity=card.get("rarity", ""), source=card.get("api_source", ""),
        api_id=card.get("api_id", ""),
    )
