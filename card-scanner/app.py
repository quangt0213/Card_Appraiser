"""Application factory. Wires config -> repository -> providers -> services ->
pipeline -> Flask blueprints, and runs startup maintenance + OCR warmup.

Run:  python app.py        (after init_db.py / seed_sample_cards.py)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from flask import Flask

from config import Config, get_config
from database.repository import Repository
from providers.base import IdentityProvider, PriceProvider
from providers.identity.mock_identity import MockIdentityProvider
from providers.price.mock_price import MockPriceProvider
from services.descriptor_store import DescriptorStore
from services.display_service import DisplayService
from services.image_matcher import ImageMatcher
from services.job_service import SimpleJobService
from services.maintenance_service import MaintenanceService
from services.ocr_service import OcrService
from services.pricing_service import PricingService
from services.scan_gate import ScanGate
from services.scan_pipeline import PipelineDeps, ScanPipeline
from utils.logger import get_logger, setup_logging

log = get_logger("app")


@dataclass
class AppContext:
    config: Config
    repository: Repository
    jobs: SimpleJobService
    pipeline: ScanPipeline
    display: DisplayService
    gate: ScanGate


def _build_catalog(cfg: Config):
    """Shared TCGCSV local catalog (free, keyless) + background daily sync."""
    from providers.tcgcsv_catalog import TcgCsvCatalog, TcgCsvClient
    client = TcgCsvClient(cfg.tcgcsv_base_url, timeout=cfg.tcgcsv_timeout_sec,
                          max_retries=cfg.tcgcsv_max_retries)
    catalog = TcgCsvCatalog(cfg.tcgcsv_db_file, client, games=cfg.enabled_games,
                            refresh_hours=cfg.tcgcsv_refresh_hours)
    catalog.start_background_sync()
    return catalog


def _build_identity_providers(cfg: Config, catalog=None) -> List[IdentityProvider]:
    providers: List[IdentityProvider] = []
    if catalog is not None:
        from providers.identity.tcgcsv_identity import TcgCsvIdentityProvider
        for game in cfg.enabled_games:
            providers.append(TcgCsvIdentityProvider(catalog, game))
    elif cfg.card_data_provider == "tcgapis" and cfg.provider_configured:
        from providers.tcgapis_client import TCGAPIsClient
        from providers.identity.tcgapis_identity import TCGAPIsIdentityProvider
        client = TCGAPIsClient(cfg.tcgapis_base_url, cfg.tcgapis_api_key,
                               timeout=cfg.tcgapis_timeout_sec, max_retries=cfg.tcgapis_max_retries)
        for game in cfg.enabled_games:
            providers.append(TCGAPIsIdentityProvider(client, game))
    if cfg.enable_mock_provider or not providers:
        for game in cfg.enabled_games:
            providers.append(MockIdentityProvider(game))
    return providers


def _build_price_provider(cfg: Config, catalog=None) -> PriceProvider:
    if catalog is not None:
        from providers.price.tcgcsv_price import TcgCsvPriceProvider
        market = TcgCsvPriceProvider(catalog)
        if cfg.price_source == "market":
            return market
        # default 'sales': last N real sales, market as automatic fallback
        from providers.price.tcgplayer_sales_price import TCGplayerSalesPriceProvider
        return TCGplayerSalesPriceProvider(
            strategy=cfg.price_strategy, window=cfg.price_recent_sales_window,
            fallback=market if cfg.price_fallback_to_market else None,
            base_url=cfg.tcgplayer_sales_base_url,
            timeout=cfg.tcgcsv_timeout_sec, max_retries=cfg.tcgcsv_max_retries)
    if cfg.card_data_provider == "tcgapis" and cfg.provider_configured:
        from providers.tcgapis_client import TCGAPIsClient
        from providers.price.tcgapis_price import TCGAPIsPriceProvider
        client = TCGAPIsClient(cfg.tcgapis_base_url, cfg.tcgapis_api_key,
                               timeout=cfg.tcgapis_timeout_sec, max_retries=cfg.tcgapis_max_retries)
        return TCGAPIsPriceProvider(client, strategy=cfg.price_strategy,
                                    window=cfg.price_recent_sales_window,
                                    fallback_to_market=cfg.price_fallback_to_market)
    return MockPriceProvider()


def build_context(cfg: Optional[Config] = None) -> AppContext:
    cfg = cfg or get_config()
    cfg.ensure_dirs()

    repo = Repository(cfg.db_file)
    repo.initialize(Path(__file__).resolve().parent / "database" / "schema.sql")

    MaintenanceService(cfg, repo).run()

    from services.storage_manager import StorageManager
    storage = StorageManager(cfg.scans_dir, cfg.card_images_dir, cfg.candidate_temp_dir)
    descriptor_store = DescriptorStore(cfg.descriptors_dir)
    matcher = ImageMatcher(phash_max_distance=cfg.phash_max_distance,
                           orb_shortlist=cfg.orb_shortlist,
                           descriptor_loader=descriptor_store.load)
    ocr = OcrService(langs=cfg.ocr_langs, gpu=cfg.ocr_gpu, enabled=cfg.ocr_enabled)
    catalog = _build_catalog(cfg) if cfg.card_data_provider == "tcgcsv" else None
    identity = _build_identity_providers(cfg, catalog)
    pricing = PricingService(_build_price_provider(cfg, catalog), repository=repo,
                             refresh_min_hours=cfg.price_refresh_min_hours)
    display = DisplayService(cfg.display_state_file)

    deps = PipelineDeps(
        repository=repo, storage=storage, matcher=matcher, ocr=ocr,
        identity_providers=identity, pricing=pricing, descriptor_store=descriptor_store,
        display=display, local_threshold=cfg.local_match_threshold,
        remote_threshold=cfg.remote_match_threshold, ocr_enabled=cfg.ocr_enabled,
    )
    pipeline = ScanPipeline(deps)
    jobs = SimpleJobService(workers=cfg.scan_workers, task_timeout_sec=cfg.scan_task_timeout_sec)

    gate = ScanGate()

    return AppContext(config=cfg, repository=repo, jobs=jobs, pipeline=pipeline,
                      display=display, gate=gate)


def create_app(cfg: Optional[Config] = None) -> Flask:
    cfg = cfg or get_config()
    setup_logging(Path(__file__).resolve().parent, cfg.debug)
    ctx = build_context(cfg)

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = cfg.max_upload_bytes
    app.config["ctx"] = ctx

    from routes.scan_routes import build_scan_blueprint
    from routes.ui_routes import build_ui_blueprint
    app.register_blueprint(build_scan_blueprint(ctx))
    app.register_blueprint(build_ui_blueprint(ctx))

    # optional: pre-load the OCR model so the first real scan isn't slow
    if cfg.ocr_enabled:
        ctx.pipeline.d.ocr.warmup()

    log.info("app ready (cards=%d, providers=%d, card_data_provider=%s, provider_configured=%s)",
             ctx.repository.card_count(), len(ctx.pipeline.d.identity_providers),
             cfg.card_data_provider, cfg.provider_configured)
    return app


def main() -> None:
    cfg = get_config()
    app = create_app(cfg)
    app.run(host=cfg.host, port=cfg.port, debug=cfg.debug, threaded=True)


if __name__ == "__main__":
    main()
