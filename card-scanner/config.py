"""Typed configuration loaded once from the environment (.env).

Everything else in the app imports `get_config()` rather than reading os.environ
directly, so values are parsed and validated in exactly one place.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # python-dotenv optional at runtime
    pass


def _b(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _s(name: str, default: str) -> str:
    return os.getenv(name, default)


def _list(name: str, default: str) -> List[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class Config:
    # server
    host: str = field(default_factory=lambda: _s("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _i("PORT", 5000))
    debug: bool = field(default_factory=lambda: _b("DEBUG", False))
    scan_workers: int = field(default_factory=lambda: _i("SCAN_WORKERS", 1))
    blocking_scan_response: bool = field(default_factory=lambda: _b("BLOCKING_SCAN_RESPONSE", True))
    scan_task_timeout_sec: float = field(default_factory=lambda: _f("SCAN_TASK_TIMEOUT_SEC", 30))
    max_upload_bytes: int = field(default_factory=lambda: _i("MAX_UPLOAD_BYTES", 12_000_000))

    # matching
    local_match_threshold: float = field(default_factory=lambda: _f("LOCAL_MATCH_THRESHOLD", 0.72))
    remote_match_threshold: float = field(default_factory=lambda: _f("REMOTE_MATCH_THRESHOLD", 0.60))
    phash_max_distance: int = field(default_factory=lambda: _i("PHASH_MAX_DISTANCE", 10))
    orb_shortlist: int = field(default_factory=lambda: _i("ORB_SHORTLIST", 5))

    # ocr
    ocr_enabled: bool = field(default_factory=lambda: _b("OCR_ENABLED", True))
    ocr_langs: List[str] = field(default_factory=lambda: _list("OCR_LANGS", "en"))
    ocr_gpu: bool = field(default_factory=lambda: _b("OCR_GPU", False))

    # card data provider selection: tcgcsv (free, default) | tcgapis (paid) | mock
    card_data_provider: str = field(default_factory=lambda: _s("CARD_DATA_PROVIDER", "tcgcsv").strip().lower())

    # provider (TCGCSV -- free, keyless; https://tcgcsv.com)
    tcgcsv_base_url: str = field(default_factory=lambda: _s("TCGCSV_BASE_URL", "https://tcgcsv.com/tcgplayer"))
    tcgcsv_timeout_sec: float = field(default_factory=lambda: _f("TCGCSV_TIMEOUT_SEC", 10))
    tcgcsv_max_retries: int = field(default_factory=lambda: _i("TCGCSV_MAX_RETRIES", 2))
    tcgcsv_refresh_hours: float = field(default_factory=lambda: _f("TCGCSV_REFRESH_HOURS", 24))

    # provider (TCGAPIs -- paid; kept for CARD_DATA_PROVIDER=tcgapis)
    tcgapis_base_url: str = field(default_factory=lambda: _s("TCGAPIS_BASE_URL", "https://api.tcgapis.com"))
    tcgapis_api_key: str = field(default_factory=lambda: _s("TCGAPIS_API_KEY", ""))
    tcgapis_timeout_sec: float = field(default_factory=lambda: _f("TCGAPIS_TIMEOUT_SEC", 8))
    tcgapis_max_retries: int = field(default_factory=lambda: _i("TCGAPIS_MAX_RETRIES", 2))

    # pricing
    # PRICE_SOURCE: sales  -> last N real sales (TCGplayer latestsales, free but
    #                         unofficial), market fallback on failure
    #               market -> TCGCSV daily market price only
    price_source: str = field(default_factory=lambda: _s("PRICE_SOURCE", "sales").strip().lower())
    tcgplayer_sales_base_url: str = field(default_factory=lambda: _s(
        "TCGPLAYER_SALES_BASE_URL", "https://mpapi.tcgplayer.com/v2/product"))
    price_strategy: str = field(default_factory=lambda: _s("PRICE_STRATEGY", "median_recent"))
    price_recent_sales_window: int = field(default_factory=lambda: _i("PRICE_RECENT_SALES_WINDOW", 3))
    price_fallback_to_market: bool = field(default_factory=lambda: _b("PRICE_FALLBACK_TO_MARKET", True))
    price_refresh_min_hours: float = field(default_factory=lambda: _f("PRICE_REFRESH_MIN_HOURS", 24))

    # games
    enabled_games: List[str] = field(default_factory=lambda: _list("ENABLED_GAMES", "pokemon,onepiece"))
    enable_mock_provider: bool = field(default_factory=lambda: _b("ENABLE_MOCK_PROVIDER", True))

    # storage caps
    scans_max_bytes: int = field(default_factory=lambda: _i("SCANS_MAX_BYTES", 1_000_000_000))
    image_cache_max_bytes: int = field(default_factory=lambda: _i("IMAGE_CACHE_MAX_BYTES", 2_000_000_000))
    candidate_temp_max_bytes: int = field(default_factory=lambda: _i("CANDIDATE_TEMP_MAX_BYTES", 512_000_000))
    descriptors_max_bytes: int = field(default_factory=lambda: _i("DESCRIPTORS_MAX_BYTES", 256_000_000))
    min_free_space_bytes: int = field(default_factory=lambda: _i("MIN_FREE_SPACE_BYTES", 20_000_000_000))
    scan_original_ttl_days: int = field(default_factory=lambda: _i("SCAN_ORIGINAL_TTL_DAYS", 14))
    candidate_temp_ttl_hours: int = field(default_factory=lambda: _i("CANDIDATE_TEMP_TTL_HOURS", 72))

    # paths
    db_path: str = field(default_factory=lambda: _s("DB_PATH", "carddata.db"))
    data_dir: str = field(default_factory=lambda: _s("DATA_DIR", "data"))

    # ---- derived path helpers ----
    @property
    def base_dir(self) -> Path:
        return Path(__file__).resolve().parent

    @property
    def data_path(self) -> Path:
        p = self.data_dir
        return Path(p) if os.path.isabs(p) else self.base_dir / p

    @property
    def db_file(self) -> Path:
        p = self.db_path
        return Path(p) if os.path.isabs(p) else self.base_dir / p

    @property
    def scans_dir(self) -> Path:
        return self.data_path / "scans"

    @property
    def card_images_dir(self) -> Path:
        return self.data_path / "cache" / "card_images"

    @property
    def candidate_temp_dir(self) -> Path:
        return Path(os.getenv("CANDIDATE_TEMP_DIR", str(self.data_path / "cache" / "candidate_temp")))

    @property
    def scan_debug_dir(self) -> Path:
        return self.data_path / "cache" / "scan_debug"

    @property
    def descriptors_dir(self) -> Path:
        return self.data_path / "descriptors"

    @property
    def display_state_file(self) -> Path:
        return self.data_path / "cache" / "display_state.json"

    def ensure_dirs(self) -> None:
        for d in (
            self.scans_dir, self.card_images_dir, self.candidate_temp_dir,
            self.scan_debug_dir, self.descriptors_dir, self.data_path / "cache",
        ):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def provider_configured(self) -> bool:
        """A real (non-mock) card data source is available."""
        if self.card_data_provider == "tcgcsv":
            return True  # keyless -- always available
        return self.card_data_provider == "tcgapis" and bool(self.tcgapis_api_key)

    @property
    def tcgcsv_db_file(self) -> Path:
        return self.data_path / "cache" / "tcgcsv_catalog.db"


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()
