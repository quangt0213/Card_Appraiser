# Raspberry Pi Trading Card Scanner Backend

A Raspberry Pi 4 backend that identifies a trading card from a JPEG posted by an
ESP32-CAM and returns its TCGplayer price. The default provider is **TCGCSV**
([tcgcsv.com](https://tcgcsv.com)) — free, keyless, no rate limits — which mirrors
TCGplayer's catalog and **market prices** daily; the paid
[TCGAPIs](https://tcgapis.com) recent-sales provider remains available via
`CARD_DATA_PROVIDER=tcgapis`. It supports Pokémon and One Piece
through a provider abstraction, caches everything it can locally in SQLite +
on-disk tiers, and shows the latest scan on a Flask-rendered touchscreen page.

This is a modular, edge-CV rebuild. The pipeline is **OpenCV-first**: it leads with
cheap, discriminative signals (collector-number OCR + perceptual hashing) and only
falls back to heavier work (EasyOCR, remote lookups, ORB) when needed.

---

## What the pipeline does (in order)

1. **Upload** — ESP32-CAM sends a JPEG to `POST /scan`. Flask validates size + JPEG
   magic bytes and saves it (hash-deduplicated) under `data/scans/`.
2. **Detect & warp** (`card_detector`) — find the card's quadrilateral, perspective-
   correct it to a canonical upright image, and crop the **title** and **collector-
   number** regions. Everything downstream sees a clean, flat card.
3. **Local match first** (`image_matcher`) — perceptual hash (pHash) of the warped
   card is compared (Hamming distance) against an **in-memory index** of known cards.
   Close hit → done, no OCR or network. This is the OpenCV-first, O(N)-cheap path.
4. **OCR fallback** (`ocr_service`, EasyOCR) — only if the local match is weak. OCR
   runs on the small title/number crops, not the whole image, and the model is loaded
   **once** at startup.
5. **Normalize** (`normalizer`, RapidFuzz) — clean OCR text, extract/repair the
   collector number, fuzzy-match names, and de-duplicate candidates.
6. **Identity providers** (`providers/identity`) — look up candidate cards in the
   local TCGCSV catalog (SQLite, no network on the scan path), or query TCGAPIs
   when configured.
7. **Rank** (`candidate_ranker`) — score each candidate:
   `0.5·number_exact + 0.3·name_fuzz + 0.2·image_score`. A misread number can't win
   alone — it must be corroborated by name/image.
8. **Price** (`pricing_service` → `providers/price`) — for the winning card, look up
   the TCGplayer **market price** (TCGCSV, default) or derive it from **real recent
   sales** (TCGAPIs `/api/v2/sales-history/:productId`).
9. **Persist & learn** — a confident remote match is written to SQLite with its pHash
   + ORB descriptors, so the **next** scan of that card resolves locally in step 3.
10. **History + display** — every attempt is written to `scan_history`; the touchscreen
    state file is updated and `/display` renders it.

---

## The matching cascade (and its guard rails)

Leads with the cheap signal, escalates only as needed, stops on confidence:

| Pass | Signal | Cost | Role |
| --- | --- | --- | --- |
| 1 | **Collector-number OCR** (+ RapidFuzz) | ~free | Most discriminative; resolves most modern cards deterministically |
| 2 | **pHash** vs in-memory index | microseconds, O(N) | "Have I seen this exact card before?" — local, offline hits |
| 3 | **ORB** over the pHash top-K | seconds | **Tie-break only** on a small shortlist, never the whole DB |
| 4 | **Name OCR → provider search → rank** | network | Fallback when the number is unreadable |

Two failure modes are handled explicitly (the flaw check you asked about):

- **A misread collector number can confidently point at the wrong card.** So a number
  hit does **not** win on its own — `candidate_ranker` still folds in name-fuzz and
  image score before accepting (`REMOTE_MATCH_THRESHOLD`).
- **pHash of a lit/foil scan drifts from clean art.** So pHash uses a **Hamming-distance
  threshold** (`PHASH_MAX_DISTANCE`), not exact match, and ORB re-ranks the shortlist
  when pHash is ambiguous.

pHash is computed natively with OpenCV's DCT (no extra `imagehash` dependency).

---

## Pricing

### Default: last 3 real sales (free, unofficial) with market fallback

`PRICE_SOURCE=sales` (the default) prices a card from its **last N completed
TCGplayer sales** (`PRICE_RECENT_SALES_WINDOW=3`, reduced by `PRICE_STRATEGY`,
default median) — a better indicator than the algorithmic market price in a
volatile market. Source: TCGplayer's marketplace `latestsales` endpoint
(`providers/price/tcgplayer_sales_price.py`), the same feed shown on their
product pages. It is free and keyless but **unofficial/undocumented**, so:

- Every failure (HTTP error, block, shape change, zero sales) falls back
  automatically to the TCGCSV market price; the quote's `basis` then reads
  `market_fallback:tcgplayer_market(...)` so the UI can tell them apart.
- The `PricingService` TTL cache (`PRICE_REFRESH_MIN_HOURS=24`) means at most
  one request per card per day.
- The raw sales used are returned in the scan result as `recent_sales`
  (`[{price, shipping, date, condition, variant}]`, newest first).
- Verify the endpoint from any machine: `python scripts/test_sales_source.py 477316`
- Set `PRICE_SOURCE=market` to disable all unofficial calls.

### Fallback / alternative: free TCGplayer market price via TCGCSV

`CARD_DATA_PROVIDER=tcgcsv` (the default) uses [tcgcsv.com](https://tcgcsv.com), a
free, keyless daily mirror of TCGplayer's catalog and prices:

- A background thread syncs the product catalog for the enabled games into
  `data/cache/tcgcsv_catalog.db` at startup and every `TCGCSV_REFRESH_HOURS`.
  After the first sync (~a few hundred small JSON files, a few minutes on a Pi),
  only sets whose `modifiedOn` changed are re-downloaded.
- Identity search and pricing then run **against local SQLite** — no network on
  the scan path, no rate limits, works offline between syncs.
- Prices are fetched lazily one *set* at a time and cached with the same TTL;
  the quote's `basis` is `tcgplayer_market(<printing>)` (or
  `tcgplayer_mid_fallback(...)` when TCGplayer has no market price).
- `productId` is TCGplayer's — the same id space TCGAPIs used — so previously
  cached cards keep pricing correctly after the switch.

TCGCSV has **no sales-history feed**, so `PRICE_STRATEGY` does not apply to it.
Prices update once a day (~20:00 UTC), which matches `PRICE_REFRESH_MIN_HOURS=24`.

### Optional: recent-sales pricing via TCGAPIs (paid)

With `CARD_DATA_PROVIDER=tcgapis` and a key, TCGAPIs exposes a real completed-
sales feed, so `providers/price/tcgapis_price.py` derives the value from actual sales:

- `GET /api/v2/sales-history/:productId` → recent completed sales.
- `PRICE_STRATEGY` chooses how to reduce them:
  - `last_sale` — the single most recent sale
  - `median_recent` — median of the last `PRICE_RECENT_SALES_WINDOW` sales (**default**, robust to outliers)
  - `mean_recent` — mean of the last N sales
- If sales history is empty and `PRICE_FALLBACK_TO_MARKET=true`, it falls back to the
  algorithmic market price (`/api/v2/prices/:productId`). The quote records its
  `basis` (e.g. `median_recent(10 sales)`) and `as_of` date so the UI never implies a
  live last-sale when it's really a fallback.

> **Plan note:** on TCGAPIs, `sales-history` and `prices` require the **Business** tier
> or higher; the catalog (identity) is available from **Hobby**. Set `TCGAPIS_API_KEY`
> in `.env`. With `CARD_DATA_PROVIDER=mock` (or a missing key on `tcgapis`), the app
> runs entirely on the built-in **mock** provider so you can develop and test offline.

---

## Project structure

```
app.py                      Flask app factory: wires config -> repo -> providers -> services -> pipeline
config.py                   Typed config, loaded once from .env
requirements.txt
.env.example
database/
  schema.sql                cards, card_images, scan_history, api_cache, storage_files, price_history (WAL)
  repository.py             the ONLY module that touches SQL (see Issue #7)
  init_db.py                create the DB
  seed_sample_cards.py      optional sample rows
providers/
  base.py                   CandidateCard, PriceQuote, IdentityProvider, PriceProvider
  tcgcsv_catalog.py         FREE local catalog: TCGCSV client + SQLite sync/search/prices
  tcgapis_client.py         shared HTTP client (x-api-key, retries, timeouts)
  identity/                 tcgcsv_identity.py, tcgapis_identity.py, mock_identity.py
  price/                    tcgplayer_sales_price.py (last N sales, default), tcgcsv_price.py (market fallback),
                            tcgapis_price.py (paid recent-sales), mock_price.py
scripts/
  test_sales_source.py      smoke-test the unofficial latestsales endpoint from any machine
services/
  card_detector.py          find + perspective-warp the card, crop title/number
  ocr_service.py            EasyOCR wrapper (loaded once, ROI-only)
  normalizer.py             RapidFuzz cleaning / number extraction / fuzzy matching
  image_matcher.py          native pHash + ORB tie-break cascade
  candidate_ranker.py       number+name+image -> confidence
  pricing_service.py        recent-sales price with a TTL cache
  scan_pipeline.py          the orchestrator
  job_service.py            SimpleJobService (ThreadPoolExecutor, 1 worker, task timeout)
  storage_manager.py        hash-dedupe saves, tiered dirs
  cache_policy.py           TTL + LRU eviction helpers
  descriptor_store.py       ORB .npz persistence
  display_service.py        writes display_state.json
  maintenance_service.py    bounded startup cleanup
routes/
  scan_routes.py            POST /scan, GET /jobs/<id>, /history, /health
  ui_routes.py              GET /display, GET /
utils/
  image_utils.py, logger.py
templates/  display.html, result.html
static/     styles.css
tests/      test_normalizer.py, test_image_matcher.py, test_candidate_ranker.py, test_pipeline.py
data/       scans/  cache/{card_images,candidate_temp,scan_debug}/  descriptors/
```

---

## Raspberry Pi 4 setup

Python 3.11+ recommended. Install system libs, then the Python deps:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip libgl1 libglib2.0-0

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt      # EasyOCR pulls in torch -- this is the slow one

cp .env.example .env                 # defaults to the free TCGCSV provider -- no key needed
python database/init_db.py
python database/seed_sample_cards.py # optional
python app.py                        # serves on http://0.0.0.0:5000
```

`opencv-python-headless` is used deliberately (no GUI libs). EasyOCR is the heaviest
install; if you want it lighter later, `ocr_service.py` is the only file to change.

---

## Configuration (`.env`)

Key settings (full list in `.env.example`):

| Setting | Default | Purpose |
| --- | --- | --- |
| `LOCAL_MATCH_THRESHOLD` | `0.72` | confidence to trust a local pHash/ORB match |
| `REMOTE_MATCH_THRESHOLD` | `0.60` | confidence to trust a remote candidate |
| `PHASH_MAX_DISTANCE` | `10` | max Hamming distance (of 64 bits) for a pHash hit |
| `ORB_SHORTLIST` | `5` | how many pHash candidates ORB re-ranks |
| `OCR_ENABLED` | `true` | set false to skip EasyOCR during quick dev |
| `CARD_DATA_PROVIDER` | `tcgcsv` | `tcgcsv` (free) \| `tcgapis` (paid) \| `mock` |
| `PRICE_SOURCE` | `sales` | `sales` (last N real sales, unofficial) \| `market` (TCGCSV only) |
| `PRICE_RECENT_SALES_WINDOW` | `3` | how many most-recent sales feed the quote |
| `PRICE_STRATEGY` | `median_recent` | `last_sale` \| `median_recent` \| `mean_recent` |
| `TCGCSV_REFRESH_HOURS` | `24` | TCGCSV catalog + per-set price cache TTL |
| `TCGAPIS_API_KEY` | *(blank)* | only for `tcgapis`; blank → mock provider |
| `PRICE_RECENT_SALES_WINDOW` | `10` | sales considered for median/mean |
| `PRICE_REFRESH_MIN_HOURS` | `24` | don't re-fetch a card's price more often than this |
| `SCAN_WORKERS` | `1` | keep at 1 on a Pi 4 |
| `MAX_UPLOAD_BYTES` | `12000000` | reject larger uploads (DoS guard) |

---

## API

- `GET /health` — status, card count, index size, DB size, whether a provider key is set.
- `POST /scan` — body is raw `image/jpeg` **or** multipart field `image`. Returns the
  final JSON result by default; add `?async=1` (or set `BLOCKING_SCAN_RESPONSE=false`)
  to get a `job_id` and poll `GET /jobs/<job_id>`.
- `GET /history?limit=25` — recent scan rows.
- `GET /display` — touchscreen UI (auto-refresh). `GET /` — status page.

`POST /scan` result:

```json
{
  "matched": true,
  "card_name": "Pikachu",
  "game": "pokemon",
  "set_name": "Base Set",
  "collector_number": "58/102",
  "price": 3.60,
  "currency": "USD",
  "price_basis": "median_recent(10 sales)",
  "price_as_of": "2026-07-01T00:00:00Z",
  "confidence": 0.86,
  "source": "remote_api",
  "match_method": "ocr+provider",
  "ocr_text": "Pikachu\n58/102",
  "db_id": 123
}
```

### ESP32-CAM upload (raw JPEG)

```cpp
HTTPClient http;
http.begin("http://RASPBERRY_PI_IP:5000/scan");
http.addHeader("Content-Type", "image/jpeg");
int code = http.POST(jpegBuffer, jpegLength);
String response = http.getString();
http.end();
```

### Test with curl

```bash
curl -X POST -H "Content-Type: image/jpeg" --data-binary @sample-card.jpg \
  http://RASPBERRY_PI_IP:5000/scan
```

---

## Touchscreen (Freenove)

```bash
chromium-browser --kiosk http://localhost:5000/display
```

`/display` auto-refreshes and shows the card name, game, set, price (with its basis and
as-of date), confidence, and match source (`local_db` / `remote_api`).

---

## Database

SQLite file `carddata.db` (WAL mode). Full-size images live on disk; SQLite holds
compact metadata, the pHash index, prices, and history:

- `cards` — normalized card, `api_id`, `phash`, descriptor/image paths, latest price.
- `card_images`, `storage_files` — on-disk file index (tier, hash, size, LRU, expiry).
- `scan_history` — every attempt (matched or not) with confidence + source.
- `price_history` — appended only when a price changes.
- `api_cache` — provider query cache.

The **repository is the single SQL owner** (repo Issue #7), and the pipeline keeps an
**in-memory index** so a scan compares hashes in RAM and only writes to SQLite on a new
match — not a per-scan DB scan.

---

## Testing

```bash
pytest
```

Tests run fully offline: a fake detector, a stub OCR, and the **mock** identity/price
providers. They need no network, no EasyOCR/torch, and no TCGAPIs key. The suite covers
the normalizer, the pHash matcher, the ranker, and an end-to-end pipeline run
(remote match → recent-sales price → subsequent local hit with no duplicate).

> Note: `normalizer.py` uses RapidFuzz when available and falls back to a stdlib
> `difflib` shim only if it isn't importable, so the app never hard-crashes on a minimal
> environment. On the Pi, `pip install -r requirements.txt` gives you the real RapidFuzz.

---

## Suggested build order

If you're bringing this up incrementally on the Pi:

1. `POST /scan` that just saves the JPEG + `/health` — prove the ESP32-CAM round-trip.
2. `card_detector` — eyeball warped crops saved to `data/cache/scan_debug/`.
3. `ocr_service` + `normalizer` on the number crop → resolve Pokémon by collector number.
4. `pricing_service` → attach the recent-sales price. **End-to-end value delivered.**
5. SQLite repository + in-memory index + pHash local matching + caching.
6. ORB tie-break, One Piece provider, confidence scoring, `/display`.
7. Maintenance, eviction, metrics, hardening.
