"""Free local card catalog backed by TCGCSV (https://tcgcsv.com).

TCGCSV mirrors TCGplayer's catalog and prices as static JSON, refreshed daily
around 20:00 UTC. No API key, no rate limits, no monthly fee.

    GET {base}/categories                        -> all games
    GET {base}/{categoryId}/groups               -> sets in a game
    GET {base}/{categoryId}/{groupId}/products   -> cards in a set (name, Number, Rarity, image)
    GET {base}/{categoryId}/{groupId}/prices     -> market/low/mid/high per productId + subType

Design:

* One SQLite file (separate from the app DB) holds groups, products, prices.
* A background thread syncs the product catalog at startup and re-checks every
  `refresh_hours`. Only groups whose TCGplayer `modifiedOn` changed since the
  last sync are re-downloaded, so after the first run the daily delta is a
  handful of small requests.
* Prices are fetched lazily per *group*: the first time a card in a set is
  priced, that set's price file (one request) is cached with the same TTL.
* `productId` is TCGplayer's id -- the same id space TCGAPIs used -- so cards
  already persisted in the app DB keep resolving prices after the switch.
* No sales-history endpoint exists here; the price basis is TCGplayer's
  daily market price (see TcgCsvPriceProvider).
"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from utils.logger import get_logger

log = get_logger("tcgcsv")

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    fuzz = None

# TCGplayer category ids (verified against {base}/categories).
GAME_CATEGORIES = {
    "pokemon": 3,
    "onepiece": 68,
}

# When a product has several printings, prefer these subtypes for "the" price.
_SUBTYPE_PREFERENCE = (
    "Normal", "Foil", "Holofoil", "Reverse Holofoil",
    "1st Edition Normal", "1st Edition Holofoil", "Unlimited",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS groups (
    group_id           INTEGER PRIMARY KEY,
    category_id        INTEGER NOT NULL,
    game               TEXT NOT NULL,
    name               TEXT NOT NULL,
    abbreviation       TEXT DEFAULT '',
    modified_on        TEXT DEFAULT '',
    products_synced_on TEXT DEFAULT '',
    prices_synced_at   TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS products (
    product_id  INTEGER PRIMARY KEY,
    group_id    INTEGER NOT NULL,
    game        TEXT NOT NULL,
    name        TEXT NOT NULL,
    clean_name  TEXT NOT NULL,
    number      TEXT DEFAULT '',
    number_norm TEXT DEFAULT '',
    rarity      TEXT DEFAULT '',
    image_url   TEXT DEFAULT '',
    url         TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_products_game_number ON products(game, number_norm);
CREATE INDEX IF NOT EXISTS idx_products_group       ON products(group_id);
CREATE TABLE IF NOT EXISTS prices (
    product_id INTEGER NOT NULL,
    sub_type   TEXT NOT NULL,
    market     REAL,
    low        REAL,
    mid        REAL,
    high       REAL,
    updated_at TEXT DEFAULT '',
    PRIMARY KEY (product_id, sub_type)
);
"""


class TcgCsvError(RuntimeError):
    pass


