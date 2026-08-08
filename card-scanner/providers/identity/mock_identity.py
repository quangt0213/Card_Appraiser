"""Offline identity provider for development and tests. No network."""
from __future__ import annotations

from typing import List

from providers.base import CandidateCard, IdentityProvider

_MOCK_DB = [
    CandidateCard(game="pokemon", card_name="Pikachu", set_name="Base Set",
                  collector_number="58/102", rarity="Common", source="mock",
                  api_id="mock-pika-58", image_url=""),
    CandidateCard(game="pokemon", card_name="Charizard", set_name="Base Set",
                  collector_number="4/102", rarity="Rare Holo", source="mock",
                  api_id="mock-char-4", image_url=""),
    CandidateCard(game="onepiece", card_name="Monkey D. Luffy", set_name="Emperors in the New World",
                  collector_number="OP09-036", rarity="SR", source="mock",
                  api_id="mock-luffy-op09-036", image_url=""),
]


class MockIdentityProvider(IdentityProvider):
    source = "mock"

    def __init__(self, game: str = "pokemon"):
        self.game = game
        self.name = f"mock:{game}"

    def search(self, query: str, *, number: str = "", limit: int = 20) -> List[CandidateCard]:
        q = (query or "").lower()
        n = number.replace(" ", "")
        out = []
        for c in _MOCK_DB:
            if c.game != self.game:
                continue
            if (q and q in c.card_name.lower()) or (n and n == c.collector_number.replace(" ", "")):
                out.append(c)
        if not out and q:  # loose fallback so demos always return something
            out = [c for c in _MOCK_DB if c.game == self.game]
        return out[:limit]
