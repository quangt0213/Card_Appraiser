import numpy as np

from services.image_matcher import (ImageMatcher, LocalCard, compute_phash_int)
from tests.conftest import make_jpeg
from utils.image_utils import decode_jpeg


def _img(seed):
    return decode_jpeg(make_jpeg(seed))


def test_phash_is_stable():
    img = _img(1)
    assert compute_phash_int(img) == compute_phash_int(img)


def test_matcher_picks_correct_card():
    a, b = _img(1), _img(2)
    index = [
        LocalCard(card_id=10, phash=compute_phash_int(a)),
        LocalCard(card_id=20, phash=compute_phash_int(b)),
    ]
    m = ImageMatcher(phash_max_distance=10, orb_shortlist=3)
    res = m.match(a, index)
    assert res.card_id == 10
    assert res.method == "phash"
    assert res.score > 0.8


def test_empty_index_returns_none():
    res = ImageMatcher().match(_img(1), [])
    assert res.card_id is None
    assert res.method == "none"
