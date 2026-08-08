"""The ONLY module that touches SQL (addresses repo Issue #7: reduce and centralize
DB calls). Everything else calls these methods; nobody writes raw queries elsewhere.

Uses parameterized queries throughout, WAL mode, and a small connection-per-call
model that is safe with the single scan worker.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from providers.base import CandidateCard

_MASK64 = (1 << 64) - 1


def _to_signed64(v: Optional[int]) -> Optional[int]:
    """SQLite INTEGER is signed 64-bit; a 64-bit unsigned pHash can overflow it.
    Map unsigned -> signed for storage."""
    if v is None:
        return None
    v &= _MASK64
    return v - (1 << 64) if v >= (1 << 63) else v


def _to_unsigned64(v: Optional[int]) -> Optional[int]:
    if v is None:
        return None
    return v + (1 << 64) if v < 0 else v


class Repository:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    # ---- connection ----
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def initialize(self, schema_path: str | Path) -> None:
        sql = Path(schema_path).read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(sql)

    # ---- in-memory index (used by ImageMatcher) ----
    def load_index(self) -> List[Tuple[int, int, str]]:
        """Return (card_id, phash, descriptor_path) for every card that has a pHash."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, phash, descriptor_path FROM cards WHERE phash IS NOT NULL"
            ).fetchall()
        return [(r["id"], _to_unsigned64(r["phash"]), r["descriptor_path"] or "") for r in rows]

    # ---- cards ----
    def get_card(self, card_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            r = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return dict(r) if r else None

    def find_by_api_id(self, api_source: str, api_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            r = conn.execute(
                "SELECT * FROM cards WHERE api_source = ? AND api_id = ?", (api_source, api_id)
            ).fetchone()
        return dict(r) if r else None

    def upsert_card(self, card: CandidateCard, *, phash: Optional[int] = None,
                    descriptor_path: str = "", image_path: str = "") -> int:
        """Insert or update a card by (api_source, api_id). Returns the row id."""
        phash = _to_signed64(phash)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM cards WHERE api_source = ? AND api_id = ?",
                (card.source, card.api_id),
            ).fetchone()
            meta = json.dumps(card.metadata or {})
            if existing:
                cid = existing["id"]
                conn.execute(
                    """UPDATE cards SET game=?, card_name=?, set_name=?, collector_number=?,
                           rarity=?, phash=COALESCE(?, phash),
                           descriptor_path=CASE WHEN ?<>'' THEN ? ELSE descriptor_path END,
                           image_path=CASE WHEN ?<>'' THEN ? ELSE image_path END,
                           metadata_json=? WHERE id=?""",
                    (card.game, card.card_name, card.set_name, card.collector_number,
                     card.rarity, phash, descriptor_path, descriptor_path,
                     image_path, image_path, meta, cid),
                )
                return cid
            cur = conn.execute(
                """INSERT INTO cards (game, card_name, set_name, collector_number, rarity,
                       api_source, api_id, phash, descriptor_path, image_path, metadata_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (card.game, card.card_name, card.set_name, card.collector_number, card.rarity,
                 card.source, card.api_id, phash, descriptor_path, image_path, meta),
            )
            return int(cur.lastrowid)

    def set_descriptor_path(self, card_id: int, path: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE cards SET descriptor_path=? WHERE id=?", (path, card_id))

    # ---- prices ----
    def get_fresh_price(self, card_id: int, max_age_hours: float) -> Optional[Tuple[float, str, str]]:
        card = self.get_card(card_id)
        if not card or card.get("price") is None or not card.get("price_updated_at"):
            return None
        try:
            updated = datetime.fromisoformat(card["price_updated_at"])
        except ValueError:
            return None
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - updated > timedelta(hours=max_age_hours):
            return None
        return float(card["price"]), card.get("currency", "USD"), card["price_updated_at"]

    def update_price(self, card_id: int, price: float, currency: str,
                     observed_at: str, basis: str = "") -> None:
        with self._connect() as conn:
            prev = conn.execute("SELECT price FROM cards WHERE id=?", (card_id,)).fetchone()
            conn.execute(
                "UPDATE cards SET price=?, currency=?, price_basis=?, price_updated_at=? WHERE id=?",
                (price, currency, basis, observed_at, card_id),
            )
            # append to history only when the value actually changes
            if prev is None or prev["price"] is None or abs((prev["price"] or 0) - price) > 1e-9:
                conn.execute(
                    "INSERT INTO price_history (card_id, price, currency, basis, observed_at) VALUES (?,?,?,?,?)",
                    (card_id, price, currency, basis, observed_at),
                )

    # ---- scan history ----
    def add_scan(self, *, matched: bool, card_id: Optional[int], card_name: str, game: str,
                 confidence: float, source: str, price: Optional[float], ocr_text: str,
                 image_path: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO scan_history
                       (matched, card_id, card_name, game, confidence, source, price, ocr_text, image_path)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (1 if matched else 0, card_id, card_name, game, confidence, source, price,
                 ocr_text, image_path),
            )
            return int(cur.lastrowid)

    def recent_scans(self, limit: int = 25) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scan_history ORDER BY scanned_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- maintenance ----
    def remove_orphan_storage_rows(self) -> int:
        removed = 0
        with self._connect() as conn:
            rows = conn.execute("SELECT id, path FROM storage_files").fetchall()
            for r in rows:
                if not Path(r["path"]).exists():
                    conn.execute("DELETE FROM storage_files WHERE id=?", (r["id"],))
                    removed += 1
        return removed

    def card_count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM cards").fetchone()["n"])

    def db_size_bytes(self) -> int:
        p = Path(self.db_path)
        return p.stat().st_size if p.exists() else 0
