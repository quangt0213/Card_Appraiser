"""Identity provider backed by the TCGAPIs catalog.

Resolves cleaned OCR text (and, when available, a collector number) into
CandidateCard rows. The category id per game is resolved once and cached.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from providers.base import CandidateCard, IdentityProvider
from providers.tcgapis_client import TCGAPIsClient, TCGAPIsError
from utils.logger import get_logger

log = get_logger("identity.tcgapis")

# TCGAPIs category names as they appear in /api/v2/games (categoryName field).
_GAME_TO_CATEGORY_NAME = {
    "pokemon": "pokemon",
    "onepiece": "one piece card game",
}


class TCGAPIsIdentityProvider(IdentityProvider):
    source = "tcgapis"

    def __init__(self, client: TCGAPIsClient, game: str):
        self.client = client
        self.game = game
        self.name = f"tcgapis:{game}"
        self._category_id: Optional[int] = None

    # ---- category resolution ----
    def _category_id_for_game(self) -> Optional[int]:
        if self._category_id is not None:
            return self._category_id
        try:
            games = self.client.get("/api/v2/games")
        except TCGAPIsError:
            return None
        target = _GAME_TO_CATEGORY_NAME.get(self.game, self.game).lower()
        for g in _as_list(games):
            name = str(g.get("categoryName", g.get("name", ""))).lower()
            if target in name or name in target:
                self._category_id = _int(g.get("categoryId") or g.get("id"))
                return self._category_id
        return None

    # ---- search ----
    def search(self, query: str, *, number: str = "", limit: int = 20) -> List[CandidateCard]:
        params: Dict[str, Any] = {"q": query, "limit": limit}
        cat = self._category_id_for_game()
        if cat is not None:
            params["categoryId"] = cat
        try:
            payload = self.client.get("/api/v1/catalog/search", params=params)
        except TCGAPIsError:
            log.info("catalog search failed for %r", query)
            return []

        cards: List[CandidateCard] = []
        for row in _as_list(payload)[:limit]:
            cards.append(self._to_candidate(row))
        # If we have a collector number, prefer exact-number rows first.
        if number:
            cards.sort(key=lambda c: (c.collector_number.replace(" ", "") != number), reverse=False)
        return cards

    def _to_candidate(self, row: Dict[str, Any]) -> CandidateCard:
        return CandidateCard(
            game=self.game,
            card_name=str(row.get("cleanName") or row.get("name") or "").strip(),
            set_name=str(row.get("groupName") or row.get("setName") or "").strip(),
            collector_number=str(row.get("number") or row.get("cardNumber") or "").strip(),
            rarity=str(row.get("rarity") or "").strip(),
            image_url=str(row.get("imageUrl") or row.get("image") or "").strip(),
            source=self.source,
            api_id=str(row.get("productId") or row.get("id") or "").strip(),
            metadata={"raw": row},
        )


def _as_list(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "results", "cards", "items"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