class TcgCsvClient:
    """Thin HTTP client for tcgcsv.com static JSON (no auth)."""

    def __init__(self, base_url: str = "https://tcgcsv.com/tcgplayer", *,
                 timeout: float = 10.0, max_retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json", "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) card-scanner/1.0"})

    def get(self, path: str) -> List[Dict[str, Any]]:
        """GET {base}{path} and return the 'results' list."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                payload = resp.json()
                if isinstance(payload, dict):
                    return payload.get("results") or []
                return payload if isinstance(payload, list) else []
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                log.warning("TCGCSV GET %s failed: %s", path, exc)
                raise TcgCsvError(str(exc)) from exc
        raise TcgCsvError(str(last_exc) if last_exc else "unknown error")


class TcgCsvCatalog:
    """SQLite-backed local catalog: identity search + market price lookup."""

    def __init__(self, db_path: Path, client: Optional[TcgCsvClient] = None, *,
                 games: Optional[List[str]] = None, refresh_hours: float = 24.0):
        self.db_path = Path(db_path)
        self.client = client or TcgCsvClient()
        self.games = [g for g in (games or list(GAME_CATEGORIES)) if g in GAME_CATEGORIES]
        self.refresh_hours = max(1.0, refresh_hours)
        self._sync_lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ---- connection ----
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ---- sync ----
    def ensure_synced(self, *, force: bool = False) -> None:
        """Sync the product catalog for all enabled games if stale."""
        if not self._sync_lock.acquire(blocking=False):
            return  # a sync is already running
        try:
            for game in self.games:
                if force or self._age_hours(f"synced:{game}") >= self.refresh_hours:
                    self._sync_game(game)
        finally:
            self._sync_lock.release()

    def start_background_sync(self) -> threading.Thread:
        """Sync at startup and re-check hourly, off the request path."""
        def loop() -> None:
            while True:
                try:
                    self.ensure_synced()
                except Exception as exc:  # noqa: BLE001 -- never kill the thread
                    log.warning("catalog sync failed: %s", exc)
                time.sleep(3600)
        t = threading.Thread(target=loop, name="tcgcsv-sync", daemon=True)
        t.start()
        return t

    def _sync_game(self, game: str) -> None:
        category = GAME_CATEGORIES[game]
        t0 = time.time()
        groups = self.client.get(f"/{category}/groups")
        fetched = 0
        with self._connect() as conn:
            for g in groups:
                conn.execute(
                    """INSERT INTO groups (group_id, category_id, game, name, abbreviation, modified_on)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(group_id) DO UPDATE SET
                           name = excluded.name, abbreviation = excluded.abbreviation,
                           modified_on = excluded.modified_on""",
                    (g.get("groupId"), category, game, g.get("name", ""),
                     g.get("abbreviation") or "", g.get("modifiedOn") or ""))
            stale = conn.execute(
                "SELECT group_id, modified_on FROM groups "
                "WHERE game = ? AND products_synced_on != modified_on", (game,)).fetchall()
        for row in stale:
            gid, modified_on = row["group_id"], row["modified_on"]
            try:
                products = self.client.get(f"/{category}/{gid}/products")
            except TcgCsvError:
                continue  # keep whatever we had; retried next cycle
            cards = [_to_card_row(p, game) for p in products]
            cards = [c for c in cards if c is not None]
            with self._connect() as conn:
                conn.executemany(
                    """INSERT INTO products (product_id, group_id, game, name, clean_name,
                                             number, number_norm, rarity, image_url, url)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(product_id) DO UPDATE SET
                           name = excluded.name, clean_name = excluded.clean_name,
                           number = excluded.number, number_norm = excluded.number_norm,
                           rarity = excluded.rarity, image_url = excluded.image_url,
                           url = excluded.url""", cards)
                conn.execute("UPDATE groups SET products_synced_on = ? WHERE group_id = ?",
                             (modified_on, gid))
            fetched += 1
        self._set_meta(f"synced:{game}", _now_iso())
        log.info("catalog sync %s: %d groups (%d refreshed) in %.1fs",
                 game, len(groups), fetched, time.time() - t0)

    # ---- identity search ----
    def search_cards(self, game: str, query: str, *, number: str = "",
                     limit: int = 20) -> List[Dict[str, Any]]:
        """Cards matching a fuzzy name and/or normalized collector number."""
        rows: Dict[int, sqlite3.Row] = {}
        norm = _norm_number(number)
        q = (query or "").strip().lower()
        sql = ("SELECT p.*, g.name AS set_name FROM products p "
               "JOIN groups g ON g.group_id = p.group_id WHERE p.game = ? AND ")
        with self._connect() as conn:
            if norm:
                for r in conn.execute(
                        sql + "(p.number_norm = ? OR p.number_norm LIKE ?)",
                        (game, norm, f"{norm}/%")):
                    rows[r["product_id"]] = r
            if q:
                for r in conn.execute(sql + "LOWER(p.clean_name) LIKE ? LIMIT 300",
                                      (game, f"%{q}%")):
                    rows.setdefault(r["product_id"], r)
                if len(rows) < limit:  # loosen: longest word of the query
                    token = max(q.split(), key=len, default="")
                    if len(token) >= 4:
                        for r in conn.execute(sql + "LOWER(p.clean_name) LIKE ? LIMIT 300",
                                              (game, f"%{token}%")):
                            rows.setdefault(r["product_id"], r)
                if not rows and fuzz is not None:
                    # OCR typos ('shnks') defeat LIKE -- fuzzy-scan all names.
                    scored = [
                        (fuzz.WRatio(q, r["clean_name"].lower()), r["product_id"])
                        for r in conn.execute(
                            "SELECT product_id, clean_name FROM products WHERE game = ?",
                            (game,))
                    ]
                    scored.sort(reverse=True)
                    top_ids = [pid for s, pid in scored[:max(limit, 20)] if s >= 60]
                    if top_ids:
                        marks = ",".join("?" * len(top_ids))
                        for r in conn.execute(
                                sql + f"p.product_id IN ({marks})", (game, *top_ids)):
                            rows.setdefault(r["product_id"], r)

        def score(r: sqlite3.Row) -> float:
            s = 0.0
            if norm and (r["number_norm"] == norm or r["number_norm"].startswith(f"{norm}/")):
                s += 100.0
            if q and fuzz is not None:
                s += fuzz.WRatio(q, r["clean_name"].lower())
            elif q and q in r["clean_name"].lower():
                s += 50.0
            return s

        ranked = sorted(rows.values(), key=score, reverse=True)[:limit]
        return [dict(r) for r in ranked]

    # ---- pricing ----
    def market_price(self, product_id: int) -> Optional[Tuple[float, str, str, str]]:
        """(value, subtype, as_of, kind) for a product; refreshes its group's
        price file when stale. kind is 'market' or 'mid_fallback'."""
        with self._connect() as conn:
            prod = conn.execute(
                "SELECT p.group_id, g.category_id, g.prices_synced_at FROM products p "
                "JOIN groups g ON g.group_id = p.group_id WHERE p.product_id = ?",
                (product_id,)).fetchone()
        if prod is None:
            return None
        if _hours_since(prod["prices_synced_at"]) >= self.refresh_hours:
            self._refresh_group_prices(prod["category_id"], prod["group_id"])
        with self._connect() as conn:
            price_rows = conn.execute(
                "SELECT sub_type, market, mid, updated_at FROM prices WHERE product_id = ?",
                (product_id,)).fetchall()
        if not price_rows:
            return None
        by_subtype = {r["sub_type"]: r for r in price_rows}
        ordered = [by_subtype[s] for s in _SUBTYPE_PREFERENCE if s in by_subtype]
        ordered += [r for r in price_rows if r not in ordered]
        for kind, column in (("market", "market"), ("mid_fallback", "mid")):
            for r in ordered:
                if r[column] is not None:
                    return float(r[column]), r["sub_type"], r["updated_at"], kind
        return None

    def _refresh_group_prices(self, category_id: int, group_id: int) -> None:
        try:
            results = self.client.get(f"/{category_id}/{group_id}/prices")
        except TcgCsvError:
            return  # serve stale prices rather than nothing
        now = _now_iso()
        with self._connect() as conn:
            conn.executemany(
                """INSERT INTO prices (product_id, sub_type, market, low, mid, high, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(product_id, sub_type) DO UPDATE SET
                       market = excluded.market, low = excluded.low, mid = excluded.mid,
                       high = excluded.high, updated_at = excluded.updated_at""",
                [(r.get("productId"), r.get("subTypeName") or "Normal", r.get("marketPrice"),
                  r.get("lowPrice"), r.get("midPrice"), r.get("highPrice"), now)
                 for r in results if r.get("productId") is not None])
            conn.execute("UPDATE groups SET prices_synced_at = ? WHERE group_id = ?",
                         (now, group_id))

    # ---- misc ----
    def card_count(self, game: Optional[str] = None) -> int:
        with self._connect() as conn:
            if game:
                return conn.execute("SELECT COUNT(*) FROM products WHERE game = ?",
                                    (game,)).fetchone()[0]
            return conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    def _set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def _age_hours(self, meta_key: str) -> float:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (meta_key,)).fetchone()
        return _hours_since(row["value"] if row else "")


# ---- helpers ----
def _to_card_row(p: Dict[str, Any], game: str) -> Optional[tuple]:
    """Product JSON -> products row, or None for sealed/non-card products."""
    number = rarity = ""
    for ext in p.get("extendedData") or []:
        if ext.get("name") == "Number":
            number = str(ext.get("value") or "").strip()
        elif ext.get("name") == "Rarity":
            rarity = str(ext.get("value") or "").strip()
    if not number:  # boxes, packs, display cases -- not scannable cards
        return None
    return (p.get("productId"), p.get("groupId"), game,
            str(p.get("name") or "").strip(), str(p.get("cleanName") or p.get("name") or "").strip(),
            number, _norm_number(number), rarity,
            str(p.get("imageUrl") or "").strip(), str(p.get("url") or "").strip())


def _norm_number(number: str) -> str:
    """Canonical collector number for matching: uppercase, every separator
    except '/' dropped (OCR misreads dashes/spaces: 'st05 001' == 'ST05-001'),
    digit segments stripped of leading zeros ('058/102' == '58/102')."""
    n = "".join(ch for ch in (number or "").upper() if ch.isalnum() or ch == "/")
    if "/" in n:
        n = "/".join(seg.lstrip("0") or "0" if seg.isdigit() else seg
                     for seg in n.split("/"))
    elif n.isdigit():
        n = n.lstrip("0") or "0"
    return n


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_since(iso: str) -> float:
    if not iso:
        return float("inf")
    try:
        then = datetime.fromisoformat(iso)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - then).total_seconds() / 3600.0
    except ValueError:
        return float("inf")
