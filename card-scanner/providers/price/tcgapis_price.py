"""Recent-sales-derived pricing from TCGAPIs.

Price definition (per your spec): derive the value from REAL recent sales via
    GET /api/v2/sales-history/:productId
not the algorithmic market price. Strategy is configurable:

    last_sale      -> the single most recent completed sale
    median_recent  -> median of the last N sales (default; robust to outliers)
    mean_recent    -> mean of the last N sales

If sales history is empty and PRICE_FALLBACK_TO_MARKET is on, fall back to
    GET /api/v2/prices/:productId  -> "market" price.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional

from providers.base import CandidateCard, PriceProvider, PriceQuote
from providers.tcgapis_client import TCGAPIsClient, TCGAPIsError
from utils.logger import get_logger

log = get_logger("price.tcgapis")


class TCGAPIsPriceProvider(PriceProvider):
    name = "tcgapis"

    def __init__(self, client: TCGAPIsClient, *, strategy: str = "median_recent",
                 window: int = 10, fallback_to_market: bool = True):
        self.client = client
        self.strategy = strategy
        self.window = max(1, window)
        self.fallback_to_market = fallback_to_market

    def price_for(self, card: CandidateCard) -> PriceQuote:
        product_id = card.api_id
        if not product_id:
            return PriceQuote(value=None, basis="no_product_id", source=self.name)

        sales = self._recent_sales(product_id)
        if sales:
            values = [s["price"] for s in sales][: self.window]
            as_of = sales[0].get("soldAt", "")
            if self.strategy == "last_sale":
                value, basis = values[0], "last_sale"
            elif self.strategy == "mean_recent":
                value, basis = statistics.fmean(values), f"mean_recent({len(values)} sales)"
            else:  # median_recent (default)
                value, basis = statistics.median(values), f"median_recent({len(values)} sales)"
            return PriceQuote(value=round(float(value), 2), currency="USD", basis=basis,
                              sample_size=len(values), as_of=str(as_of), source=self.name)

        if self.fallback_to_market:
            market = self._market_price(product_id)
            if market is not None:
                return PriceQuote(value=round(float(market), 2), currency="USD",
                                  basis="market_fallback", sample_size=0, source=self.name)

        return PriceQuote(value=None, basis="no_sales", source=self.name)

    # ---- endpoint calls ----
    def _recent_sales(self, product_id: str) -> List[Dict[str, Any]]:
        try:
            payload = self.client.get(f"/api/v2/sales-history/{product_id}")
        except TCGAPIsError:
            return []
        rows = _as_list(payload, keys=("sales", "data", "results"))
        out: List[Dict[str, Any]] = []
        for r in rows:
            price = _num(r.get("purchasePrice") if "purchasePrice" in r else r.get("price"))
            if price is None:
                continue
            out.append({"price": price, "soldAt": r.get("orderDate") or r.get("soldAt") or ""})
        # newest first if a date is present
        out.sort(key=lambda r: str(r.get("soldAt", "")), reverse=True)
        return out

    def _market_price(self, product_id: str) -> Optional[float]:
        try:
            payload = self.client.get(f"/api/v2/prices/{product_id}")
        except TCGAPIsError:
            return None
        rows = _as_list(payload, keys=("prices", "data", "results")) or ([payload] if isinstance(payload, dict) else [])
        best: Optional[float] = None
        for r in rows:
            for key in ("marketPrice", "market", "midPrice", "mid"):
                v = _num(r.get(key))
                if v is not None:
                    best = v
                    break
            if best is not None:
                break
        return best


def _as_list(payload: Any, keys=("data", "results")) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in keys:
            if isinstance(payload.get(k), list):
                return payload[k]
    return []


def _num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
