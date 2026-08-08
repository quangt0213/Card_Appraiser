"""Identity provider backed by the free TCGCSV local catalog.

Search runs against SQLite (no network on the scan path), so it works offline
between daily syncs and has no per-request cost or rate limit.
"""
from __future__ import annotations

from typing import List

from providers.base import CandidateCard, IdentityProvider
from providers.tcgcsv_catalog import TcgCsvCatalog
from utils.logger import get_logger

log = get_logger("identity.tcgcsv")


class TcgCsvIdentityProvider(IdentityProvider):
    source = "tcgcsv"

    def __init__(self, catalog: TcgCsvCatalog, game: str):
        self.catalog = catalog
        self.game = game
        self.name = f"tcgcsv:{game}"

    def search(self, query: str, *, number: str = "", limit: int = 20) -> List[CandidateCard]:
        rows = self.catalog.search_cards(self.game, query, number=number, limit=limit)
        return [
            CandidateCard(
                game=self.game,
                card_name=row["name"],
                set_name=row["set_name"],
                collector_number=row["number"],
                rarity=row["rarity"],
                image_url=row["image_url"],
                source=self.source,
                api_id=str(row["product_id"]),  # TCGplayer productId
                metadata={"group_id": row["group_id"], "url": row["url"]},
            )
            for row in rows
        ]
