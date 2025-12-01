# espn_adapter.py
#
# Small wrapper around ESPN's public scoreboard API.
# Normalizes the response into a simple list of dicts that main.py can use.

from __future__ import annotations

from typing import Any, Dict, List

import requests


_LEAGUE_PATH = {
    "NBA": "nba",
    "WNBA": "wnba",
}


def _log(msg: str) -> None:
    print(msg, flush=True)


def _pick_national_broadcast(comp: Dict[str, Any]) -> tuple[str, bool]:
    """
    Return (broadcast_label, is_national).

    We ONLY treat something as 'national' if ESPN marks the broadcast market
    as 'national'. This avoids local RSNs / team streams like 'BlazerVision'.
    """
    broadcasts = comp.get("broadcasts") or []

    # First pass: true national TV
    for b in broadcasts:
        market = (b.get("market") or "").lower()
        if market != "national":
            continue

        names = b.get("names") or []
        if names:
            return names[0], True

        # Fallback: sometimes the label is in media.shortName
        media = b.get("media") or {}
        short_name = media.get("shortName") or media.get("shortText")
        if short_name:
            return short_name, True

    # No national broadcast found
    return "", False


def get_scoreboard(sport: str, date_iso: str) -> List[Dict[str, Any]]:
    """
    Fetch ESPN's scoreboard for a given sport and ISO date (YYYY-MM-DD).

    Returns a list of game dicts with at least:
      - id: ESPN event id (str)
      - status: e.g. 'STATUS_FINAL', 'STATUS_IN_PROGRESS'
      - is_final: bool
      - away, home: full team names
      - away_abbr, home_abbr: ESPN abbreviations (ATL, PHI, etc.)
      - broadcast: national network label ('' if none)
      - is_national: bool
    """
    sport_up = sport.upper()
    path = _LEAGUE_PATH.get(sport_up)
    if not path:
        raise ValueError(f"Unsupported sport for ESPN scoreboard: {sport}")

    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/{path}/scoreboard"
    params = {"dates": date_iso.replace("-", "")}

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
    except Exception as ex:
        _log(
            f"[ESPN ERROR] scoreboard fetch failed for {sport_up} {date_iso}: {ex}"
        )
        return []

    data = resp.json()
    events = data.get("events") or []

    _log(
        f"[ESPN] scoreboard OK for {sport_up} on {date_iso} "
        f"via {resp.url}"
    )

    games: List[Dict[str, Any]] = []

    for ev in events:
        try:
            event_id = str(ev.get("id"))
            competitions = ev.get("competitions") or []
            if not competitions:
                continue

            comp = competitions[0]

            status_info = comp.get("status") or {}
            status_type = status_info.get("type") or {}
            status_name = status_type.get("name") or ""
            is_final = bool(status_type.get("completed"))

            competitors = comp.get("competitors") or []
            if len(competitors) < 2:
                continue

            away_team = None
            home_team = None
            for c in competitors:
                side = (c.get("homeAway") or "").lower()
                if side == "away":
                    away_team = c
                elif side == "home":
                    home_team = c

            if not away_team or not home_team:
                continue

            away_info = away_team.get("team") or {}
            home_info = home_team.get("team") or {}

            away_name = away_info.get("shortDisplayName") or away_info.get(
                "displayName"
            ) or ""
            home_name = home_info.get("shortDisplayName") or home_info.get(
                "displayName"
            ) or ""

            away_abbr = away_info.get("abbreviation") or ""
            home_abbr = home_info.get("abbreviation") or ""

            broadcast_label, is_national = _pick_national_broadcast(comp)

            games.append(
                {
                    "id": event_id,
                    "status": status_name,
                    "is_final": is_final,
                    "away": away_name,
                    "home": home_name,
                    "away_abbr": away_abbr,
                    "home_abbr": home_abbr,
                    "broadcast": broadcast_label,
                    "is_national": is_national,
                }
            )
        except Exception as ex:
            _log(f"[ESPN WARN] could not parse event: {ex}")

    _log(f"[ESPN] {len(games)} total {sport_up} events on {date_iso}")
    return games
