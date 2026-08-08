"""Seed a couple of sample cards (no images) so /history and the DB have content
during development. Run:  python database/seed_sample_cards.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_config              # noqa: E402
from database.repository import Repository  # noqa: E402
from providers.base import CandidateCard    # noqa: E402

SAMPLES = [
    CandidateCard(game="pokemon", card_name="Pikachu", set_name="Base Set",
                  collector_number="58/102", rarity="Common", source="seed", api_id="seed-pika-58"),
    CandidateCard(game="pokemon", card_name="Charizard", set_name="Base Set",
                  collector_number="4/102", rarity="Rare Holo", source="seed", api_id="seed-char-4"),
    CandidateCard(game="onepiece", card_name="Monkey D. Luffy", set_name="Emperors in the New World",
                  collector_number="OP09-036", rarity="SR", source="seed", api_id="seed-luffy-op09-036"),
]


def main() -> None:
    cfg = get_config()
    repo = Repository(cfg.db_file)
    repo.initialize(Path(__file__).resolve().parent / "schema.sql")
    for c in SAMPLES:
        cid = repo.upsert_card(c)
        print(f"  seeded card #{cid}: {c.card_name}")
    print(f"Done. {repo.card_count()} cards in DB.")


if __name__ == "__main__":
    main()
