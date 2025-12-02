import requests
import re
import datetime
from typing import Dict, Tuple, Optional

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
# PARSE PRECAP HEADER DATE ("For Games Played on ...")
# -----------------------------------------------------------

# Example header text:
#   "For Games Played on November 30, 2025"
_PRECAP_DATE_REGEX = re.compile(
    r"For Games Played on ([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})",
    re.IGNORECASE,
)


def _parse_precap_date_iso(html: str) -> Optional[str]:
    """
    Extract the 'For Games Played on Month DD, YYYY' header and return
    it as 'YYYY-MM-DD'. If not found or invalid, return None.
    """
    if not html:
        return None

    m = _PRECAP_DATE_REGEX.search(html)
    if not m:
        return None

    month_name, day_str, year_str = m.groups()
    try:
        dt = datetime.datetime.strptime(
            f"{month_name} {int(day_str)}, {int(year_str)}",
            "%B %d, %Y",
        ).date()
    except Exception:
        return None

    return dt.isoformat()


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

def fetch_excitement_map(
    sport: str,
    expected_date_iso: Optional[str] = None,
) -> Dict[Tuple[str, str], float]:
    """
    Return a mapping {(AWAY_CODE, HOME_CODE): excitement_float} for all
    finished games currently listed on Inpredictable's PreCap page.

    If expected_date_iso is provided (YYYY-MM-DD), we will:
      - Parse the header 'For Games Played on Month DD, YYYY'
      - Convert it to YYYY-MM-DD
      - If it does NOT match expected_date_iso, we treat PreCap as
        stale/mismatched and return an EMPTY map.

    This guarantees we never apply yesterday's EI to today's games,
    even if the same teams play back-to-back in the same arena.
    """
    sport_up = sport.upper()

    html, err = fetch_precap_html(sport_up)
    if err:
        raise RuntimeError(f"PreCap fetch failed for {sport_up}: {err}")

    header_date_iso = _parse_precap_date_iso(html)

    if expected_date_iso is not None:
        if header_date_iso is None:
            print(
                f"[INPRED WARNING] {sport_up}: could not parse PreCap header date; "
                f"expected {expected_date_iso}. Ignoring EI for safety.",
                flush=True,
            )
            return {}

        if header_date_iso != expected_date_iso:
            print(
                f"[INPRED WARNING] {sport_up}: PreCap date {header_date_iso} "
                f"!= expected {expected_date_iso}. Ignoring EI for safety.",
                flush=True,
            )
            return {}

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

    return tuple_map


def get_excitation_for_date(sport: str, date_str: str):
    """
    Legacy wrapper that returns a dict in the older format:

      {
        "source": "INPREDICTABLE",
        "excitement_map": {"ATL@PHI": 13.7},
        "error": None or str,
      }

    date_str is used as expected_date_iso so we only return EI when the
    PreCap header date matches date_str.
    """
    try:
        tuple_map = fetch_excitement_map(sport, expected_date_iso=date_str)
    except Exception as e:
        return {
            "source": "INPREDICTABLE",
            "excitement_map": {},
            "error": str(e),
        }

    legacy_map = {f"{a}@{h}": val for (a, h), val in tuple_map.items()}
    return {
        "source": "INPREDICTABLE",
        "excitement_map": legacy_map,
        "error": None,
    }
