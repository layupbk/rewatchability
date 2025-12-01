import requests
import re

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
# FETCH PRECIP HTML
# -----------------------------------------------------------

def fetch_precap_html(sport):
    if sport == "NBA":
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
# PARSE FINISHED GAMES FROM PRECIP HTML
# -----------------------------------------------------------

ROW_REGEX = re.compile(
    r'([A-Z]{3})\s*@\s*([A-Z]{3}).+?Finished.+?([\d\.]+)',
    re.DOTALL
)

def parse_precap_finished_games(html: str, sport: str):
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
        except:
            continue

        if sport == "NBA":
            if away not in TEAM_MAP_NBA or home not in TEAM_MAP_NBA:
                continue
        else:
            if away not in TEAM_MAP_WNBA or home not in TEAM_MAP_WNBA:
                continue

        key = f"{away}@{home}"
        excitement_map[key] = excite_val

    print(f"[INPRED] parsed {len(excitement_map)} finished games from PreCap for {sport}")
    return excitement_map


# -----------------------------------------------------------
# MAIN FUNCTION CALLED BY main.py
# -----------------------------------------------------------

def get_excitation_for_date(sport: str, date_str: str):
    """
    Returns dict:
      "source"             Always "INPREDICTABLE"
      "excitement_map"     Dict { "ATL@PHI": 13.7 }
      "error"              If error occurred
    """

    html, err = fetch_precap_html(sport)
    if err:
        return {"source": "INPREDICTABLE", "excitement_map": {}, "error": err}

    excitement_map = parse_precap_finished_games(html, sport)
    return {"source": "INPREDICTABLE", "excitement_map": excitement_map, "error": None}
