# posting_rules.py
from __future__ import annotations

from typing import Final


SCORE_THRESHOLD: Final[int] = 70

# Very simple heuristic list of "national" networks for NBA / WNBA.
NATIONAL_KEYWORDS: Final[list[str]] = [
    "ESPN",
    "ESPN2",
    "ESPN+",
    "ABC",
    "TNT",
    "TBS",
    "NBATV",
    "NBA TV",
    "ION",
    "AMAZON",
    "PRIME VIDEO",
    "CBS",
    "FOX",
]


def is_national_broadcast(network: str | None, sport: str | None = None) -> bool:
    """Return True if the network looks like a national TV broadcast."""
    if not network:
        return False
    up = network.upper()
    for kw in NATIONAL_KEYWORDS:
        if kw in up:
            return True
    return False


def should_auto_post(score: int, network: str | None, sport: str | None = None) -> bool:
    """
    Core posting rule:

    - Auto-post any game that is on national TV, OR
    - Auto-post any game with score >= SCORE_THRESHOLD.

    Fallback (highest game of the night) is handled in main.py.
    """
    if score >= SCORE_THRESHOLD:
        return True
    if is_national_broadcast(network, sport):
        return True
    return False
