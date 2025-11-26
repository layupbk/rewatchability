# scoring.py
# Rewatchability Score™ master formulas (LOCKED)
# Shared display range: 40–100, with rare 100s when EI exceeds E_MAX.

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ScoreResult:
    score: int
    sport: str
    ei: float


# ======================================================================
# COMMON NOTES
# ======================================================================
#
# - All sports share the same piecewise shape:
#     EI ≤ E_MIN        -> 40
#     E_MIN → E_MED     -> 40 → 70
#     E_MED → E_90      -> 70 → 90
#     E_90 → E_99       -> 90 → 99
#     E_99 → E_MAX      -> 99 → 100
#     EI > E_MAX        -> 100
#
# - Scores are clamped to [40, 100] and rounded to nearest int.
# - EI values passed into these functions are already scaled
#   upstream (via EI_SCALE in main.py).


# ======================================================================
# NBA V1
# ======================================================================

NBA_E_MIN = 0.00536
NBA_E_MED = 0.16262
NBA_E_90  = 0.2632740
NBA_E_99  = 0.3418272
NBA_E_MAX = 0.42322


def _score_nba(e: float) -> int:
    E = float(e)
    if E <= NBA_E_MIN:
        s = 40.0
    elif E <= NBA_E_MED:
        s = 40.0 + 30.0 * (E - NBA_E_MIN) / (NBA_E_MED - NBA_E_MIN)
    elif E <= NBA_E_90:
        s = 70.0 + 20.0 * (E - NBA_E_MED) / (NBA_E_90 - NBA_E_MED)
    elif E <= NBA_E_99:
        s = 90.0 + 9.0 * (E - NBA_E_90) / (NBA_E_99 - NBA_E_90)
    elif E <= NBA_E_MAX:
        s = 99.0 + 1.0 * (E - NBA_E_99) / (NBA_E_MAX - NBA_E_99)
    else:
        s = 100.0

    if s < 40.0:
        s = 40.0
    if s > 100.0:
        s = 100.0
    return int(round(s))


# ======================================================================
# NFL V1
# ======================================================================

NFL_E_MIN = 0.00984
NFL_E_MED = 0.087269
NFL_E_90  = 0.1444728
NFL_E_99  = 0.22292766
NFL_E_MAX = 0.297374


def _score_nfl(e: float) -> int:
    E = float(e)
    if E <= NFL_E_MIN:
        s = 40.0
    elif E <= NFL_E_MED:
        s = 40.0 + 30.0 * (E - NFL_E_MIN) / (NFL_E_MED - NFL_E_MIN)
    elif E <= NFL_E_90:
        s = 70.0 + 20.0 * (E - NFL_E_MED) / (NFL_E_90 - NFL_E_MED)
    elif E <= NFL_E_99:
        s = 90.0 + 9.0 * (E - NFL_E_90) / (NFL_E_99 - NFL_E_90)
    elif E <= NFL_E_MAX:
        s = 99.0 + 1.0 * (E - NFL_E_99) / (NFL_E_MAX - NFL_E_99)
    else:
        s = 100.0

    if s < 40.0:
        s = 40.0
    if s > 100.0:
        s = 100.0
    return int(round(s))


# ======================================================================
# MLB V1
# ======================================================================

MLB_E_MIN = 0.00326
MLB_E_MED = 0.04436
MLB_E_90  = 0.0755340
MLB_E_99  = 0.1103992
MLB_E_MAX = 0.16694


def _score_mlb(e: float) -> int:
    E = float(e)
    if E <= MLB_E_MIN:
        s = 40.0
    elif E <= MLB_E_MED:
        s = 40.0 + 30.0 * (E - MLB_E_MIN) / (MLB_E_MED - MLB_E_MIN)
    elif E <= MLB_E_90:
        s = 70.0 + 20.0 * (E - MLB_E_MED) / (MLB_E_90 - MLB_E_MED)
    elif E <= MLB_E_99:
        s = 90.0 + 9.0 * (E - MLB_E_90) / (MLB_E_99 - MLB_E_90)
    elif E <= MLB_E_MAX:
        s = 99.0 + 1.0 * (E - MLB_E_99) / (MLB_E_MAX - MLB_E_99)
    else:
        s = 100.0

    if s < 40.0:
        s = 40.0
    if s > 100.0:
        s = 100.0
    return int(round(s))


