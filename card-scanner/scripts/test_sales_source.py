#!/usr/bin/env python3
"""Smoke-test the unofficial TCGplayer latest-sales endpoint from this machine.

Run on the Pi (or anywhere) to confirm the sales price source works before
trusting it in production:

    python scripts/test_sales_source.py            # default: Shanks ST05-001
    python scripts/test_sales_source.py 477316     # any TCGplayer productId

Exit code 0 = endpoint reachable and parsed; 1 = failed (app will fall back
to the TCGCSV market price automatically, so a failure here is not fatal).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers.base import CandidateCard
from providers.price.tcgplayer_sales_price import TCGplayerSalesPriceProvider


def main() -> int:
    product_id = sys.argv[1] if len(sys.argv) > 1 else "477316"
    provider = TCGplayerSalesPriceProvider(window=3)
    quote = provider.price_for(CandidateCard(game="", card_name="", api_id=product_id))

    if quote.value is None:
        print(f"FAILED: no sales for product {product_id} (basis={quote.basis})")
        print("The app will fall back to the TCGCSV market price.")
        return 1

    print(f"OK: product {product_id} -> {quote.value} {quote.currency} ({quote.basis})")
    for s in quote.sales:
        print(f"  {s['date'][:19]}  {s['price']:>8.2f}  +{s['shipping']:.2f} ship  "
              f"{s['condition']}  {s['variant']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
