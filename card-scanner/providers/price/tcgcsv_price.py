"""Free pricing from the TCGCSV local catalog.

Price basis: TCGplayer's *market price*, mirrored daily by tcgcsv.com.
There is no sales-history endpoint in a free source, so PRICE_STRATEGY
(last_sale / median_recent / mean_recent) does not apply here; the app's
PRICE_REFRESH_MIN_HOURS cache (default 24h) matches TCGCSV's daily cadence,
so nothing is lost versus per-scan fetching.

If the market price is missing for every printing, falls back to midPrice
(basis 'tcgplayer_mid_fallback').
"""
from __future__ import annotations

from providers.base import CandidateCard, PriceProvider, PriceQuote
from providers.tcgcsv_catalog import TcgCsvCatalog
from utils.logger import get_logger

log = get_logger("price.tcgcsv")


class TcgCsvPriceProvider(PriceProvider):
    name = "tcgcsv"

    def __init__(self, catalog: TcgCsvCatalog):
        self.catalog = catalog

    def price_for(self, card: CandidateCard) -> PriceQuote:
        product_id = (card.api_id or "").strip()
        if not product_id.isdigit():
            # e.g. mock provider ids -- nothing to look up
            return PriceQuote(value=None, basis="no_product_id", source=self.name)

        got = self.catalog.market_price(int(product_id))
        if got is None:
            return PriceQuote(value=None, basis="no_price", source=self.name)

        value, subtype, as_of, kind = got
        basis = f"tcgplayer_market({subtype})" if kind == "market" \
            else f"tcgplayer_mid_fallback({subtype})"
        return PriceQuote(value=round(value, 2), currency="USD", basis=basis,
                          sample_size=0, as_of=as_of, source=self.name)
