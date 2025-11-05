from dataclasses import dataclass

@dataclass
class ScoreResult:
    score: int  # final integer score to display (40–99 normally; 100 only at E_max+ for NFL/MLB)

# -----------------------------
# Helpers
# -----------------------------

def _ei_to_decimal(ei: float) -> float:
    """Accept EI in decimal (0–10+) or percentage (0–100). If >1.5, assume percentage and divide by 100."""
    try:
        e = float(ei)
    except Exception:
        raise ValueError("EI must be numeric")
    return e / 100.0 if e > 1.5 else e

def _round_int(x: float) -> int:
    """Round to nearest integer the way humans expect for a score display."""
    return int(round(x))

# -----------------------------
# NBA / NCAAM (linear)
# -----------------------------

def _score_nba(ei: float) -> int:
    # Score = clamp(4*EI + 40, 40..99)
    raw = 4.0 * ei + 40.0
    clamped = max(40.0, min(99.0, raw))
    return _round_int(clamped)

# NCAAM mirrors NBA curve
_score_ncaam = _score_nba

# -----------------------------
# NFL / NCAAF (piecewise; 2012–2024 reg-season calibration)
# -----------------------------

NFL_E_MIN = 0.636
NFL_E_MED = 3.772
NFL_E_90  = 6.315
NFL_E_99  = 8.1511504
NFL_E_MAX = 10.587

def _score_nfl(ei: float) -> int:
    E = ei
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
        # Rare all-timer
        s = 100.0
    # Clamp floor to 40; allow rare 100s by not capping at 99 here.
    return _round_int(max(40.0, s))

# NCAAF mirrors NFL curve
_score_ncaaf = _score_nfl

# -----------------------------
# MLB (piecewise; 2016–2025 reg-season calibration, 2020 excluded)
# -----------------------------

MLB_E_MIN = 0.524
MLB_E_MED = 2.380
MLB_E_90  = 6.312072
MLB_E_99  = 7.701617
MLB_E_MAX = 9.426000

def _score_mlb(ei: float) -> int:
    E = ei
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
    return _round_int(max(40.0, s))

# -----------------------------
# Public entry point
# -----------------------------

def score_game(sport: str, ei) -> ScoreResult:
    """
    Compute Rewatchability Score™ for a single game.
    - sport: one of 'NBA','NFL','MLB','NCAAF','NCAAM'
    - ei: Excitement Index (decimal). If passed as percentage (e.g., 875), we auto-convert.
    """
    s = sport.upper().strip()
    E = _ei_to_decimal(float(ei))

    if s == "NBA":
        score = _score_nba(E)
    elif s == "NCAAM":
        score = _score_ncaam(E)
    elif s == "NFL":
        score = _score_nfl(E)
    elif s == "NCAAF":
        score = _score_ncaaf(E)
    elif s == "MLB":
        score = _score_mlb(E)
    else:
        raise ValueError("Unsupported sport")

    return ScoreResult(score=score)
