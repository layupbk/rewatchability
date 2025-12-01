# scoring.py
# Basketball-only Rewatchability Score™ formulas using inpredictable's Excitement.
#
# We support:
#   - NBA
#   - WNBA
#
# Input:
#   excitement = inpredictable "Excitement" value for a single game
#               (float, usually in the 0–20 range).
#
# Formula (for both leagues):
#   score = 40 + 4 * excitement
# Then clamped to [40, 99] and rounded to nearest int.

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScoreResult:
    score: int
    sport: str
    excitement: float


def score_game(league_key: str, excitement: float) -> ScoreResult:
    """Convert raw Excitement into a 40–99 Rewatchability Score."""
    key = (league_key or "NBA").upper()

    try:
        e = float(excitement)
    except (TypeError, ValueError):
        e = 0.0

    if e < 0.0:
        e = 0.0

    s = 40.0 + 4.0 * e

    if s < 40.0:
        s = 40.0
    if s > 99.0:
        s = 99.0

    score_int = int(round(s))

    if key not in ("NBA", "WNBA"):
        key = "NBA"

    return ScoreResult(score=score_int, sport=key, excitement=e)
