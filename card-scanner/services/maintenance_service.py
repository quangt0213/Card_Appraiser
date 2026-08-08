"""Bounded startup cleanup. Kept small and safe for a single-scanner Pi workload."""
from __future__ import annotations

from utils.logger import get_logger
from services import cache_policy

log = get_logger("maintenance")


class MaintenanceService:
    def __init__(self, config, repository=None):
        self.cfg = config
        self.repo = repository

    def run(self) -> dict:
        cfg = self.cfg
        summary = {"removed_expired": 0, "evicted": 0}

        # 1. prune expired candidate temp downloads
        for f in cache_policy.expired_files(cfg.candidate_temp_dir, cfg.candidate_temp_ttl_hours * 3600):
            _safe_unlink(f); summary["removed_expired"] += 1

        # 2. prune old uploaded scan originals
        for f in cache_policy.expired_files(cfg.scans_dir, cfg.scan_original_ttl_days * 86400):
            _safe_unlink(f); summary["removed_expired"] += 1

        # 3. enforce LRU caps on the image cache
        for f in cache_policy.lru_eviction_plan(cfg.card_images_dir, cfg.image_cache_max_bytes):
            _safe_unlink(f); summary["evicted"] += 1

        # 4. drop DB rows whose files are gone
        if self.repo is not None:
            try:
                summary["orphan_rows_removed"] = self.repo.remove_orphan_storage_rows()
            except Exception as exc:  # pragma: no cover
                log.warning("orphan cleanup skipped: %s", exc)

        log.info("maintenance summary: %s", summary)
        return summary


def _safe_unlink(path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
