"""
Rewatchability Score – Piecewise Scoring Engine
Updated to v1 EI constants (NBA / NFL / MLB / NCAAF / NCAAB)
"""

# ============================================================
#  NEW V1 CONSTANTS (based on your latest cleaned datasets)
# ============================================================

# ---------- NBA ----------
NBA_E_MIN = 0.00536
NBA_E_MED = 0.16262
NBA_E_90  = 0.2632740
NBA_E_99  = 0.3418272
NBA_E_MAX = 0.42322

# ---------- NFL ----------
NFL_E_MIN = 0.00984
NFL_E_MED = 0.087269
NFL_E_90  = 0.1444728
NFL_E_99  = 0.22292766
NFL_E_MAX = 0.297374

# ---------- MLB ----------
MLB_E_MIN = 0.00326
MLB_E_MED = 0.04436
MLB_E_90  = 0.0755340
MLB_E_99  = 0.1103992
MLB_E_MAX = 0.16694

# ---------- NCAAF ----------
NCAAF_E_MIN = 0.000026
NCAAF_E_MED = 0.060416
NCAAF_E_90  = 0.127918
NCAAF_E_99  = 0.1876307
NCAAF_E_MAX = 0.286786

# ---------- NCAAB ----------
NCAAB_E_MIN = 0.00002
NCAAB_E_MED = 0.07897
NCAAB_E_90  = 0.156834
NCAAB_E_99  = 0.2132926
NCAAB_E_MAX = 0.33728


# ============================================================
#  UNIVERSAL PIECEWISE SCORING FUNCTION
# ============================================================

def piecewise_score(EI, E_MIN, E_MED, E_90, E_99, E_MAX):
    """
    Universal piecewise 40→70→90→99→100 scoring formula.
    Scores are always clamped to [40, 100] and rounded to nearest int.
    """

    if EI <= E_MIN:
        return 40

    # 40 → 70 region
    if EI <= E_MED:
        frac = (EI - E_MIN) / (E_MED - E_MIN)
        return round(40 + frac * 30)

    # 70 → 90 region
    if EI <= E_90:
        frac = (EI - E_MED) / (E_90 - E_MED)
        return round(70 + frac * 20)

    # 90 → 99 region
    if EI <= E_99:
        frac = (EI - E_90) / (E_99 - E_90)
        return round(90 + frac * 9)

    # 99 → 100 region
    if EI <= E_MAX:
        frac = (EI - E_99) / (E_MAX - E_99)
        return round(99 + frac * 1)

    return 100


# ============================================================
#  SPORT-SPECIFIC SCORE ROUTERS
# ============================================================

def score_nba(ei):
    return piecewise_score(ei, NBA_E_MIN, NBA_E_MED, NBA_E_90, NBA_E_99, NBA_E_MAX)

def score_nfl(ei):
    return piecewise_score(ei, NFL_E_MIN, NFL_E_MED, NFL_E_90, NFL_E_99, NFL_E_MAX)

def score_mlb(ei):
    return piecewise_score(ei, MLB_E_MIN, MLB_E_MED, MLB_E_90, MLB_E_99, MLB_E_MAX)

def score_ncaaf(ei):
    return piecewise_score(ei, NCAAF_E_MIN, NCAAF_E_MED, NCAAF_E_90, NCAAF_E_99, NCAAF_E_MAX)

def score_ncaab(ei):
    return piecewise_score(ei, NCAAB_E_MIN, NCAAB_E_MED, NCAAB_E_90, NCAAB_E_99, NCAAB_E_MAX)


# ============================================================
#  MAIN DISPATCH
# ============================================================

def score_game(sport, ei):
    sport = sport.lower()

    if sport == "nba":
        return score_nba(ei)
    if sport == "nfl":
        return score_nfl(ei)
    if sport == "mlb":
        return score_mlb(ei)
    if sport in ("ncaaf", "cfb", "college-football"):
        return score_ncaaf(ei)
    if sport in ("ncaab", "cbb", "college-basketball"):
        return score_ncaab(ei)

    raise ValueError(f"Unknown sport '{sport}' for scoring.")
