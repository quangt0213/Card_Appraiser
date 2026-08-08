"""Provider contracts.

Identity and pricing are deliberately separate:

* IdentityProvider  -- OCR/query text  -> candidate cards (name, set, number, image, productId)
* PriceProvider     -- a resolved card  -> a recent-sales-derived price quote

This lets us swap the price source without touching matching, and cache prices
independently of identity.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CandidateCard:
    """Normalized card record returned by any identity provider."""
    game: str
    card_name: str
    set_name: str = ""
    collector_number: str = ""
    rarity: str = ""
    image_url: str = ""
    source: str = ""
    api_id: str = ""            # provider product/card id (e.g. TCGAPIs productId)
    price: Optional[float] = None
    currency: str = "USD"
    metadata: dict = field(default_factory=dict)


@dataclass
class PriceQuote:
    """A price derived from recent sales (see PRICE_STRATEGY)."""
    value: Optional[float]
    currency: str = "USD"
    basis: str = ""             # e.g. "median_recent(3 sales)" or "market_fallback"
    sample_size: int = 0
    as_of: str = ""             # ISO timestamp of the freshest sale used
    source: str = ""
    sales: list = field(default_factory=list)  # raw recent sales used, newest first:
                                               # [{price, shipping, date, condition, variant}]


class IdentityProvider(ABC):
    game: str = ""
    name: str = ""

    @abstractmethod
    def search(self, query: str, *, number: str = "", limit: int = 20) -> List[CandidateCard]:
        """Return candidate cards for a cleaned OCR query and/or collector number."""
        raise NotImplementedError


class PriceProvider(ABC):
    name: str = ""

    @abstractmethod
    def price_for(self, card: CandidateCard) -> PriceQuote:
        """Return a recent-sales-derived price for an identified card."""
        raise NotImplementedError
