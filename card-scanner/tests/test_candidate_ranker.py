from providers.base import CandidateCard
from services import candidate_ranker


def _card(name, number, api_id):
    return CandidateCard(game="pokemon", card_name=name, collector_number=number,
                         source="mock", api_id=api_id)


def test_number_match_dominates():
    cards = [_card("Pikachu", "58/102", "a"), _card("Charizard", "4/102", "b")]
    best = candidate_ranker.best(cards, ocr_title="Pikachu", ocr_number="58/102")
    assert best.card.api_id == "a"
    assert best.number_exact
    assert best.confidence >= 0.8


def test_name_only_when_number_missing():
    cards = [_card("Pikachu", "58/102", "a"), _card("Charizard", "4/102", "b")]
    best = candidate_ranker.best(cards, ocr_title="Charizrd", ocr_number="")
    assert best.card.api_id == "b"


def test_low_confidence_when_nothing_matches():
    cards = [_card("Blastoise", "2/102", "c")]
    best = candidate_ranker.best(cards, ocr_title="Mewtwo", ocr_number="10/102")
    assert best.confidence < 0.6
