"""Deterministic hashed bag-of-words embedding (256 dims, L2-normalised)."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

DIMS = 256
_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-\.]*")
STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was were "
    "with there any last week what how does did do is isn't was about between during than then "
    "any please tell me show".split()
)


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN.findall(text.lower()):
        tok = tok.strip(".-")
        if len(tok) < 2 or tok in STOPWORDS:
            continue
        out.append(tok)
    return out


def top_tokens(text: str, n: int = 8) -> set[str]:
    counts = Counter(tokenize(text))
    return {tok for tok, _ in counts.most_common(n)}


def _slot(token: str) -> tuple[int, float]:
    digest = hashlib.sha1(token.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % DIMS
    sign = 1.0 if digest[4] & 1 else -1.0
    return index, sign


def embed(text: str) -> list[float]:
    vec = [0.0] * DIMS
    for tok, count in Counter(tokenize(text)).items():
        index, sign = _slot(tok)
        vec[index] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)
