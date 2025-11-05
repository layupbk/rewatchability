# scoring.py
# Rewatchability Score™ master formulas (LOCKED)
# Shared display range: 40–99, with NFL/MLB allowing a rare 100 when EI exceeds E_max.

from __future__ import annotations
from dataclasses import dataclass

@dataclass
class ScoreResult:
    score: int
    sport: str
    ei: float

# ----------------------------
# NBA (linear)
# ----------------------------
def _score_nba(ei: float) -> int:
    """
    NBA: Score = min(99, max(40, 4*EI + 40))
    EI is Σ|ΔWP| on a 0..1 scale per step (sum can exceed 1).
    """
    s = 4.0 * float(ei) + 40.0
    if s < 40:
        s = 40.0
    if s > 99:
        s = 99.0
    return int(round(s))

# ----------------------------
# NFL (piecewise, 2012–2024 REG calibration, true 40 floor)
# ----------------------------
NFL_E_MIN  = 0.636
NFL_E_MED  = 3.772
NFL_E_90   = 6.315
NFL_E_99   = 8.1511504
NFL_E_MAX  = 10.587

def _score_nfl(e: float) -> int:
    E = float(e)
    if E <= NFL_E_MIN:
        s = 40.0
    elif E <= NFL_E_MED:
        s = 40.0 + 30.0 * (E - NFL_E_MIN) / (NFL_E_MED - NFL_E_MIN)
    elif E <= NFL_E_90:
        s = 70.0 + 20.0 * (E - NFL_E_MED) / (NFL_E_90 - NFL_E_MED)
    elif E <= NFL_E_99:
        s = 90.0 + 9.0  * (E - NFL_E_90) / (NFL_E_99 - NFL_E_90)
    elif E <= NFL_E_MAX:
        s = 99.0 + 1.0  * (E - NFL_E_99) / (NFL_E_MAX - NFL_E_99)
    else:
        s = 100.0
    # Clamp visible floor to 40; allow rare 100 for outliers
    if s < 40.0: s = 40.0
    if s > 100.0: s = 100.0
    return int(round(s))

# ----------------------------
# MLB (piecewise, 2016–2025 REG calibration; 2020 excluded)
# ----------------------------
MLB_E_MIN  = 0.524
MLB_E_MED  = 2.380
MLB_E_90   = 6.312072
MLB_E_99   = 7.701617
MLB_E_MAX  = 9.426000

def _score_mlb(e: float) -> int:
    E = float(e)
    if E <= MLB_E_MIN:
        s = 40.0
    elif E <= MLB_E_MED:
        s = 40.0 + 30.0 * (E - MLB_E_MIN) / (MLB_E_MED - MLB_E_MIN)
    elif E <= MLB_E_90:
        s = 70.0 + 20.0 * (E - MLB_E_MED) / (MLB_E_90 - MLB_E_MED)
    elif E <= MLB_E_99:
        s = 90.0 + 9.0  * (E - MLB_E_90) / (MLB_E_99 - MLB_E_90)
    elif E <= MLB_E_MAX:
        s = 99.0 + 1.0  * (E - MLB_E_99) / (MLB_E_MAX - MLB_E_99)
    else:
        s = 100.0
    if s < 40.0: s = 40.0
    if s > 100.0: s = 100.0
    return int(round(s))

# ----------------------------
# Public entrypoint
# ----------------------------
def score_game(sport: str, ei: float) -> ScoreResult:
    """
    sport: 'NBA' | 'NFL' | 'MLB'  (UPPERCASE)
    ei: Excitement Index on decimal scale (0..1 per step; SUM of abs diffs)
    """
    key = (sport or "").upper().strip()
    # Defensive: if EI was accidentally given in percent points, convert
    E = float(ei)
    if E > 120:      # impossible if decimal-sum; definitely percent or garbage
        E = E / 100.0
    # Route to formula
    if key == "NBA":
        s = _score_nba(E)
    elif key == "NFL":
        s = _score_nfl(E)
    elif key == "MLB":
        s = _score_mlb(E)
    else:
        # Unknown sport: return safe floor so we don't publish junk
        s = 40
    return ScoreResult(score=s, sport=key, ei=E)
