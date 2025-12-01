# espn_adapter.py
# ESPN scoreboard adapter for Rewatchability bot (basketball-only).
#
# Public API:
#   get_scoreboard(league_key: str, date_iso: str) -> list[dict]
#   get_final_like_events(...) -> convenience wrapper
#
# We only support:
#   - NBA
#   - WNBA
#
# We also EXCLUDE preseason games explicitly. We only keep:
#   - Regular season
#   - Playoffs / Play-In (non-preseason)

from __future__ import annotations

import os
from typing import Any, Dict, Final, List, Tuple

import requests

DEBUG: bool = os.getenv("DEBUG_ESPN", "1").lower() not in ("0", "false", "no")
TIMEOUT: float = float(os.getenv("ESPN_TIMEOUT", "8.0"))

USER_AGENT: str = os.getenv(
    "ESPN_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36",
)

HEADERS: Final[dict[str, str]] = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

# Only NBA + WNBA
LEAGUE_PATH: Final[dict[str, Tuple[str, str]]] = {
    "NBA": ("basketball", "nba"),
    "WNBA": ("basketball", "wnba"),
}


def _log(msg: str) -> None:
    if DEBUG:
        print(f"[ESPN] {msg}", flush=True)


def _scoreboard_urls(league_key: str) -> List[str]:
    sport, league = LEAGUE_PATH[league_key]
    return [
        f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard",
        f"https://site.web.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard",
    ]


def _get_json(url: str, params: dict[str, str]) -> Dict[str, Any] | None:
    try:
        _log(f"[DEBUG] GET {url} params={params}")
        resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code != 200:
            _log(f"[DEBUG] non-200 from {url}: {resp.status_code}")
            return None
        return resp.json()
    except Exception as ex:
        _log(f"[DEBUG] request error for {url}: {ex}")
        return None


def _is_final(comp: Dict[str, Any]) -> bool:
    status = (comp.get("status") or {}).get("type") or {}
    state = (status.get("state") or "").lower()
    completed = bool(status.get("completed"))
    return completed and state == "post"


def _is_in_season(comp: Dict[str, Any]) -> bool:
    """
    Filter out preseason games.

    ESPN season types are usually:
      1 = preseason
      2 = regular season
      3 = postseason
      4 = play-in
    We only keep 2/3/4.
    """
    season = comp.get("season") or {}
    try:
        season_type = int(season.get("type", 0))
    except (TypeError, ValueError):
        return True  # be permissive if missing
    return season_type in (2, 3, 4)


def _split_home_away(comp: Dict[str, Any]) -> Tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    home = None
    away = None
    for c in comp.get("competitors") or []:
        side = (c.get("homeAway") or "").lower()
        if side == "home":
            home = c
        elif side == "away":
            away = c
    return home, away


def _team_fields(team_wrapper: Dict[str, Any]) -> Tuple[str, str]:
    team = team_wrapper.get("team") or {}
    # Prefer ESPN's shortDisplayName (e.g., "Celtics") for UI-facing team names.
    name = (
        team.get("shortDisplayName")
        or team.get("displayName")
        or team.get("name")
        or "Team"
    )
    # Abbreviation is used for matching against inpredictable / PreCap.
    abbr = team.get("abbreviation") or name
    return name, abbr


def _extract_broadcast(comp: Dict[str, Any]) -> str:
    """Return the primary broadcast string, or "" if there isn't one.

    ESPN sometimes uses "broadcasts", sometimes "geoBroadcasts". We no longer
    return a placeholder like "Streaming / Local" because the caller only needs
    this field when there's an actual named TV/streaming network.
    """
    broadcasts = comp.get("broadcasts") or comp.get("geoBroadcasts") or []
    if not broadcasts:
        return ""

    b = broadcasts[0] or {}
    return (
        b.get("shortName")
        or b.get("name")
        or b.get("longName")
        or ""
    )


def get_scoreboard(league_key: str, date_iso: str) -> List[Dict[str, Any]]:
    """
    Return a normalized scoreboard for a given league/date.

    league_key: "NBA" or "WNBA"
    date_iso: "YYYY-MM-DD" in local game-day time
    """
    if league_key not in LEAGUE_PATH:
        raise ValueError(f"Unsupported league_key: {league_key!r}")

    # ESPN expects dates as YYYYMMDD
    dates_param = date_iso.replace("-", "")

    last_err = None
    data: Dict[str, Any] | None = None

    for url in _scoreboard_urls(league_key):
        data = _get_json(url, {"dates": dates_param})
        if data is not None:
            _log(
                f"[INFO] scoreboard OK for {league_key} on {date_iso} via "
                f"{url} dates={dates_param}"
            )
            break

    if data is None:
        raise RuntimeError(
            f"Could not fetch ESPN scoreboard for {league_key} {date_iso}; "
            f"last_err={last_err}"
        )

    events = data.get("events") or []
    out: List[Dict[str, Any]] = []

    for ev in events:
        competitions = ev.get("competitions") or []
        if not competitions:
            continue
        comp = competitions[0]

        if not _is_in_season(comp):
            # Skip preseason games
            continue

        home, away = _split_home_away(comp)
        if not home or not away:
            continue

        home_name, home_abbr = _team_fields(home)
        away_name, away_abbr = _team_fields(away)

        broadcast = _extract_broadcast(comp)

        event_id = ev.get("id") or comp.get("id")
        if not event_id:
            continue

        out.append(
            {
                "id": str(event_id),
                "home": home_name,
                "home_short": home_abbr,
                "away": away_name,
                "away_short": away_abbr,
                "broadcast": broadcast,
                "is_final": _is_final(comp),
            }
        )

    return out


def get_final_like_events(league_key: str, date_iso: str) -> List[Dict[str, Any]]:
    """
    Backwards-compatible helper:
    just filters get_scoreboard(...) down to final games.
    """
    return [g for g in get_scoreboard(league_key, date_iso) if g.get("is_final")]
