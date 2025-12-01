# espn_adapter.py
# ESPN scoreboard adapter for Rewatchability (basketball-only).
#
# Public API:
#   get_scoreboard(league_key: str, date_iso: str) -> list[dict]
#
# Returns a list of games shaped like:
#   {
#       "id": str,            # ESPN event id
#       "away": str,          # e.g. "Celtics"
#       "home": str,          # e.g. "Lakers"
#       "is_final": bool,     # True if completed/final
#       "broadcast": str,     # national network or "" if local/none
#   }

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

# Optional override: comma-separated list of scoreboard URL templates
# with {sport} and {league} placeholders.
SCOREBOARD_TEMPLATES_ENV = os.getenv("ESPN_SCOREBOARD_BASES", "")

# Optional overrides for sport/league path components.
SPORT_OVERRIDE = os.getenv("ESPN_SCOREBOARD_SPORT", "")  # usually "basketball"
NBA_LEAGUE_OVERRIDE = os.getenv("ESPN_SCOREBOARD_NBA_LEAGUE", "")
WNBA_LEAGUE_OVERRIDE = os.getenv("ESPN_SCOREBOARD_WNBA_LEAGUE", "")

# Treat only these as national / major streaming networks when deciding what to show.
NATIONAL_BROADCAST_KEYWORDS = [
    "ESPN",        # includes ESPN, ESPN2, ESPN+, etc.
    "TNT",
    "NBA TV",
    "ABC",
    "ION",
    "CBS",
    "FOX",
    "FS1",
    "PRIME VIDEO",
    "AMAZON",
    "PEACOCK",
    "MAX",         # e.g. NBA on TNT via Max
]


# ----------------------------------------------------------------------
# Utilities
# ----------------------------------------------------------------------


def _log(msg: str) -> None:
    print(f"[ESPN] {msg}", flush=True)


def _scoreboard_templates() -> List[str]:
    '''List of scoreboard base URLs with {sport} and {league} placeholders.

    If ESPN_SCOREBOARD_BASES is set, use that (comma-separated).
    Otherwise, use known-good defaults.
    '''
    if SCOREBOARD_TEMPLATES_ENV:
        tmpls = [t.strip() for t in SCOREBOARD_TEMPLATES_ENV.split(",") if t.strip()]
        if tmpls:
            return tmpls

    # Defaults: site.api and site.web.api variants
    return [
        "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard",
        "https://site.web.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard",
    ]


def _league_path(league_key: str) -> Dict[str, str]:
    '''Map external league key ("NBA"/"WNBA") into ESPN {sport}/{league} path pieces.'''
    lk = league_key.upper()
    sport = SPORT_OVERRIDE or "basketball"

    if lk == "NBA":
        league = NBA_LEAGUE_OVERRIDE or "nba"
    elif lk == "WNBA":
        league = WNBA_LEAGUE_OVERRIDE or "wnba"
    else:
        raise ValueError(f"Unsupported league_key for ESPN scoreboard: {league_key!r}")

    return {"sport": sport, "league": league}


def _fetch_json(url: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.get(url, params=params, timeout=10)
    except Exception as ex:
        _log(f"error fetching scoreboard: {ex}")
        return None

    if resp.status_code != 200:
        _log(f"GET {url} -> {resp.status_code}")
        return None

    try:
        return resp.json()
    except Exception as ex:
        _log(f"error decoding JSON from {url}: {ex}")
        return None


def _pick_national_broadcast(comp: Dict[str, Any]) -> str:
    '''Return a simple network string if the game has a national / major streaming broadcast.
    Local RSNs (BlazerVision, Spectrum SportsNet, MSG, NBC Sports regionals, etc.) are filtered out.'''
    casts = comp.get("broadcasts") or []
    if not casts:
        return ""

    def _name_from_b(b: Dict[str, Any]) -> str:
        names = b.get("names")
        if isinstance(names, list) and names:
            return str(names[0]).strip()
        return str(b.get("shortName") or b.get("name") or "").strip()

    # Prefer any broadcast whose name contains a known national keyword.
    for b in casts:
        name = _name_from_b(b)
        if not name:
            continue
        name_up = name.upper()
        if any(key in name_up for key in NATIONAL_BROADCAST_KEYWORDS):
            return name

    # If nothing national is found, treat as local-only and hide it.
    return ""


def _extract_teams(comp: Dict[str, Any]) -> Dict[str, str]:
    '''From a competition object, return {"away": short_name, "home": short_name}.'''
    away_name = ""
    home_name = ""
    for team in comp.get("competitors") or []:
        side = team.get("homeAway")
        tinfo = team.get("team") or {}
        # Prefer shortDisplayName (e.g. "76ers", "Trail Blazers", "Lakers")
        name = (
            tinfo.get("shortDisplayName")
            or tinfo.get("nickname")
            or tinfo.get("name")
            or tinfo.get("displayName")
            or tinfo.get("location")
            or ""
        )
        name = str(name).strip()
        if side == "away":
            away_name = name
        elif side == "home":
            home_name = name
    return {"away": away_name, "home": home_name}


def _is_final_event(event: Dict[str, Any]) -> bool:
    '''Determine if an ESPN event is effectively 'final'.'''
    comps = event.get("competitions") or []
    if not comps:
        return False
    comp = comps[0]
    status = comp.get("status") or event.get("status") or {}
    # ESPN has both a boolean "completed" and a status.type.name
    if status.get("type", {}).get("completed"):
        return True
    type_name = status.get("type", {}).get("name") or status.get("type", {}).get("state")
    if not type_name:
        return False
    type_name = str(type_name).upper()
    return type_name in {"STATUS_FINAL", "STATUS_END_OF_EVENT", "FINAL"}


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


def get_scoreboard(league_key: str, date_iso: str) -> List[Dict[str, Any]]:
    '''Fetch ESPN scoreboard for a given league ("NBA"/"WNBA") and date (YYYY-MM-DD).
    Returns a list of simplified game dicts.'''
    pieces = _league_path(league_key)
    sport = pieces["sport"]
    league = pieces["league"]

    # ESPN expects dates as YYYYMMDD
    date_compact = date_iso.replace("-", "")

    data: Optional[Dict[str, Any]] = None

    for tmpl in _scoreboard_templates():
        url = tmpl.format(sport=sport, league=league)
        params = {"dates": date_compact}
        # This log format matches what you're used to seeing in Render.
        _log(f"scoreboard OK for {league_key} on {date_iso} via {url} dates={date_compact}")
        data = _fetch_json(url, params)
        if data is not None:
            break

    if data is None:
        _log(f"no scoreboard data for {league_key} on {date_iso}")
        return []

    events = data.get("events") or []
    if not events:
        _log(f"0 total {league_key} events on {date_iso}")
        return []

    _log(f"{len(events)} total {league_key} events on {date_iso}")
    games_out: List[Dict[str, Any]] = []

    for ev in events:
        event_id = str(ev.get("id") or "").strip()
        comps = ev.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]

        is_final = _is_final_event(ev)

        teams = _extract_teams(comp)
        away_name = teams["away"]
        home_name = teams["home"]

        broadcast = _pick_national_broadcast(comp)

        games_out.append(
            {
                "id": event_id,
                "away": away_name,
                "home": home_name,
                "is_final": bool(is_final),
                "broadcast": broadcast,
            }
        )

    _log(f"{len(games_out)} total {league_key} events on {date_iso}")
    return games_out
