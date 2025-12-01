# espn_adapter.py
#
# ESPN scoreboard adapter for basketball-only (NBA + WNBA).
# Returns a simplified list of game dicts per date:
#
#   {
#       "id": "401810163",
#       "sport": "NBA",
#       "date": "2025-11-30",
#       "is_final": True/False,
#       # display names (nicknames only, e.g. "Celtics")
#       "away": "Celtics",
#       "home": "Cavaliers",
#       # abbreviations used for Inpredictable PreCap (e.g. "BOS", "CLE")
#       "away_short": "BOS",
#       "home_short": "CLE",
#       # full names like "Boston Celtics" if you ever need them
#       "away_full": "Boston Celtics",
#       "home_full": "Cleveland Cavaliers",
#       # national TV/streaming only ("" if local/unknown)
#       "broadcast": "ESPN"  # or "", "TNT", "ESPN, ABC", etc.
#   }

from __future__ import annotations

from typing import Any, Dict, List
import datetime
import requests

# ----------------------------------------------------------------------
# League → ESPN path
# ----------------------------------------------------------------------

_LEAGUE_PATHS: Dict[str, str] = {
    "NBA": "basketball/nba",
    "WNBA": "basketball/wnba",
}


def _scoreboard_url(league: str) -> str:
    league_up = league.upper()
    if league_up not in _LEAGUE_PATHS:
        raise ValueError(f"Unsupported league for ESPN scoreboard: {league!r}")
    return f"https://site.api.espn.com/apis/site/v2/sports/{_LEAGUE_PATHS[league_up]}/scoreboard"


def _fetch_scoreboard(league: str, date_iso: str) -> Dict[str, Any]:
    """
    Fetch scoreboard JSON for the given league and date (YYYY-MM-DD).
    """
    url = _scoreboard_url(league)
    dates_param = date_iso.replace("-", "")

    params = {"dates": dates_param}
    print(f"[ESPN] [DEBUG] GET {url} params={params}", flush=True)

    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        print(f"[ESPN] [WARN] scoreboard HTTP {resp.status_code} for {league} on {date_iso}", flush=True)
        resp.raise_for_status()

    data = resp.json()
    print(
        f"[ESPN] [INFO] scoreboard OK for {league} on {date_iso} via {url} dates={dates_param}",
        flush=True,
    )
    return data


def _is_final(competition: Dict[str, Any]) -> bool:
    status = competition.get("status", {}).get("type", {})
    state = (status.get("state") or "").lower()
    completed = bool(status.get("completed"))
    return completed or state in ("post", "final", "status_final")


def _is_preseason(event: Dict[str, Any]) -> bool:
    """
    Filter out preseason games.
    ESPN season types are typically:
      1 = preseason, 2 = regular season, 3+ = playoffs/play-in.
    """
    season_type = event.get("season", {}).get("type")
    return season_type == 1


def _extract_team_fields(team_comp: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract abbreviation + nickname + full display name for one team.
    """
    t = team_comp.get("team") or {}

    abbrev = (t.get("abbreviation") or "").upper().strip()
    # ESPN usually:
    #   "abbreviation": "BOS"
    #   "name": "Celtics"
    #   "shortDisplayName": "Celtics"
    #   "displayName": "Boston Celtics"
    nickname = (t.get("name") or t.get("shortDisplayName") or "").strip()
    full_name = (t.get("displayName") or f"{nickname}").strip()

    return {
        "abbrev": abbrev,
        "nickname": nickname,
        "full": full_name,
    }


def _extract_broadcast(competition: Dict[str, Any]) -> str:
    """
    Build a single broadcast string with ONLY national / international networks.
    Returns "" for local-only or unknown coverage.
    """
    broadcasts = competition.get("broadcasts") or []
    national_names: List[str] = []

    for b in broadcasts:
        market = (b.get("market") or "").lower()
        names = b.get("names") or []

        # Treat "national" & "international" as "national coverage" for our purposes.
        if market in ("national", "international"):
            for n in names:
                n = (n or "").strip()
                if n and n not in national_names:
                    national_names.append(n)

    if not national_names:
        return ""

    return ", ".join(national_names)


def get_scoreboard(league: str, date_iso: str) -> List[Dict[str, Any]]:
    """
    Public API: fetch every non-preseason event for the given basketball league & date.

    Returns a list of standardized game dicts (see module docstring).
    """
    league_up = league.upper()
    data = _fetch_scoreboard(league_up, date_iso)

    events = data.get("events") or []
    print(f"[ESPN] {len(events)} total {league_up} events on {date_iso}", flush=True)

    results: List[Dict[str, Any]] = []

    for event in events:
        if _is_preseason(event):
            # Skip preseason
            continue

        competitions = event.get("competitions") or []
        if not competitions:
            continue
        comp = competitions[0]

        competitors = comp.get("competitors") or []
        if len(competitors) < 2:
            continue

        # identify home/away
        away_comp = None
        home_comp = None
        for c in competitors:
            ha = c.get("homeAway")
            if ha == "away":
                away_comp = c
            elif ha == "home":
                home_comp = c

        if not away_comp or not home_comp:
            continue

        away_fields = _extract_team_fields(away_comp)
        home_fields = _extract_team_fields(home_comp)

        broadcast = _extract_broadcast(comp)
        is_final = _is_final(comp)

        game: Dict[str, Any] = {
            "id": event.get("id"),
            "sport": league_up,
            "date": date_iso,
            "is_final": is_final,
            # nicknames only, for display (e.g. "Celtics")
            "away": away_fields["nickname"],
            "home": home_fields["nickname"],
            # full names just in case (e.g. "Boston Celtics")
            "away_full": away_fields["full"],
            "home_full": home_fields["full"],
            # abbreviations used to match Inpredictable PreCap keys
            "away_short": away_fields["abbrev"],
            "home_short": home_fields["abbrev"],
            # national/international coverage only; "" if local/unknown
            "broadcast": broadcast,
        }

        results.append(game)

    return results
