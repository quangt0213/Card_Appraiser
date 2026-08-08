"""RapidFuzz-backed text normalization -- the layer that stitches noisy OCR to
clean provider data. Pure functions, no I/O, heavily unit-tested.

Responsibilities:
  * clean raw OCR text (fix common confusions, strip noise)
  * extract a collector number (Pokemon NNN/NNN, One Piece OPxx-NNN, etc.)
  * fuzzy-score a candidate card name against the OCR'd title
  * de-duplicate near-identical candidates before expensive image matching
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple

# RapidFuzz is the intended engine (fast C++ implementation, used on the Pi). We
# fall back to a stdlib difflib shim only if it isn't importable, so the app never
# hard-crashes on a minimal environment. On the Pi, `pip install rapidfuzz` -> real thing.
try:
    from rapidfuzz import fuzz, process
    HAVE_RAPIDFUZZ = True
except Exception:  # pragma: no cover - exercised only where rapidfuzz is absent
    HAVE_RAPIDFUZZ = False
    import difflib

    class _FuzzShim:
        @staticmethod
        def WRatio(a: str, b: str) -> float:
            return difflib.SequenceMatcher(None, a, b).ratio() * 100.0

        token_set_ratio = WRatio

    class _ProcessShim:
        @staticmethod
        def extractOne(query, choices, scorer=None):
            best_i, best_s = None, -1.0
            for i, c in enumerate(choices):
                s = difflib.SequenceMatcher(None, query, c).ratio() * 100.0
                if s > best_s:
                    best_i, best_s = i, s
            if best_i is None:
                return None
            return choices[best_i], best_s, best_i

    fuzz = _FuzzShim()       # type: ignore
    process = _ProcessShim()  # type: ignore

# Common OCR confusions, applied only inside number regions where we expect digits.
_DIGIT_FIXUP = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8"})

# Collector-number patterns, most specific first.
_NUMBER_PATTERNS = [
    re.compile(r"\b([A-Z]{2}\d{2}-\d{2,3})\b"),   # One Piece / many: OP09-036, ST01-001
    # Pokemon fractions: 58/102. Digit positions also accept common OCR
    # confusions (O/I/l/|/S/B) so "5B/1O2" still matches; _DIGIT_FIXUP then
    # repairs them. Requires at least one real digit per side.
    re.compile(r"\b((?=[OIlSB|]*\d)[\dOIlSB|]{1,3}\s*/\s*(?=[OIlSB|]*\d)[\dOIlSB|]{1,3})\b"),
    re.compile(r"\b([A-Z]{1,4}-?\d{2,3})\b"),      # promos: SWSH039, XY12
]


def clean_text(raw: str) -> str:
    """Collapse whitespace, drop control chars, keep readable card text."""
    if not raw:
        return ""
    text = re.sub(r"[^\w\s/\-.']", " ", raw)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_collector_number(raw: str) -> str:
    """Pull a normalized collector number out of noisy OCR text, or '' if none."""
    if not raw:
        return ""
    up = raw.upper()
    for pat in _NUMBER_PATTERNS:
        m = pat.search(up)
        if m:
            token = m.group(1)
            if "/" in token:
                left, right = token.split("/")
                left = left.strip().translate(_DIGIT_FIXUP)
                right = right.strip().translate(_DIGIT_FIXUP)
                return f"{int(left)}/{int(right)}" if left.isdigit() and right.isdigit() else f"{left}/{right}"
            if "-" in token:
                prefix, num = token.split("-", 1)
                num = num.translate(_DIGIT_FIXUP)
                return f"{prefix}-{num.zfill(3)}"
            return token
    return ""


def extract_title(raw: str) -> str:
    """Best-guess card name line from OCR output: the longest mostly-alpha line."""
    lines = [clean_text(l) for l in (raw or "").splitlines()]
    lines = [l for l in lines if l and not _NUMBER_PATTERNS[1].search(l)]
    if not lines:
        return clean_text(raw)
    # prefer the line with the most letters
    return max(lines, key=lambda l: sum(ch.isalpha() for ch in l))


def name_score(ocr_title: str, candidate_name: str) -> float:
    """0..1 fuzzy similarity between an OCR'd title and a candidate card name."""
    if not ocr_title or not candidate_name:
        return 0.0
    return fuzz.WRatio(ocr_title.lower(), candidate_name.lower()) / 100.0


def best_name_match(ocr_title: str, names: Iterable[str]) -> Optional[Tuple[str, float]]:
    names = list(names)
    if not names or not ocr_title:
        return None
    match = process.extractOne(ocr_title.lower(), [n.lower() for n in names], scorer=fuzz.WRatio)
    if not match:
        return None
    _, score, idx = match
    return names[idx], score / 100.0


def number_match(a: str, b: str) -> bool:
    """Loose equality between two collector numbers (ignore spacing/zero padding)."""
    def norm(x: str) -> str:
        x = (x or "").upper().replace(" ", "")
        if "/" in x:
            l, _, r = x.partition("/")
            return f"{l.lstrip('0') or '0'}/{r.lstrip('0') or '0'}"
        return x
    return bool(a) and bool(b) and norm(a) == norm(b)


def dedupe_candidates(candidates: List, key=lambda c: (c.card_name.lower(), c.set_name.lower(), c.collector_number)):
    """Collapse duplicate candidates so we don't image-match the same card twice."""
    seen = set()
    out = []
    for c in candidates:
        k = key(c)
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out
