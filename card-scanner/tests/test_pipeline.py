"""End-to-end pipeline test, fully offline: fake detector, stub OCR, mock identity
and price providers, a real matcher, and a temp SQLite DB."""
from pathlib import Path

from database.repository import Repository
from providers.identity.mock_identity import MockIdentityProvider
from providers.price.mock_price import MockPriceProvider
from services.descriptor_store import DescriptorStore
from services.image_matcher import ImageMatcher
from services.pricing_service import PricingService
from services.scan_pipeline import PipelineDeps, ScanPipeline
from services.storage_manager import StorageManager
from tests.conftest import StubOcr, fake_detect, make_jpeg


def _build_pipeline(tmp_path: Path, schema_path: Path) -> ScanPipeline:
    repo = Repository(tmp_path / "test.db")
    repo.initialize(schema_path)
    storage = StorageManager(tmp_path / "scans", tmp_path / "imgs", tmp_path / "temp")
    dstore = DescriptorStore(tmp_path / "desc")
    matcher = ImageMatcher(phash_max_distance=10, orb_shortlist=3, descriptor_loader=dstore.load)
    pricing = PricingService(MockPriceProvider(), repository=repo, refresh_min_hours=24)
    deps = PipelineDeps(
        repository=repo, storage=storage, matcher=matcher, ocr=StubOcr("Pikachu\n58/102"),
        identity_providers=[MockIdentityProvider("pokemon")], pricing=pricing,
        descriptor_store=dstore, display=None, detect=fake_detect,
        local_threshold=0.72, remote_threshold=0.60, ocr_enabled=True,
    )
    return ScanPipeline(deps), repo


def test_remote_match_then_local_hit(tmp_path, schema_path):
    pipe, repo = _build_pipeline(tmp_path, schema_path)
    jpeg = make_jpeg(7)

    # First scan: no local index -> OCR + mock provider -> remote match, price from recent sales
    r1 = pipe.process(jpeg)
    assert r1["matched"] is True
    assert r1["card_name"] == "Pikachu"
    assert r1["source"] == "remote_api"
    assert r1["price"] == 3.6            # median of mock recent sales
    assert r1["number_exact"] is True
    assert repo.card_count() == 1

    # Second scan of the same image: should now resolve from the local index
    r2 = pipe.process(jpeg)
    assert r2["matched"] is True
    assert r2["source"] == "local_db"
    assert r2["db_id"] == r1["db_id"]
    assert repo.card_count() == 1        # no duplicate card created


def test_no_candidates_is_graceful(tmp_path, schema_path):
    repo = Repository(tmp_path / "t2.db"); repo.initialize(schema_path)
    storage = StorageManager(tmp_path / "s", tmp_path / "i", tmp_path / "t")
    dstore = DescriptorStore(tmp_path / "d")
    matcher = ImageMatcher(descriptor_loader=dstore.load)
    pricing = PricingService(MockPriceProvider(), repository=repo)
    deps = PipelineDeps(
        repository=repo, storage=storage, matcher=matcher,
        ocr=StubOcr("Zzzznonsense\n999/999"),
        identity_providers=[MockIdentityProvider("onepiece")],  # wrong game -> no hit
        pricing=pricing, descriptor_store=dstore, detect=fake_detect,
    )
    pipe = ScanPipeline(deps)
    r = pipe.process(make_jpeg(3))
    assert r["matched"] is False
    assert r["source"] == "none"
    # history still records the failed attempt
    assert len(repo.recent_scans()) == 1


def test_history_records_scans(tmp_path, schema_path):
    pipe, repo = _build_pipeline(tmp_path, schema_path)
    pipe.process(make_jpeg(7))
    scans = repo.recent_scans()
    assert len(scans) == 1
    assert scans[0]["card_name"] == "Pikachu"
