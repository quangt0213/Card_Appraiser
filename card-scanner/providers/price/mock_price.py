"""Offline price provider: deterministic fake 'recent sales' so tests/dev work with no network."""
from __future__ import annotations

import statistics

from providers.base import CandidateCard, PriceProvider, PriceQuote

_MOCK_SALES = {
    "mock-pika-58": [3.50, 3.75, 3.20, 4.00, 3.60],
    "mock-char-4": [280.0, 300.0, 265.0, 310.0, 290.0],
    "mock-luffy-op09-036": [12.0, 11.5, 13.0, 12.5, 12.25],
}


class MockPriceProvider(PriceProvider):
    name = "mock"

    def price_for(self, card: CandidateCard) -> PriceQuote:
        sales = _MOCK_SALES.get(card.api_id)
        if not sales:
            return PriceQuote(value=None, basis="no_sales", source=self.name)
        value = round(statistics.median(sales), 2)
        return PriceQuote(value=value, currency="USD",
                          basis=f"median_recent({len(sales)} sales)",
                          sample_size=len(sales), as_of="2026-07-01T00:00:00Z", source=self.name)