# ======================================================================
# NCAAF V1 (College Football)
# ======================================================================

NCAAF_E_MIN = 0.000026
NCAAF_E_MED = 0.060416
NCAAF_E_90  = 0.127918
NCAAF_E_99  = 0.1876307
NCAAF_E_MAX = 0.286786


def _score_ncaaf(e: float) -> int:
    E = float(e)
    if E <= NCAAF_E_MIN:
        s = 40.0
    elif E <= NCAAF_E_MED:
        s = 40.0 + 30.0 * (E - NCAAF_E_MIN) / (NCAAF_E_MED - NCAAF_E_MIN)
    elif E <= NCAAF_E_90:
        s = 70.0 + 20.0 * (E - NCAAF_E_MED) / (NCAAF_E_90 - NCAAF_E_MED)
    elif E <= NCAAF_E_99:
        s = 90.0 + 9.0 * (E - NCAAF_E_90) / (NCAAF_E_99 - NCAAF_E_90)
    elif E <= NCAAF_E_MAX:
        s = 99.0 + 1.0 * (E - NCAAF_E_99) / (NCAAF_E_MAX - NCAAF_E_99)
    else:
        s = 100.0

    if s < 40.0:
        s = 40.0
    if s > 100.0:
        s = 100.0
    return int(round(s))


# ======================================================================
# NCAAB V1 (Men's College Basketball)
# ======================================================================

NCAAB_E_MIN = 0.00002
NCAAB_E_MED = 0.07897
NCAAB_E_90  = 0.156834
NCAAB_E_99  = 0.2132926
NCAAB_E_MAX = 0.33728


def _score_ncaab(e: float) -> int:
    E = float(e)
    if E <= NCAAB_E_MIN:
        s = 40.0
    elif E <= NCAAB_E_MED:
        s = 40.0 + 30.0 * (E - NCAAB_E_MIN) / (NCAAB_E_MED - NCAAB_E_MIN)
    elif E <= NCAAB_E_90:
        s = 70.0 + 20.0 * (E - NCAAB_E_MED) / (NCAAB_E_90 - NCAAB_E_MED)
    elif E <= NCAAB_E_99:
        s = 90.0 + 9.0 * (E - NCAAB_E_90) / (NCAAB_E_99 - NCAAB_E_90)
    elif E <= NCAAB_E_MAX:
        s = 99.0 + 1.0 * (E - NCAAB_E_99) / (NCAAB_E_MAX - NCAAB_E_99)
    else:
        s = 100.0

    if s < 40.0:
        s = 40.0
    if s > 100.0:
        s = 100.0
    return int(round(s))


# ======================================================================
# MAIN DISPATCH
# ======================================================================

def score_game(sport: str, ei_raw: float, *, scale: float = 1.0) -> ScoreResult:
    """
    Main entrypoint used by main.py.

    Args:
      sport: one of "NBA", "NFL", "MLB", "NCAAF", "NCAAB"
      ei_raw: scaled EI value (already multiplied by EI_SCALE in main.py)
      scale: optional extra scaling factor (usually 1.0)

    Returns:
      ScoreResult(score=int, sport=str, ei=float)
    """
    key = sport.upper()
    E = float(ei_raw) * float(scale)

    if key == "NBA":
        s = _score_nba(E)
    elif key == "NFL":
        s = _score_nfl(E)
    elif key == "MLB":
        s = _score_mlb(E)
    elif key in ("NCAAF", "CFB"):
        s = _score_ncaaf(E)
    elif key in ("NCAAB", "CBB"):
        s = _score_ncaab(E)
    else:
        # Unknown sport: return safe floor so we don't publish junk
        s = 40

    return ScoreResult(score=s, sport=key, ei=E)
