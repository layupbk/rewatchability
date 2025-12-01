import requests
import re
from typing import Dict, Tuple

# -----------------------------------------------------------
# HARD-MAPPED TEAM NAME TRANSLATION (ESPN -> INPREDICTABLE)
# -----------------------------------------------------------

TEAM_MAP_NBA = {
    "ATL": "ATL",
    "BKN": "BKN",
    "BOS": "BOS",
    "CHA": "CHA",
    "CHI": "CHI",
    "CLE": "CLE",
    "DAL": "DAL",
    "DEN": "DEN",
    "DET": "DET",
    "GSW": "GSW",
    "HOU": "HOU",
    "IND": "IND",
    "LAC": "LAC",
    "LAL": "LAL",
    "MEM": "MEM",
    "MIA": "MIA",
    "MIL": "MIL",
    "MIN": "MIN",
    "NOP": "NOP",
    "NYK": "NYK",
    "OKC": "OKC",
    "ORL": "ORL",
    "PHI": "PHI",
    "PHX": "PHX",
    "POR": "POR",
    "SAC": "SAC",
    "SAS": "SAS",
    "TOR": "TOR",
    "UTA": "UTA",
    "WAS": "WAS",
}

TEAM_MAP_WNBA = {
    "ATL": "ATL",
    "CHI": "CHI",
    "CON": "CON",
    "DAL": "DAL",
    "IND": "IND",
    "LAS": "LAS",
    "LVA": "LVA",
    "MIN": "MIN",
    "NYL": "NYL",
    "PHX": "PHX",
    "SEA": "SEA",
    "WAS": "WAS",
    "GSV": "GSV",
}

# -----------------------------------------------------------
# FETCH PRECAP HTML
# -----------------------------------------------------------

def fetch_precap_html(sport: str):
    """
    Fetch the Inpredictable PreCap page for the given sport.

    Currently only NBA has a PreCap page; WNBA will return an error.
    Returns (html_text, error_message). If error_message is not None,
    html_text will be None.
    """
    sport_up = sport.upper()
    if sport_up == "NBA":
        url = "https://stats.inpredictable.com/nba/preCapOld.php"
    else:
        return None, "Invalid sport"

    try:
        r = requests.get(url, timeout=10)
    except Exception as e:
        return None, str(e)

    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"

    return r.text, None


# -----------------------------------------------------------
# PARSE FINISHED GAMES FROM PRECAP HTML
# -----------------------------------------------------------

ROW_REGEX = re.compile(
    r"([A-Z]{3})\s*@\s*([A-Z]{3}).+?Finished.+?([\d\.]+)",
    re.DOTALL,
)


def parse_precap_finished_games(html: str, sport: str):
    """
    Parse the PreCap HTML and return a mapping like {"ATL@PHI": 13.7}.
    """
    if not html:
        print("[INPRED] blank HTML")
        return {}

    matches = ROW_REGEX.findall(html)
    if not matches:
        print("[INPRED] no matches found in HTML")
        return {}

    excitement_map = {}

    for away, home, excite in matches:
        try:
            excite_val = float(excite)
        except Exception:
            continue

        sport_up = sport.upper()
        if sport_up == "NBA":
            if away not in TEAM_MAP_NBA or home not in TEAM_MAP_NBA:
                continue
        else:
            if away not in TEAM_MAP_WNBA or home not in TEAM_MAP_WNBA:
                continue

        key = f"{away}@{home}"
        excitement_map[key] = excite_val

    print(
        f"[INPRED] parsed {len(excitement_map)} finished games from PreCap for {sport}"
    )
    return excitement_map


# -----------------------------------------------------------
# PUBLIC API USED BY main.py
# -----------------------------------------------------------

# Simple in-process cache so we don't hammer PreCap on every poll
_PRECAP_CACHE: Dict[str, Dict[Tuple[str, str], float]] = {}


def fetch_excitement_map(sport: str) -> Dict[Tuple[str, str], float]:
    """
    Return a mapping {(AWAY_CODE, HOME_CODE): excitement_float} for all
    finished games currently listed on Inpredictable's PreCap page.

    main.py expects this tuple-keyed structure so it can look up values
    using (away_code, home_code).
    """
    sport_up = sport.upper()
    if sport_up in _PRECAP_CACHE:
        return _PRECAP_CACHE[sport_up]

    html, err = fetch_precap_html(sport_up)
    if err:
        # Let the caller's try/except handle this
        raise RuntimeError(f"PreCap fetch failed for {sport_up}: {err}")

    string_map = parse_precap_finished_games(html, sport_up)

    tuple_map: Dict[Tuple[str, str], float] = {}
    for key, excite in string_map.items():
        if "@" not in key:
            continue
        away, home = key.split("@", 1)
        away = away.strip().upper()
        home = home.strip().upper()
        if not away or not home:
            continue
        tuple_map[(away, home)] = excite

    _PRECAP_CACHE[sport_up] = tuple_map
    return tuple_map


def get_excitation_for_date(sport: str, date_str: str):
    """
    Legacy wrapper that returns a dict in the older format used by some
    other scripts:

      {
        "source": "INPREDICTABLE",
        "excitement_map": {"ATL@PHI": 13.7},
        "error": None or str,
      }

    date_str is unused because PreCap always shows the current day.
    """
    try:
        tuple_map = fetch_excitement_map(sport)
    except Exception as e:
        return {
            "source": "INPREDICTABLE",
            "excitement_map": {},
            "error": str(e),
        }

    # Convert back to "AWAY@HOME" string keys for compatibility
    legacy_map = {f"{a}@{h}": val for (a, h), val in tuple_map.items()}
    return {
        "source": "INPREDICTABLE",
        "excitement_map": legacy_map,
        "error": None,
    }
