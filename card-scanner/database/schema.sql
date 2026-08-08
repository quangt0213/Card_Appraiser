-- Card scanner schema. Full-size images live on disk (see storage_files); SQLite
-- holds compact metadata, hashes, the pHash index, prices, and history only.

PRAGMA journal_mode = WAL;      -- better read/write concurrency, fewer fsyncs (kinder to the SD card)
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS cards (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    game              TEXT NOT NULL,
    card_name         TEXT NOT NULL,
    set_name          TEXT DEFAULT '',
    collector_number  TEXT DEFAULT '',
    rarity            TEXT DEFAULT '',
    api_source        TEXT DEFAULT '',          -- e.g. 'tcgapis'
    api_id            TEXT DEFAULT '',          -- provider productId
    phash             INTEGER,                  -- 64-bit perceptual hash of the card art
    descriptor_path   TEXT DEFAULT '',          -- ORB .npz path (Tier 2)
    image_path        TEXT DEFAULT '',          -- cached full-size art (Tier 3)
    price             REAL,                     -- latest recent-sales-derived value
    currency          TEXT DEFAULT 'USD',
    price_basis       TEXT DEFAULT '',          -- how `price` was derived
    price_updated_at  TEXT DEFAULT '',          -- ISO timestamp
    metadata_json     TEXT DEFAULT '{}',
    created_at        TEXT DEFAULT (datetime('now')),
    UNIQUE(api_source, api_id)
);
CREATE INDEX IF NOT EXISTS idx_cards_game_number ON cards(game, collector_number);

CREATE TABLE IF NOT EXISTS card_images (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id    INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    path       TEXT NOT NULL,
    hash       TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scan_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at  TEXT DEFAULT (datetime('now')),
    matched     INTEGER NOT NULL DEFAULT 0,
    card_id     INTEGER REFERENCES cards(id) ON DELETE SET NULL,
    card_name   TEXT DEFAULT '',
    game        TEXT DEFAULT '',
    confidence  REAL DEFAULT 0,
    source      TEXT DEFAULT '',                -- local_db | remote_api | none
    price       REAL,
    ocr_text    TEXT DEFAULT '',
    image_path  TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_scan_history_time ON scan_history(scanned_at DESC);

CREATE TABLE IF NOT EXISTS api_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cache_key   TEXT NOT NULL UNIQUE,
    payload     TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    expires_at  TEXT
);

CREATE TABLE IF NOT EXISTS storage_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tier         INTEGER NOT NULL,              -- 1..4
    path         TEXT NOT NULL UNIQUE,
    hash         TEXT DEFAULT '',
    size_bytes   INTEGER DEFAULT 0,
    expires_at   TEXT,
    last_access  TEXT,
    pinned       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS price_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id      INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    price        REAL NOT NULL,
    currency     TEXT DEFAULT 'USD',
    basis        TEXT DEFAULT '',
    observed_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_price_history_card ON price_history(card_id, observed_at DESC);
