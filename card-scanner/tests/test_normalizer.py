from services import normalizer


def test_extract_pokemon_number():
    assert normalizer.extract_collector_number("HP 60  58/102  Base") == "58/102"


def test_extract_onepiece_number():
    assert normalizer.extract_collector_number("Luffy  OP09-036  SR") == "OP09-036"


def test_digit_fixup_in_number():
    # OCR reads O for 0 and l for 1 inside the number
    assert normalizer.extract_collector_number("5B/1O2") in {"58/102", "5B/102"}


def test_number_match_ignores_padding():
    assert normalizer.number_match("4/102", "004/102")
    assert not normalizer.number_match("4/102", "5/102")


def test_name_score_ranges():
    assert normalizer.name_score("Pikachu", "Pikachu") == 1.0
    assert normalizer.name_score("Pikchu", "Pikachu") > 0.7
    assert normalizer.name_score("", "Pikachu") == 0.0


def test_extract_title_prefers_alpha_line():
    raw = "Charizard\n4/102\nHP 120"
    assert normalizer.extract_title(raw) == "Charizard"


def test_dedupe():
    class C:
        def __init__(self, n): self.card_name = n; self.set_name = "s"; self.collector_number = "1"
    out = normalizer.dedupe_candidates([C("a"), C("a"), C("b")])
    assert len(out) == 2
