"""
ESPN scoreboard adapter
Fetches games and normalizes them into a common structure.

Used by main.py for all supported leagues.
"""

from __future__ import annotations

import datetime
import requests
from typing import Dict, Any, List, Optional

ESPN_SCOREBOARD_API = (
    "https://site.api.espn.com/apis/site/v2/sports/{sport_group}/{league}/scoreboard"
)


def _log(msg: str) -> None:
    print(f"[ESPN] {msg}", flush=True)


def _get_espn_scoreboard(
    sport_group: str, league: str, date_iso: str
) -> Optional[Dict[str, Any]]:
    """
    Pull the ESPN scoreboard for a given date.
    Uses YYYYMMDD format required by ESPN.
    """
    # ESPN expects 20251130 instead of 2025-11-30
    y, m, d = date_iso.split("-")
    datestr = f"{y}{m}{d}"

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
        _log(f"could not decode JSON: {ex}")
        return None

    _log(f"scoreboard OK for {league.upper()} on {date_iso} via {url} dates={datestr}")
    return data


def _safe_team_abbrev(team_obj: Dict[str, Any]) -> str:
    """
    Get a consistent team abbreviation (3–4 letters).
    ESPN sometimes puts it in different fields.
    """
    if not team_obj:
        return ""

    # Try abbreviation first
    abbr = (
        team_obj.get("abbreviation")
        or team_obj.get("shortDisplayName")
        or team_obj.get("name")
        or ""
    )

    return str(abbr).upper().strip()


def _pick_national_broadcast(comp: Dict[str, Any]) -> str:
    """
    Return a simple network string if the game has a national/international broadcast.
    Handles cases where `names` may be a string or list.
    """
    casts = comp.get("broadcasts") or []
    if not casts:
        return ""

    # We only consider the first broadcast object
    b = casts[0] or {}

    names = b.get("names")
    short_name = b.get("shortName")
    long_name = b.get("name")

    # If `names` is a list, use the first string
    if isinstance(names, list) and names:
        candidate = names[0]
    else:
        candidate = names or short_name or long_name or ""

    return str(candidate).strip()


def parse_espn_scoreboard(
    data: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Convert ESPN data into our unified list of game dicts:
    {
        "id": str,
        "status": "FINAL" | "IN" | "UPCOMING",
        "start": "YYYY-MM-DD",
        "away": "TEAM",
        "home": "TEAM",
        "away_score": int,
        "home_score": int,
        "broadcast": str or "",
        "is_final": bool,
        "is_live": bool,
    }
    """
    out: List[Dict[str, Any]] = []

    if not data:
        return out

    events = data.get("events") or []
    _log(f"{len(events)} total {data.get('leagues',[{}])[0].get('abbreviation','')} events on scoreboard")

    for ev in events:
        gid = ev.get("id") or ev.get("uid") or ""
        comps = ev.get("competitions") or []
        if not comps:
            continue

        comp = comps[0]
        status_block = comp.get("status", {})
        status_type = status_block.get("type", {}).get("state", "")

        # Normalize ESPN status → our status flags
        if status_type == "post":
            status = "FINAL"
            is_final = True
            is_live = False
        elif status_type == "in":
            status = "IN"
            is_final = False
            is_live = True
        else:
            status = "UPCOMING"
            is_final = False
            is_live = False

        # Teams + scores
        competitors = comp.get("competitors") or []
        away_abbr = home_abbr = ""
        away_score = home_score = 0

        for c in competitors:
            team_obj = c.get("team", {})
            abbr = _safe_team_abbrev(team_obj)
            score = int(c.get("score") or 0)
            home_away = c.get("homeAway")

            if home_away == "away":
                away_abbr = abbr
                away_score = score
            elif home_away == "home":
                home_abbr = abbr
                home_score = score

        # Date
        date_raw = ev.get("date", "")
        try:
            dt = datetime.datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
            date_iso = dt.date().isoformat()
        except Exception:
            date_iso = ""

        # Broadcast
        broadcast = _pick_national_broadcast(comp)

        out.append(
            {
                "id": str(gid),
                "status": status,
                "is_final": is_final,
                "is_live": is_live,
                "start": date_iso,
                "away": away_abbr,
                "home": home_abbr,
                "away_score": away_score,
                "home_score": home_score,
                "broadcast": broadcast,
            }
        )

    return out


def get_games_for_date(
    league_up: str,
    date_iso: str,
) -> List[Dict[str, Any]]:
    """
    Main function called by main.py
    """
    league_up = (league_up or "").upper()

    if league_up == "NBA":
        scoreboard = _get_espn_scoreboard("basketball", "nba", date_iso)
    elif league_up == "WNBA":
        scoreboard = _get_espn_scoreboard("basketball", "wnba", date_iso)
    else:
        raise ValueError(f"Unsupported league for ESPN adapter: {league_up}")

    if not scoreboard:
        _log(f"[WARN] no scoreboard data for {league_up} on {date_iso}")
        return []

    return parse_espn_scoreboard(scoreboard)
