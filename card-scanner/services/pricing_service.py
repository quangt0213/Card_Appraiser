"""Resolve a card's recent-sales-derived price, with a TTL cache so we don't
re-hit the (paid, rate-limited) sales-history endpoint on every scan.

Cache order: fresh DB price (within PRICE_REFRESH_MIN_HOURS) -> provider -> DB write.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from providers.base import CandidateCard, PriceProvider, PriceQuote
from utils.logger import get_logger

log = get_logger("pricing")


class PricingService:
    def __init__(self, price_provider: PriceProvider, repository=None,
                 refresh_min_hours: float = 24.0):
        self.provider = price_provider
        self.repo = repository
        self.refresh_min_hours = refresh_min_hours

    def get_price(self, card: CandidateCard, card_db_id: Optional[int] = None) -> PriceQuote:
        # 1. serve a fresh cached price if we have one
        if self.repo is not None and card_db_id is not None:
            cached = self.repo.get_fresh_price(card_db_id, self.refresh_min_hours)
            if cached is not None:
                value, currency, as_of = cached
                return PriceQuote(value=value, currency=currency, basis="cache",
                                  as_of=as_of, source="cache")

        # 2. fetch from provider (recent sales derived)
        quote = self.provider.price_for(card)

        # 3. persist for next time + append to price_history on change
        if self.repo is not None and card_db_id is not None and quote.value is not None:
            self.repo.update_price(card_db_id, quote.value, quote.currency,
                                   observed_at=_now_iso(), basis=quote.basis)
        return quote


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
