"""Recent-sales pricing from TCGplayer's marketplace 'latest sales' endpoint.

    POST https://mpapi.tcgplayer.com/v2/product/{productId}/latestsales
    body: {"conditions": [], "languages": [], "variants": [],
           "listingType": "All", "offset": 0, "limit": N}

This is the same feed TCGplayer's own product pages show under "Latest Sales".
It is FREE and keyless, but **unofficial and undocumented**: TCGplayer can
change or block it at any time. Because of that:

* Parsing is defensive (multiple key-name fallbacks), mirroring the approach
  used for TCGAPIs.
* Any failure (HTTP error, blocked, empty, shape change) falls back to the
  injected fallback provider (TCGCSV daily market price) instead of erroring.
* The app-level PricingService caches quotes for PRICE_REFRESH_MIN_HOURS, so
  this endpoint is hit at most once per card per day -- polite traffic.

Verify from any machine with:  python scripts/test_sales_source.py 477316
"""
from __future__ import annotations

import statistics
import time
from typing import Any, Dict, List, Optional

import requests

from providers.base import CandidateCard, PriceProvider, PriceQuote
from utils.logger import get_logger

log = get_logger("price.tcgplayer_sales")

DEFAULT_BASE_URL = "https://mpapi.tcgplayer.com/v2/product"


class TCGplayerSalesPriceProvider(PriceProvider):
    name = "tcgplayer_sales"

    def __init__(self, *, strategy: str = "median_recent", window: int = 3,
                 fallback: Optional[PriceProvider] = None,
                 base_url: str = DEFAULT_BASE_URL,
                 timeout: float = 10.0, max_retries: int = 2):
        self.strategy = strategy
        self.window = max(1, window)
        self.fallback = fallback
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            # A real UA string: the endpoint sits behind a CDN that rejects
            # the default python-requests agent.
            "User-Agent": ("Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        })

    # ---- PriceProvider ----
    def price_for(self, card: CandidateCard) -> PriceQuote:
        product_id = (card.api_id or "").strip()
        if not product_id.isdigit():
            # mock/foreign ids -- nothing to look up here or downstream
            return PriceQuote(value=None, basis="no_product_id", source=self.name)

        sales = self._latest_sales(product_id)
        if sales:
            recent = sales[: self.window]
            values = [s["price"] for s in recent]
            if self.strategy == "last_sale":
                value, basis = values[0], "last_sale"
            elif self.strategy == "mean_recent":
                value, basis = statistics.fmean(values), f"mean_recent({len(values)} sales)"
            else:  # median_recent (default)
                value, basis = statistics.median(values), f"median_recent({len(values)} sales)"
            return PriceQuote(value=round(float(value), 2), currency="USD", basis=basis,
                              sample_size=len(values), as_of=str(recent[0].get("date", "")),
                              source=self.name, sales=recent)

        if self.fallback is not None:
            quote = self.fallback.price_for(card)
            if quote.value is not None:
                quote.basis = f"market_fallback:{quote.basis}"
                return quote

        return PriceQuote(value=None, basis="no_sales", source=self.name)

    # ---- endpoint call ----
    def _latest_sales(self, product_id: str) -> List[Dict[str, Any]]:
        """Newest-first completed sales, defensively parsed; [] on any failure."""
        url = f"{self.base_url}/{product_id}/latestsales"
        body = {"conditions": [], "languages": [], "variants": [],
                "listingType": "All", "offset": 0, "limit": max(self.window * 3, 10)}
        payload: Any = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.post(url, json=body, timeout=self.timeout)
                if resp.status_code in (403, 429):
                    # blocked or rate limited -- back off once, then give up to fallback
                    if attempt < self.max_retries:
                        time.sleep(min(2 ** attempt, 4))
                        continue
                    log.warning("latestsales %s for product %s", resp.status_code, product_id)
                    return []
                resp.raise_for_status()
                payload = resp.json()
                break
            except (requests.RequestException, ValueError) as exc:
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                log.warning("latestsales failed for product %s: %s", product_id, exc)
                return []

        rows = _as_list(payload, keys=("data", "sales", "results"))
        out: List[Dict[str, Any]] = []
        for r in rows:
            price = _num(r.get("purchasePrice", r.get("price")))
            if price is None or price <= 0:
                continue
            out.append({
                "price": price,
                "shipping": _num(r.get("shippingPrice")) or 0.0,
                "date": str(r.get("orderDate") or r.get("soldDate") or r.get("date") or ""),
                "condition": str(r.get("condition") or ""),
                "variant": str(r.get("variant") or r.get("subTypeName") or ""),
            })
        out.sort(key=lambda s: s["date"], reverse=True)  # newest first
        return out


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
