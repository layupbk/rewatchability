"""
ESPN scoreboard adapter for Rewatchability (basketball-only).

Public API:
    get_scoreboard(league_key: str, date_iso: str) -> list[dict]

Returns a list of games shaped like:
    {
        "id": str,        # ESPN event id
        "away": str,      # e.g. "Celtics"
        "home": str,      # e.g. "Lakers"
        "is_final": bool, # True if completed/final
        "broadcast": str, # national network or "" if local/none
    }
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

import requests

ESPN_SCOREBOARD_API = (
    "https://site.api.espn.com/apis/site/v2/sports/{sport_group}/{league}/scoreboard"
)


def _log(msg: str) -> None:
    print(f"[ESPN] {msg}", flush=True)


def _get_espn_scoreboard(
    sport_group: str,
    league: str,
    date_iso: str,
) -> Optional[Dict[str, Any]]:
    """
    Fetch raw ESPN scoreboard JSON for the given date (YYYY-MM-DD).
    ESPN expects the date as YYYYMMDD in the query string.
    """
    try:
        year, month, day = date_iso.split("-")
    except ValueError:
        _log(f"bad date_iso {date_iso!r} (expected YYYY-MM-DD)")
        return None

    datestr = f"{year}{month}{day}"
    url = ESPN_SCOREBOARD_API.format(sport_group=sport_group, league=league)
    params = {"dates": datestr}

    try:
        resp = requests.get(url, params=params, timeout=10)
    except Exception as ex:
        _log(f"error contacting ESPN: {ex}")
        return None

    if resp.status_code != 200:
        _log(f"bad status {resp.status_code} for scoreboard fetch")
        return None

    try:
        data = resp.json()
    except Exception as ex:
        _log(f"could not decode ESPN JSON: {ex}")
        return None

    _log(
        f"scoreboard OK for {league.upper()} on {date_iso} via {url} dates={datestr}"
    )
    return data


def _safe_team_name(team_obj: Dict[str, Any]) -> str:
    """
    Normalize a team name that matches our NAME_TO_INPRED mapping
    (e.g., 'Hawks', 'Cavaliers', 'Liberty').
    """
    if not team_obj:
        return ""

    # ESPN usually has "shortDisplayName" = "Hawks", "Lakers", etc.
    name = (
        team_obj.get("shortDisplayName")
        or team_obj.get("name")
        or team_obj.get("abbreviation")
        or ""
    )
    return str(name).strip()


def _pick_national_broadcast(comp: Dict[str, Any]) -> str:
    """
    Return a simple network string if the game has a national/international broadcast.
    Safely handles the case where `names` is a list.
    """
    casts = comp.get("broadcasts") or []
    if not casts:
        return ""

    b = casts[0] or {}

    names = b.get("names")
    short_name = b.get("shortName")
    long_name = b.get("name")

    # `names` can be a list like ["ESPN", "ESPN2"] or a single string.
    if isinstance(names, list) and names:
        candidate = names[0]
    else:
        candidate = names or short_name or long_name or ""

    return str(candidate).strip()


def get_scoreboard(league_key: str, date_iso: str) -> List[Dict[str, Any]]:
    """
    Fetch ESPN scoreboard for the given league ("NBA" or "WNBA") and date (YYYY-MM-DD).

    Returns a list of simplified game dicts:
        {
            "id": str,
            "away": str,
            "home": str,
            "is_final": bool,
            "broadcast": str,
        }
    """
    league_key = (league_key or "").upper()

    if league_key == "NBA":
        sport_group = "basketball"
        league = "nba"
    elif league_key == "WNBA":
        sport_group = "basketball"
        league = "wnba"
    else:
        raise ValueError(f"Unsupported league for ESPN adapter: {league_key!r}")

    raw = _get_espn_scoreboard(sport_group, league, date_iso)
    if not raw:
        _log(f"[WARN] no scoreboard data for {league_key} on {date_iso}")
        return []

    events = raw.get("events") or []
    games_out: List[Dict[str, Any]] = []

    for ev in events:
        event_id = str(ev.get("id") or ev.get("uid") or "")

        comps = ev.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]

        # Determine game state
        status_block = comp.get("status") or {}
        st_type = (status_block.get("type") or {}).get("state") or ""
        st_type = str(st_type).lower()

        if st_type == "post":
            is_final = True
        else:
            is_final = False

        # Collect teams
        away_name = ""
        home_name = ""

        for c in comp.get("competitors") or []:
            team_obj = c.get("team") or {}
            name = _safe_team_name(team_obj)
            side = c.get("homeAway")
            if side == "away":
                away_name = name
            elif side == "home":
                home_name = name

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
