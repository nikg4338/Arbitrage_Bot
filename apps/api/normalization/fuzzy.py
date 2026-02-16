from __future__ import annotations

import re
from difflib import SequenceMatcher


def _tokenize(value: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", value.lower()) if token]


def token_set_similarity(a: str, b: str) -> float:
    tokens_a = set(_tokenize(a))
    tokens_b = set(_tokenize(b))
    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    diff_a = tokens_a - intersection
    diff_b = tokens_b - intersection

    sorted_intersection = " ".join(sorted(intersection))
    sorted_a = " ".join(sorted(intersection | diff_a))
    sorted_b = " ".join(sorted(intersection | diff_b))

    r1 = SequenceMatcher(None, sorted_intersection, sorted_a).ratio()
    r2 = SequenceMatcher(None, sorted_intersection, sorted_b).ratio()
    r3 = SequenceMatcher(None, sorted_a, sorted_b).ratio()

    return max(r1, r2, r3)
